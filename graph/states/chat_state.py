"""ChatState — global state of the chat_graph.

For ``messages`` we use the LangGraph built-in ``add_messages`` reducer:
every new BaseMessage is appended, never overwritten. This is the foundation
of the ReAct agent loop.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ChatState(TypedDict, total=False):
    """The chat_graph state. messages, trace, and intent are persisted."""

    messages: Annotated[list[BaseMessage], add_messages]
    """Full conversation history. add_messages reducer appends."""

    intent: str
    """One of 6 values: list | extract | search | compare | validate | chat.
    Set by the intent_classifier_node."""

    plan: list[str]
    """Output of the planner_node: tool-order hint for the system prompt."""

    iteration_count: int
    """Number of agent ↔ tools loop iterations. Capped at
    settings.chat_max_iterations (10) — beyond that we force-end."""

    validator_retry_count: int
    """Number of validator → agent retries. Capped at settings.validator_max_retries (2)."""

    final_answer: str
    """Output of the synthesizer_node. The chat's reply to the user."""

    sources_cited: list[str]
    """Source filenames detected by the validator_node (anti-hallucination check)."""

    trace: Annotated[list[str], add]
    """Step-by-step log for the UI sidebar. ``add`` reducer appends node calls."""
