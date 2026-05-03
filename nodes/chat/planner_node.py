"""planner_node — intent → tool-order hint for the system prompt.

Hard-coded rules. The plan is appended to the agent's SYSTEM prompt; the
LLM (or dummy) uses it as a hint.
"""

from __future__ import annotations

from graph.states.chat_state import ChatState


_PLAN_BY_INTENT: dict[str, list[str]] = {
    "list": ["list_documents"],
    "extract": ["list_documents", "get_extraction"],
    "search": ["list_documents", "search_documents"],
    "compare": ["list_documents", "get_extraction", "get_extraction", "compare_documents"],
    "validate": ["validate_document"],
    "chat": [],
}


async def planner_node(state: ChatState) -> dict:
    intent = state.get("intent", "chat")
    plan = _PLAN_BY_INTENT.get(intent, [])
    return {
        "plan": plan,
        "trace": [f"planner: {' → '.join(plan) if plan else '(no plan, direct LLM)'}"],
    }
