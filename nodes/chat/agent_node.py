"""agent_node — LLM bind_tools, the heart of the ReAct loop.

The node calls the LLM with the full message history + the system prompt.
If the LLM emits a tool_call, the downstream ``tools_condition`` routes to
the ToolNode; otherwise it routes to the synthesizer.

``build_agent_node(llm_with_tools)`` is a factory returning a closure with
the bound LLM. The graph receives the chat model at compile time.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from config import settings
from graph.states.chat_state import ChatState
from nodes.chat._prompts import AGENTIC_SYSTEM_PROMPT


# Friendly-error message prefixes — these are filtered out of the LLM history
# so they don't pollute follow-up reasoning. (Mirrors the parity behavior of
# the original system's ``_filter_history``.)
_ERROR_MESSAGE_PREFIXES: tuple[str, ...] = (
    "Missing",
    "Your API balance",
    "You exceeded",
    "The LLM service",
    "Network error",
    "Could not load PDF",
    "The file is too large",
    # Multilingual fallback (HU)
    "Hianyzo",
    "Az API szamladon",
    "Tullepted",
    "Az LLM szolgaltatas",
    "Halozati hiba",
    "Nem sikerult a PDF",
    "A fajl tul nagy",
)


def _filter_history(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Drop error-flavored AIMessages from the history.

    Friendly-error outputs (e.g. "Your API balance is insufficient") would
    confuse follow-up reasoning, so we exclude them when building the LLM input.
    """
    cleaned: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, AIMessage):
            content = m.content
            if isinstance(content, str) and any(
                content.startswith(prefix) for prefix in _ERROR_MESSAGE_PREFIXES
            ):
                continue
        cleaned.append(m)
    return cleaned


def build_agent_node(llm_with_tools, plan_to_prompt: bool = True):
    """Factory: capture llm_with_tools in a closure.

    Args:
        llm_with_tools: a ChatModel Runnable already bound with ``bind_tools(...)``
        plan_to_prompt: if True, append ``state["plan"]`` to the system prompt
    """

    async def agent_node(state: ChatState) -> dict:
        messages = state.get("messages") or []
        plan = state.get("plan") or []
        intent = state.get("intent", "chat")

        # Compose the system prompt
        system_text = AGENTIC_SYSTEM_PROMPT
        if plan_to_prompt and plan:
            system_text += (
                f"\n\n=== CURRENT PLAN (intent: {intent}) ==="
                f"\nSuggested tool order (hint, not mandatory): {' → '.join(plan)}"
            )

        # Iteration count
        iter_count = state.get("iteration_count", 0)
        if iter_count >= settings.chat_max_iterations:
            # Force-end: synthesize from the existing tool results
            return {
                "messages": [HumanMessage(
                    content="Please synthesize an answer from the tool results already collected; do NOT call any more tools."
                )],
                "iteration_count": iter_count + 1,
                "trace": [f"agent: max iter ({iter_count}) → forced synthesis"],
            }

        # LLM call — error-flavored history is stripped out
        cleaned_messages = _filter_history(messages)
        full_messages = [SystemMessage(content=system_text)] + cleaned_messages
        response = await llm_with_tools.ainvoke(full_messages)

        return {
            "messages": [response],
            "iteration_count": iter_count + 1,
            "trace": [f"agent: iter={iter_count + 1}, tool calls={len(getattr(response, 'tool_calls', []) or [])}"],
        }

    return agent_node
