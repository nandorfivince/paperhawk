"""validator_node — source citation check (anti-hallucination).

Verifies that:
  1. At least 1 tool call ran (otherwise skip — e.g. "thanks" message)
  2. The final_answer contains a [Source: X] citation or filename mention
  3. The answer is at least 20 chars
  4. The cited filenames actually appear in the tool outputs

If any of these fail and ``retry_count < settings.validator_max_retries``,
go back to the agent with a HumanMessage: "Please re-call the tools and
include [Source: filename] citations."
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, ToolMessage

from config import settings
from graph.states.chat_state import ChatState


_FILENAME_PATTERN = re.compile(r"\b([\w_\-]+\.(?:pdf|docx|png|jpg|jpeg|txt))\b", re.I)
_SOURCE_PATTERN = re.compile(r"\[(?:Source|Forrás)[:\s]+([^\]]+)\]", re.I)


async def validator_node(state: ChatState) -> dict:
    """Check the final_answer for source citations."""
    final_answer = state.get("final_answer", "")
    messages = state.get("messages") or []
    retry_count = state.get("validator_retry_count", 0)

    # Was there a tool call?
    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
    if not tool_msgs:
        # No tool — plain chat answer, no source check
        return {
            "trace": ["validator: no tool call → skipped"],
            "sources_cited": [],
        }

    # 1. At least 20 chars
    if len(final_answer.strip()) < 20:
        if retry_count < settings.validator_max_retries:
            return _retry(state, retry_count, "The answer is too short (< 20 chars).")
        # Max retry → let it through
        return {
            "trace": ["validator: too short, but max retry → end"],
            "sources_cited": [],
        }

    # 2. Source citation check
    source_matches = _SOURCE_PATTERN.findall(final_answer)
    filename_mentions = _FILENAME_PATTERN.findall(final_answer)

    if not source_matches and not filename_mentions:
        if retry_count < settings.validator_max_retries:
            return _retry(state, retry_count, "Missing source citation in [Source: filename] format.")
        return {
            "trace": ["validator: no source citation, but max retry → end"],
            "sources_cited": [],
        }

    # 3. Do the cited filenames actually appear in the tool outputs?
    available_files: set[str] = set()
    for tm in tool_msgs:
        content = str(tm.content)
        for match in _FILENAME_PATTERN.findall(content):
            available_files.add(match.lower())

    cited_files = []
    for citation in source_matches:
        # Multiple filenames separated by comma (e.g. [Source: a.pdf, b.pdf])
        for f in re.split(r"[,;]", citation):
            f = f.strip()
            if f:
                cited_files.append(f)
    cited_files.extend(filename_mentions)

    invalid_citations = [
        c for c in cited_files
        if c.lower() not in available_files and not any(
            c.lower() in af for af in available_files
        )
    ]

    if invalid_citations and retry_count < settings.validator_max_retries:
        return _retry(state, retry_count,
                      f"Cited filenames are not in the tool results: {invalid_citations}")

    return {
        "trace": [f"validator: ok (sources: {cited_files[:3]})"],
        "sources_cited": list({c.lower() for c in cited_files}),
    }


def _retry(state: ChatState, retry_count: int, reason: str) -> dict:
    """Go back to the agent with a HumanMessage."""
    msg = HumanMessage(content=(
        f"Your answer is not acceptable: {reason} "
        "Please re-call the tools and include [Source: filename.pdf] citations."
    ))
    return {
        "messages": [msg],
        "validator_retry_count": retry_count + 1,
        "trace": [f"validator: retry {retry_count + 1} ({reason})"],
    }
