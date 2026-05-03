"""llm_risk_subgraph — per-doc LLM kockázat-elemző chain.

Topológia:

  START
    → llm_risk_node            (assess_risks_llm — LLM kontextuális elemzés)
    → filter_llm_risks_node    (formai szűrő: ≥5 szó, ≥2 szakkifejezés, ≥1 konkrét adat)
    → drop_business_normal_node (szemantikai cross-check az extracted-tal)
    → drop_repeats_node        (70% szó-overlap dedup a basic risks ellen)
    END → "risks" key a parent state-be (merge_risks reducer)

A subgraph-ot a `risk_subgraph.py` Send-fan-out-olja per-doc:
    Send("llm_risk_per_doc", {"doc_file_name", "extracted", "basic_risks"})

A kimenet a `risks` kulcsba kerül, a `merge_risks` reducer (merge_risks_with_dedup)
dedup-pal egyesít a parent `PipelineState.risks`-be.

A node-ok IDEIGLENES kulcsa a `llm_risks_raw` — ez a chain végén `risks`-szé
alakul a `drop_repeats_node`-ban.

A `prototype-agentic/pipeline/risk.py:166-220` `assess_risks_llm` 4-soros
sorozat-chain-jét reprodukálja LangGraph-ban, Send API-val skálázva.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from graph.states.pipeline_state import Risk, merge_risks
from nodes.risk.drop_business_normal_node import drop_business_normal_node
from nodes.risk.drop_repeats_node import drop_repeats_node
from nodes.risk.filter_llm_risks_node import filter_llm_risks_node
from nodes.risk.llm_risk_node import build_llm_risk_node


class _LLMRiskState(TypedDict, total=False):
    """A per-doc LLM risk subgraph state-je.

    A subgraph-ot Send-en keresztül hívják, payload: doc_file_name + extracted +
    basic_risks. A `llm_risks_raw` egy ideiglenes lista a node-ok között.
    """
    doc_file_name: str
    extracted: dict
    basic_risks: list[Risk]
    llm_risks_raw: list[Risk]
    risks: Annotated[list[Risk], merge_risks]


def build_llm_risk_subgraph(llm):
    """Compile-olt per-doc LLM risk subgraph.

    Args:
        llm: BaseChatModel-szerű Runnable a `with_structured_output()` API-val.

    Returns:
        Compile-olt LangGraph CompiledStateGraph.
    """
    graph = StateGraph(_LLMRiskState)

    graph.add_node("llm_risk", build_llm_risk_node(llm))
    graph.add_node("filter_formal", filter_llm_risks_node)
    graph.add_node("drop_business_normal", drop_business_normal_node)
    graph.add_node("drop_repeats", drop_repeats_node)

    graph.add_edge(START, "llm_risk")
    graph.add_edge("llm_risk", "filter_formal")
    graph.add_edge("filter_formal", "drop_business_normal")
    graph.add_edge("drop_business_normal", "drop_repeats")
    graph.add_edge("drop_repeats", END)

    return graph.compile()
