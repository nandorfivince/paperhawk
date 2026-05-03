"""dd_graph -- multi-agent supervisor pattern a DD asszisztenshez.

Topológia:

  START
    → contract_filter_node          (state["documents"] → szerződések)
    → per_contract_summary_node     (Python-deterministic per-szerz)
    → supervisor_node               (Command(goto=specialist)-tal routing)
       ├→ audit_specialist
       ├→ legal_specialist
       ├→ compliance_specialist
       └→ financial_specialist
       → supervisor_node (loop, max 4 iter)
       → dd_synthesizer              (DDPortfolioReport)
       → END

A LangGraph 0.6+ `Command` mintát követjük a routing-hoz. A supervisor
max 4 iterációt csinál, utána force-en a synthesizer-be lép.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.states.dd_state import DDState
from nodes.dd.contract_filter_node import contract_filter_node
from nodes.dd.dd_synthesizer import build_dd_synthesizer
from nodes.dd.per_contract_summary_node import per_contract_summary_node
from nodes.dd.specialists import (
    audit_specialist,
    compliance_specialist,
    financial_specialist,
    legal_specialist,
)
from nodes.dd.supervisor_node import supervisor_node


def build_dd_graph(*, llm=None, checkpointer=None):
    """Compile-olt DD graph multi-agent supervisor mintával.

    Args:
        llm: opcionális BaseChatModel-szerű Runnable. Ha adott, a `dd_synthesizer`
             1 LLM hívással generál exec summary + top_red_flags + per-szerz
             risk-rating-eket (paritás a `prototype-agentic/pipeline/dd_assistant.py`-vel).
        checkpointer: opcionális checkpointer.
    """
    graph = StateGraph(DDState)

    graph.add_node("contract_filter", contract_filter_node)
    graph.add_node("per_contract_summary", per_contract_summary_node)
    graph.add_node("supervisor", supervisor_node)

    graph.add_node("audit_specialist", audit_specialist)
    graph.add_node("legal_specialist", legal_specialist)
    graph.add_node("compliance_specialist", compliance_specialist)
    graph.add_node("financial_specialist", financial_specialist)

    graph.add_node("dd_synthesizer", build_dd_synthesizer(llm=llm))

    graph.add_edge(START, "contract_filter")
    graph.add_edge("contract_filter", "per_contract_summary")
    graph.add_edge("per_contract_summary", "supervisor")

    # A supervisor `Command(goto=X)` mintán át routing-ol — ezért nincs explicit
    # add_conditional_edges, hanem az add_node a Command-támogatott node-ot építi.
    # A specialista-ok visszamennek a supervisor-hoz.
    graph.add_edge("audit_specialist", "supervisor")
    graph.add_edge("legal_specialist", "supervisor")
    graph.add_edge("compliance_specialist", "supervisor")
    graph.add_edge("financial_specialist", "supervisor")

    graph.add_edge("dd_synthesizer", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
