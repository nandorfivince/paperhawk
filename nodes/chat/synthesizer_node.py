"""synthesizer_node — at the end of the tool loop, take the last AIMessage.content as final_answer."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from graph.states.chat_state import ChatState


async def synthesizer_node(state: ChatState) -> dict:
    """Take the last AIMessage.content from messages as final_answer."""
    messages = state.get("messages") or []
    last_ai_content = ""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            content = m.content
            if isinstance(content, str) and content.strip():
                last_ai_content = content
                break
            elif isinstance(content, list):
                # Anthropic-style content blocks
                text_parts = [
                    part.get("text", "") for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                if any(text_parts):
                    last_ai_content = "\n".join(t for t in text_parts if t)
                    break

    return {
        "final_answer": last_ai_content or "(empty answer)",
        "trace": [f"synthesizer: {len(last_ai_content)} characters"],
    }
