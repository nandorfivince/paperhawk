"""chat_graph -- 5 chat tool + ReAct + validator.

Topológia:

  START
    → intent_classifier_node    (regex, gyors -- 6 intent)
    → planner_node              (intent → tool-sorrend hint a system prompt-ba)
    → agent_node                (LLM bind_tools, ReAct)
    → tools_condition (cond)
       ├→ tool_node (ToolNode)  (5 tool végrehajtás)
       │    → agent_node (loop)
       ↓ ha nincs több tool_call
    → synthesizer_node          (utolsó AIMessage.content → final_answer)
    → validator_node            (forrás-cite + min 20 char)
    → should_retry (cond)
       ├→ agent_node (max 2 retry)
       ↓ ok
    → END
"""

from __future__ import annotations

from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from config import settings
from graph.states.chat_state import ChatState
from nodes.chat.agent_node import build_agent_node
from nodes.chat.intent_classifier_node import intent_classifier_node
from nodes.chat.planner_node import planner_node
from nodes.chat.synthesizer_node import synthesizer_node
from nodes.chat.validator_node import validator_node
from tools import ChatToolContext, build_tools


def _should_retry(state: ChatState) -> str:
    """Validator → agent (retry) vagy END.

    A validator_node a `messages` listához egy HumanMessage-t fűz, ha nem
    elfogadható a válasz. Ezt detektáljuk: az utolsó message HumanMessage-e?
    """
    messages = state.get("messages") or []
    if not messages:
        return "end"
    last = messages[-1]
    # Ha az utolsó user-instrukció a validator-ből jött (retry kérés)
    if hasattr(last, "type") and last.type == "human":
        # A validator által beszúrt HumanMessage-eket azonosítjuk a content-szubstring-en
        content = str(getattr(last, "content", ""))
        if "A válasz nem elfogadható" in content:
            retry = state.get("validator_retry_count", 0)
            if retry <= settings.validator_max_retries:
                return "retry"
    return "end"


def build_chat_graph(llm: Runnable, context: ChatToolContext, *, checkpointer=None):
    """Compile-olt chat_graph.

    Args:
        llm: a chat-modell (Runnable, configurable_alternatives is OK)
        context: a ChatToolContext (HybridStore + documents map)
        checkpointer: opcionális (SqliteSaver / InMemorySaver)
    """
    tools_list = build_tools(context)
    llm_with_tools = llm.bind_tools(tools_list)

    graph = StateGraph(ChatState)

    graph.add_node("intent", intent_classifier_node)
    graph.add_node("planner", planner_node)
    graph.add_node("agent", build_agent_node(llm_with_tools))
    graph.add_node("tools", ToolNode(tools_list))
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("validator", validator_node)

    graph.add_edge(START, "intent")
    graph.add_edge("intent", "planner")
    graph.add_edge("planner", "agent")

    # tools_condition: agent → tools VAGY synthesizer
    graph.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", "__end__": "synthesizer"},
    )
    # tool végrehajtás után vissza agent-hez (ReAct loop)
    graph.add_edge("tools", "agent")

    # synthesizer → validator → END vagy retry
    graph.add_edge("synthesizer", "validator")
    graph.add_conditional_edges(
        "validator",
        _should_retry,
        {"retry": "agent", "end": END},
    )

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
