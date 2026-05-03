"""risk_subgraph — aggregated risk analysis with Send API parallelism.

Topology:

  START
    → basic_risk_dispatch         (Send: per-doc basic risk)
    → basic_risk / noop_basic
    → domain_dispatch_node        (Send: per-doc × per-applicable-check, ~30 parallel)
    → apply_domain_check
    → [if llm provided] llm_risk_dispatch  (Send: per-doc LLM risk + 3-filter chain)
    → llm_risk_per_doc / noop_llm
    → plausibility_dispatch       (Send: per-doc plausibility)
    → plausibility / noop_plaus
    → evidence_score_node         (per-doc info)
    → duplicate_detector_node     (package-level, sync, ISA 240)
    END

If ``llm=None``, the LLM risk-analysis layer is skipped (Phase-4 backward
compatible). When ``llm`` is provided, the ``llm_risk_subgraph`` runs a 4-node
chain per-doc with Send fan-out: llm_risk → filter_llm_risks →
drop_business_normal → drop_repeats. The full anti-hallucination 5+1 layers.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from graph.states.pipeline_state import PipelineState, ProcessedDocument, Risk
from nodes.pipeline.duplicate_detector_node import duplicate_detector_node
from nodes.risk.basic_risk_node import basic_risk_node
from nodes.risk.domain_dispatch_node import (
    apply_domain_check_node,
    domain_dispatch_node,
)
from nodes.risk.evidence_score_node import evidence_score_node
from nodes.risk.plausibility_node import plausibility_node
from subgraphs.llm_risk_subgraph import build_llm_risk_subgraph


# ---------------------------------------------------------------------------
# Send dispatchers (basic + plausibility per-doc)
# ---------------------------------------------------------------------------


def basic_risk_dispatch(state: PipelineState) -> list[Send]:
    sends: list[Send] = []
    documents: list[ProcessedDocument] = state.get("documents") or []
    for doc in documents:
        if doc.classification is None or doc.extracted is None:
            continue
        sends.append(Send("basic_risk", {
            "doc_file_name": doc.ingested.file_name,
            "doc_type": doc.classification.doc_type,
            "extracted": doc.extracted.raw,
        }))
    return sends or [Send("noop_basic", {})]


def plausibility_dispatch(state: PipelineState) -> list[Send]:
    sends: list[Send] = []
    documents: list[ProcessedDocument] = state.get("documents") or []
    for doc in documents:
        if doc.classification is None or doc.extracted is None:
            continue
        sends.append(Send("plausibility", {
            "doc_file_name": doc.ingested.file_name,
            "extracted": doc.extracted.raw,
        }))
    return sends or [Send("noop_plaus", {})]


def llm_risk_dispatch(state: PipelineState) -> list[Send]:
    """Per-doc Send to the ``llm_risk_per_doc`` node.

    We pass the per-doc-filtered basic + domain + plausibility risks so the
    ``llm_risk_node`` can build the "ALREADY FOUND" block, and so
    ``drop_repeats_node`` doesn't drop genuinely new observations.

    Filtering is by ``Risk.affected_document`` field.
    """
    sends: list[Send] = []
    documents: list[ProcessedDocument] = state.get("documents") or []
    all_risks: list[Risk] = state.get("risks") or []

    for doc in documents:
        if doc.classification is None or doc.extracted is None:
            continue
        file_name = doc.ingested.file_name
        # Filter risks for this doc by affected_document.
        # We also include risks with affected_document=None (e.g. global
        # duplicate detection) since they don't disturb per-doc context.
        per_doc_basic = [
            r for r in all_risks
            if r.affected_document is None or r.affected_document == file_name
        ]
        sends.append(Send("llm_risk_per_doc", {
            "doc_file_name": file_name,
            "extracted": doc.extracted.raw,
            "basic_risks": per_doc_basic,
        }))
    return sends or [Send("noop_llm", {})]


async def _noop_basic(state: dict) -> dict:
    return {}


async def _noop_plaus(state: dict) -> dict:
    return {}


async def _noop_llm(state: dict) -> dict:
    return {}


# ---------------------------------------------------------------------------
# Subgraph builder
# ---------------------------------------------------------------------------


def build_risk_subgraph(llm=None):
    """Compile the risk subgraph (operates on the parent PipelineState).

    Args:
        llm: optional BaseChatModel-like Runnable. If None, the LLM
             risk-analysis layer (assess_risks_llm + 3 filters) is SKIPPED;
             only basic + domain + plausibility + evidence_score +
             duplicate_detector run (Phase-4 backward-compatible mode). If
             provided, the LLM layer runs after domain_dispatch.
    """
    graph = StateGraph(PipelineState)

    # Domain-dispatch + apply (Send fan-out for 12 of the 14 checks)
    graph.add_node("domain_dispatcher", _domain_dispatcher_passthrough)
    graph.add_node("apply_domain_check", apply_domain_check_node)

    # Basic risk (per-doc fan-out)
    graph.add_node("basic_risk_dispatcher", _basic_dispatcher_passthrough)
    graph.add_node("basic_risk", basic_risk_node)
    graph.add_node("noop_basic", _noop_basic)

    # Plausibility (per-doc fan-out)
    graph.add_node("plausibility_dispatcher", _plaus_dispatcher_passthrough)
    graph.add_node("plausibility", plausibility_node)
    graph.add_node("noop_plaus", _noop_plaus)

    # Per-doc info (evidence score)
    graph.add_node("evidence_score", evidence_score_node)

    # Package-level duplicate
    graph.add_node("duplicate_detector", duplicate_detector_node)

    # LLM risk subgraph (if llm provided) — Send fan-out per-doc chain
    has_llm = llm is not None
    if has_llm:
        llm_risk_subgraph = build_llm_risk_subgraph(llm)

        async def llm_risk_per_doc(state: dict) -> dict:
            """Run the LLM risk subgraph on the parent Send payload.

            At the end of the subgraph the 3-filter result is in ``risks``;
            it merges into the parent state's ``risks`` reducer.
            """
            result = await llm_risk_subgraph.ainvoke(state)
            risks = result.get("risks") or []
            return {"risks": risks} if risks else {}

        graph.add_node("llm_risk_dispatcher", _llm_risk_dispatcher_passthrough)
        graph.add_node("llm_risk_per_doc", llm_risk_per_doc)
        graph.add_node("noop_llm", _noop_llm)

    # Edges: dispatchers → conditional Sends → join nodes
    graph.add_edge(START, "basic_risk_dispatcher")
    graph.add_conditional_edges(
        "basic_risk_dispatcher",
        basic_risk_dispatch,
        ["basic_risk", "noop_basic"],
    )

    graph.add_edge("basic_risk", "domain_dispatcher")
    graph.add_edge("noop_basic", "domain_dispatcher")

    graph.add_conditional_edges(
        "domain_dispatcher",
        domain_dispatch_node,
        ["apply_domain_check"],
    )

    if has_llm:
        # apply_domain_check → llm_risk_dispatcher → llm_risk_per_doc → plausibility_dispatcher
        graph.add_edge("apply_domain_check", "llm_risk_dispatcher")
        graph.add_conditional_edges(
            "llm_risk_dispatcher",
            llm_risk_dispatch,
            ["llm_risk_per_doc", "noop_llm"],
        )
        graph.add_edge("llm_risk_per_doc", "plausibility_dispatcher")
        graph.add_edge("noop_llm", "plausibility_dispatcher")
    else:
        # apply_domain_check → plausibility_dispatcher (skip LLM)
        graph.add_edge("apply_domain_check", "plausibility_dispatcher")

    graph.add_conditional_edges(
        "plausibility_dispatcher",
        plausibility_dispatch,
        ["plausibility", "noop_plaus"],
    )
    graph.add_edge("plausibility", "evidence_score")
    graph.add_edge("noop_plaus", "evidence_score")

    graph.add_edge("evidence_score", "duplicate_detector")
    graph.add_edge("duplicate_detector", END)

    return graph.compile()


# Passthrough nodes (combined with Send dispatchers for fan-out)
async def _domain_dispatcher_passthrough(state: PipelineState) -> dict:
    return {}


async def _basic_dispatcher_passthrough(state: PipelineState) -> dict:
    return {}


async def _plaus_dispatcher_passthrough(state: PipelineState) -> dict:
    return {}


async def _llm_risk_dispatcher_passthrough(state: PipelineState) -> dict:
    return {}
