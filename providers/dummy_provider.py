"""DummyChatModel — deterministic stub LLM for eval, load, and smoke tests.

A subclass of ``langchain_core.language_models.chat_models.BaseChatModel`` that:

  * NEVER hits the network (offline, fast, < 1 ms)
  * returns deterministic responses for the same input (eval reproducibility)
  * supports ``bind_tools()`` (the full ChatGraph runs in dummy mode)
  * supports ``with_structured_output()`` (extract / classify / risk dummy mode)
  * streams responses in chunks (UI streaming test)

Design principle: the keyword-router and ``set_docs_hint`` mechanisms originate
from an earlier baseline (LangGraph rag-chatbot) but are tailored here to the
5 chat tools and 6 schemas of THIS system. We do not import from any other
project — every behavior is implemented here.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field


# ---------------------------------------------------------------------------
# Intent rules — keyword regex routing for the 5 chat tools
# ---------------------------------------------------------------------------
# The system uses 6 chat intents (see nodes/chat/intent_classifier_node.py).
# The dummy uses simplified regexes here so the full ChatGraph can be tested
# without an LLM.
#
# English-first patterns with multilingual fallback (HU/DE/FR snippets) so
# multilingual demo flows keep working in dummy mode.
# Order MATTERS — first match wins; specific intents come before generic ones.
# Global, instance-independent docs_hint — the configurable_alternatives pattern
# may instantiate multiple DummyChatModel instances; they share this list.
_GLOBAL_DOCS_HINT: list[str] = []


_INTENT_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "compare",
        re.compile(
            r"\b(compar\w*|differ\w*|diff|versus|\bvs\b|cheap\w*|expensiv\w*|"
            r"hasonlit\w*|elter\w*|kulonbs\w*|szembe\w*|drag\w*|olcsobb\w*|mennyivel)\b",
            re.I,
        ),
    ),
    (
        "validate",
        re.compile(
            r"\b(math|error\w*|valid\w*|check|verify|cdv|tax\s*id|consist\w*|correct|"
            r"matek\w*|hib\w*|validal\w*|ellenoriz\w*|adoszam\w*|ervenyes\w*|helyes)\b",
            re.I,
        ),
    ),
    (
        "search",
        re.compile(
            # 'which' removed — handled by the list pattern when followed by a doc-context noun
            r"\b(search|find|where|contain\w*|penalty|liquid\w*|clause\w*|"
            r"keres\w*|talald|hol|melyik|tartalmaz\w*|kotber\w*|change|klauz\w*)\b",
            re.I,
        ),
    ),
    (
        "list",
        re.compile(
            # 'what' / 'which' only count if followed by a document-context noun;
            # otherwise 'What is the gross total?' would be misrouted as list.
            r"\b("
            r"(?:what|which)\s+(?:documents?|files?|types?|kinds?|uploads?)|"
            r"how\s*many\s+(?:documents?|files?)|"
            r"list|listazd|listazz|"
            r"file\w*|document\w*|kind|"
            r"milyen|mely|hany|fajl\w*|dokumentum\w*|tipus\w*"
            r")\b",
            re.I,
        ),
    ),
    (
        "extract",
        re.compile(
            r"\b(gross|net|issu\w*|amount\w*|due|date\w*|quantity|total\w*|sum\w*|"
            r"price|cost|unit\s*price|payable|"
            r"brutto\w*|netto\w*|kiallit\w*|allit\w*|bocsat\w*|fizetesi|datum\w*|"
            r"menny\w*|osszeg\w*|vegosszeg\w*|ar\b|ara\b)\b",
            re.I,
        ),
    ),
]


def _classify_intent(text: str) -> str:
    """Simple regex router; returns 'chat' if nothing matches.

    Normalizes diacritics before matching (so "ellenőrizd" matches "ellenoriz").
    """
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text)
    text_norm = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    for intent, pattern in _INTENT_RULES:
        if pattern.search(text_norm):
            return intent
    return "chat"


def _extract_filenames(text: str, available: list[str]) -> list[str]:
    """Extract filenames mentioned in the user prompt.

    Two passes: (a) explicit extensions (.pdf, .docx, .png), (b) if none, fuzzy
    lookup against docs_hint by common stem tokens.
    """
    text_lower = text.lower()
    found: list[str] = []
    # (a) explicit filename-like patterns
    for m in re.finditer(r"([\w_\-]+\.(?:pdf|docx|png|jpg|jpeg|txt))", text_lower):
        candidate = m.group(1)
        # case-insensitive match against available list
        for av in available:
            if av.lower() == candidate:
                if av not in found:
                    found.append(av)
                break
    # (b) if no explicit match, search by stem tokens in available
    if not found:
        for av in available:
            stem = av.lower().rsplit(".", 1)[0]
            tokens = stem.replace("_", " ").replace("-", " ").split()
            if any(tok in text_lower for tok in tokens if len(tok) > 3):
                found.append(av)
    return found


# ---------------------------------------------------------------------------
# DummyChatModel
# ---------------------------------------------------------------------------


class DummyChatModel(BaseChatModel):
    """Deterministic chat-model — BaseChatModel implementation.

    Two modes:

    1. **Tool-binding mode** (chat agent loop): after ``bind_tools()``, the
       invoke decides which tool to call based on the user prompt and returns
       an AIMessage with ``tool_calls``. After several iterations (max ~3 tool
       calls per query), it finishes with a "Source-cited answer: ..." message.

    2. **Structured output mode** (extract / classify / risk node): after
       ``with_structured_output()``, the call returns a fixed Pydantic instance
       based on the schema name fixture.

    ``set_docs_hint(filenames)`` lets the UI inform the model of available
    files after upload — these are used to choose ``get_extraction(filename)``
    parameters.
    """

    # Pydantic fields (BaseChatModel is pydantic-based)
    # NOTE: backed by a module-level GLOBAL list because configurable_alternatives
    # instantiates one DummyChatModel for the "default" provider, and
    # ``get_dummy_handle()`` may return a different instance. The global
    # docs_hint ensures UI/eval setup is visible everywhere.
    docs_hint: list[str] = Field(default_factory=list)
    """Currently available document filenames — used for chat tool parameter
    selection. ``set_docs_hint()`` sets both the instance and the global list."""

    structured_fixtures: dict[str, Any] = Field(default_factory=dict)
    """Schema name → fixed Pydantic instance or dict (extract/classify dummy output)."""

    bound_tools: list[BaseTool] = Field(default_factory=list)
    """Toolset configured by ``bind_tools()``."""

    # Per-thread tool-call counter (loop guard)
    _call_counts: dict[str, dict[str, int]] = {}

    @property
    def _llm_type(self) -> str:
        return "dummy-chat"

    # ------------------------------------------------------------------
    # Public configuration
    # ------------------------------------------------------------------

    def set_docs_hint(self, filenames: list[str]) -> None:
        """Called from the UI: list of uploaded file names.

        Sets both globally and per-instance, so the configurable_alternatives
        singleton pattern doesn't cause state drift.
        """
        global _GLOBAL_DOCS_HINT
        names = list(filenames)
        self.docs_hint = names
        _GLOBAL_DOCS_HINT = names

    def set_structured_fixture(self, schema_name: str, value: Any) -> None:
        """Eval/test seam: schema_name → fixed output."""
        self.structured_fixtures[schema_name] = value

    # ------------------------------------------------------------------
    # bind_tools — LangChain tool binding
    # ------------------------------------------------------------------

    def bind_tools(
        self,
        tools: list[BaseTool],
        *,
        tool_choice: Any = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> "DummyChatModel":
        """Stores the toolset on the bound_tools field.

        Per LangChain convention, returns a new instance to keep immutability
        (so multiple graphs can use different toolsets).
        """
        new = self.model_copy(deep=False)
        new.bound_tools = list(tools)
        return new

    # ------------------------------------------------------------------
    # _generate — sync invoke
    # ------------------------------------------------------------------

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002
        run_manager: CallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ChatResult:
        ai_message = self._produce_response(messages)
        return ChatResult(generations=[ChatGeneration(message=ai_message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002
        run_manager: AsyncCallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ChatResult:
        return self._generate(messages, stop=stop, **kwargs)

    # ------------------------------------------------------------------
    # _stream — token-level streaming (UI streaming test)
    # ------------------------------------------------------------------

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002
        run_manager: CallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> Iterator[ChatGenerationChunk]:
        ai = self._produce_response(messages)
        # Split content into whitespace-separated tokens and stream chunk by chunk
        content = ai.content if isinstance(ai.content, str) else ""
        if content:
            for token in re.findall(r"\S+\s*", content):
                yield ChatGenerationChunk(message=AIMessageChunk(content=token))
        # Tool-call: emit the entire tool_calls payload in a single chunk
        # (LangChain expects this format for streaming tool-binding output)
        if ai.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=ai.tool_calls)
            )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002
        run_manager: AsyncCallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> AsyncIterator[ChatGenerationChunk]:
        for chunk in self._stream(messages, stop=stop, **kwargs):
            yield chunk

    # ------------------------------------------------------------------
    # Response logic
    # ------------------------------------------------------------------

    def _produce_response(self, messages: list[BaseMessage]) -> AIMessage:
        """Heart of the dummy logic: returns an AIMessage based on the message history."""

        # Structured output mode is wired up in Phase 3 (with_structured_output).
        # For now we focus on the tool-binding chat path.

        last_human = self._last_human_message(messages)
        last_human_content = last_human.content if last_human else ""
        if not isinstance(last_human_content, str):
            last_human_content = str(last_human_content)

        # If there are ToolMessages in the history, at least one tool call ran.
        # NOTE: list (not set) — for counter-based loop guard, duplicates matter
        # (e.g. compare-flow calls get_extraction twice).
        prior_tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        prior_tool_names: list[str] = [
            (tm.name or "") for tm in prior_tool_msgs if getattr(tm, "name", None)
        ]

        # If no tools are bound → text answer
        if not self.bound_tools:
            return AIMessage(content=self._compose_text_answer(last_human_content, prior_tool_msgs))

        # Tool-binding mode: which tool to call?
        intent = _classify_intent(last_human_content)
        tool_call = self._choose_tool_call(intent, last_human_content, prior_tool_names)

        if tool_call is None:
            # No more tools to call — synthesize a final answer from tool outputs
            return AIMessage(
                content=self._compose_text_answer(last_human_content, prior_tool_msgs)
            )

        # Single tool-call AIMessage
        return AIMessage(
            content="",
            tool_calls=[tool_call],
        )

    @staticmethod
    def _last_human_message(messages: list[BaseMessage]) -> HumanMessage | None:
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                return m
        return None

    def _choose_tool_call(
        self,
        intent: str,
        user_text: str,
        already_called: list[str],
    ) -> dict[str, Any] | None:
        """Pick the next tool call based on intent + user text.

        Loop guard: if we already called a tool once (or twice for get_extraction
        in compare flow), return None → the agent synthesizes.

        We only call tools that the graph builder confirmed are bound.
        """
        tool_names = {t.name for t in self.bound_tools}

        # Effective docs_hint: instance OR global (defends against singleton drift)
        docs_hint = self.docs_hint or _GLOBAL_DOCS_HINT

        # Max 1 call per tool, except get_extraction (max 2 — for compare flow)
        max_calls = {"get_extraction": 2}

        def can_call(name: str) -> bool:
            if name not in tool_names:
                return False
            count = sum(1 for n in already_called if n == name)
            return count < max_calls.get(name, 1)

        # Intent-based strategy
        if intent == "list" and can_call("list_documents"):
            return self._tool_call("list_documents", {})

        if intent == "search" and can_call("search_documents"):
            # Search needs a list-first if not yet listed
            if "list_documents" in tool_names and "list_documents" not in already_called:
                return self._tool_call("list_documents", {})
            return self._tool_call("search_documents", {"query": user_text[:120]})

        if intent == "validate" and can_call("validate_document"):
            files = _extract_filenames(user_text, docs_hint)
            target = files[0] if files else (docs_hint[0] if docs_hint else "")
            if target:
                return self._tool_call("validate_document", {"filename": target})

        if intent == "extract" and can_call("get_extraction"):
            # Extract needs a list-first
            if "list_documents" in tool_names and "list_documents" not in already_called:
                return self._tool_call("list_documents", {})
            files = _extract_filenames(user_text, docs_hint)
            target = files[0] if files else (docs_hint[0] if docs_hint else "")
            if target:
                return self._tool_call("get_extraction", {"filename": target})

        if intent == "compare":
            # Compare flow: list → get × 2 → compare
            if "list_documents" in tool_names and "list_documents" not in already_called:
                return self._tool_call("list_documents", {})
            files = _extract_filenames(user_text, docs_hint)
            if len(files) < 2 and len(docs_hint) >= 2:
                files = (files + [d for d in docs_hint if d not in files])[:2]
            extr_count = sum(1 for n in already_called if n == "get_extraction")
            if extr_count < min(2, len(files)) and can_call("get_extraction"):
                return self._tool_call("get_extraction", {"filename": files[extr_count]})
            if can_call("compare_documents") and len(files) >= 2:
                return self._tool_call(
                    "compare_documents",
                    {"filename_a": files[0], "filename_b": files[1]},
                )

        # chat intent or fallback: no tool call
        return None

    @staticmethod
    def _tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": name,
            "args": args,
            "id": f"dummy_tool_call_{uuid.uuid4().hex[:8]}",
            "type": "tool_call",
        }

    @staticmethod
    def _compose_text_answer(user_text: str, tool_msgs: list[ToolMessage]) -> str:
        """Synthesize a simple answer from tool results.

        Follows the AGENTIC_SYSTEM_PROMPT [Source: X] format used by the real LLM.
        """
        if not tool_msgs:
            return (
                "I could not find any tool result for your question in the uploaded "
                "documents. Try asking with more specifics."
            )

        parts: list[str] = ["Based on the tool results:"]
        for tm in tool_msgs:
            content = tm.content
            if isinstance(content, str):
                snippet = content[:300]
            else:
                snippet = json.dumps(content, ensure_ascii=False)[:300]
            tool_name = getattr(tm, "name", "tool")
            parts.append(f"- **{tool_name}**: {snippet}")

        # Source citation (the anti-halluc validator requires this)
        sources = []
        for tm in tool_msgs:
            content = str(tm.content)
            for m in re.finditer(r"([\w_\-]+\.(?:pdf|docx|png|jpg|jpeg|txt))", content):
                if m.group(1) not in sources:
                    sources.append(m.group(1))
        if sources:
            parts.append(f"\n[Source: {', '.join(sources)}]")

        # Echo-back hint to the user query (context in the response)
        parts.append(f"\n_(Dummy LLM response to: \"{user_text[:80]}\")_")

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def build_dummy_chat() -> DummyChatModel:
    """Used by ``providers/__init__.py`` in the configurable_alternatives setup."""
    return DummyChatModel()
