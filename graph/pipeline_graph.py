"""Top-level pipeline graph — a teljes ingest → classify → extract → RAG → risk → report flow.

A pipeline egy hibrid: per-doc Send-fan-out a négy szakaszban (ingest, classify,
extract, rag-index), majd fan-in (`merge_doc_results` reducer), majd
csomag-szintű compare + risk + report.

Topológia:

  START
    → dispatch_ingest           (Send: per-doc)
    → ingest_per_doc            (subgraph hívás → ProcessedDocument shell)
    → dispatch_classify         (Send: per-doc)
    → classify_node             (Send-payload-ból futás)
    → dispatch_extract          (Send: per-doc)
    → extract_per_doc           (subgraph hívás)
    → dispatch_rag_index        (Send: per-doc)
    → rag_index_per_doc         (subgraph hívás, store closure)
    → quote_validator_node      (anti-halluc 7. réteg)
    → compare_node              (three-way matching, sync)
    → risk_subgraph             (basic + domain × Send + plausibility + duplicate)
    → report_node               (JSON struktúra)
    END
"""

from __future__ import annotations

import time
from datetime import datetime

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from graph.states.doc_state import DocState
from graph.states.pipeline_state import (
    Classification,
    ExtractedData,
    IngestedDocument,
    PipelineState,
    ProcessedDocument,
)
from nodes.extract.extract_node import build_extract_node
from nodes.extract.quote_validator_node import quote_validator_node
from nodes.pipeline.classify_node import build_classify_node
from nodes.pipeline.compare_node import compare_node
from nodes.pipeline.report_node import build_report_node
from store import HybridStore
from subgraphs.ingest_subgraph import build_ingest_subgraph
from subgraphs.rag_index_subgraph import build_rag_index_subgraph
from subgraphs.risk_subgraph import build_risk_subgraph


# ---------------------------------------------------------------------------
# Send dispatchers
# ---------------------------------------------------------------------------


def dispatch_ingest(state: PipelineState) -> list[Send]:
    """Fan-out: minden file egy DocState-tel az ingest_per_doc-ba."""
    files = state.get("files") or []
    if not files:
        return [Send("noop_ingest", {})]
    return [
        Send("ingest_per_doc", {
            "file_name": fn,
            "file_bytes": fb,
            "started_at": datetime.now(),
        })
        for fn, fb in files
    ]


def dispatch_classify(state: PipelineState) -> list[Send]:
    documents: list[ProcessedDocument] = state.get("documents") or []
    if not documents:
        return [Send("noop_classify", {})]
    return [
        Send("classify_per_doc", {"ingested": d.ingested})
        for d in documents
        if d.ingested is not None
    ]


def dispatch_extract(state: PipelineState) -> list[Send]:
    documents: list[ProcessedDocument] = state.get("documents") or []
    sends = []
    for d in documents:
        if d.classification is None or d.ingested is None:
            continue
        sends.append(Send("extract_per_doc", {
            "ingested": d.ingested,
            "classification": d.classification,
        }))
    return sends or [Send("noop_extract", {})]


def _make_dispatch_rag_index(store: HybridStore):
    def dispatch_rag_index(state: PipelineState) -> list[Send]:
        documents: list[ProcessedDocument] = state.get("documents") or []
        sends = []
        for d in documents:
            if d.ingested is None:
                continue
            doc_type = d.classification.doc_type if d.classification else "egyeb"
            sends.append(Send("rag_index_per_doc", {
                "ingested": d.ingested,
                "doc_type": doc_type,
            }))
        return sends or [Send("noop_rag", {})]
    return dispatch_rag_index


# ---------------------------------------------------------------------------
# Per-doc subgraph wrapper-ek (a parent state-be visszadnak)
# ---------------------------------------------------------------------------


def _make_ingest_per_doc():
    ingest_subgraph = build_ingest_subgraph()

    async def ingest_per_doc(state: DocState) -> dict:
        result = await ingest_subgraph.ainvoke(state)
        ingested = result.get("ingested")
        if ingested is None:
            return {}
        # ProcessedDocument shell — a documents reducer file_name-en upsert
        pd = ProcessedDocument(ingested=ingested)
        return {"documents": [pd]}

    return ingest_per_doc


def _make_classify_per_doc(llm=None):
    classify_node = build_classify_node(llm=llm)

    async def classify_per_doc(state: dict) -> dict:
        return await classify_node(state)

    return classify_per_doc


def _make_extract_per_doc(llm=None):
    extract_node = build_extract_node(llm=llm)

    async def extract_per_doc(state: dict) -> dict:
        return await extract_node(state)

    return extract_per_doc


def _make_rag_index_per_doc(store: HybridStore):
    rag_subgraph = build_rag_index_subgraph(store)

    async def rag_index_per_doc(state: dict) -> dict:
        result = await rag_subgraph.ainvoke({
            "ingested": state["ingested"],
            "doc_type": state.get("doc_type", "egyeb"),
        })
        chunks_indexed = result.get("chunks_indexed", 0)
        # A documents listához egy frissítést adunk a chunks_indexed mezővel
        # → merge_doc_results reducer file_name-en upsert-eli
        ing = state["ingested"]
        pd = ProcessedDocument(ingested=ing, rag_chunks_indexed=chunks_indexed)
        return {"documents": [pd]} if ing else {}

    return rag_index_per_doc


async def _noop(state: dict) -> dict:
    return {}


# ---------------------------------------------------------------------------
# Wall-clock timer (start + finish)
# ---------------------------------------------------------------------------


async def start_timer_node(state: PipelineState) -> dict:
    return {
        "started_at": datetime.now(),
        "_internal_start": time.time(),
    }


async def finish_timer_node(state: PipelineState) -> dict:
    started = state.get("started_at")
    elapsed = 0.0
    if started is not None:
        elapsed = (datetime.now() - started).total_seconds()
    return {
        "finished_at": datetime.now(),
        "processing_seconds": round(elapsed, 3),
    }


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------


def build_pipeline_graph(store: HybridStore, *, llm=None, checkpointer=None):
    """Compile-olt pipeline_graph.

    Args:
        store: a HybridStore singleton (a per-doc rag_index_per_doc-ba bezárva)
        llm: opcionális BaseChatModel-szerű Runnable. Ha adott, az LLM kockázat-
             elemző réteg (assess_risks_llm + 3 szűrő) bekapcsolódik a
             risk_subgraph-ba — a `prototype-agentic`-vel paritásos viselkedés
             érdekében ezt MINDIG meg kell adni a UI-on (lásd app/main.py).
        checkpointer: opcionális (SqliteSaver / InMemorySaver). None → no checkpoint.
    """
    risk_subgraph = build_risk_subgraph(llm=llm)

    graph = StateGraph(PipelineState)

    # Belépés / timer
    graph.add_node("start_timer", start_timer_node)

    # Per-doc ingest fan-out
    graph.add_node("ingest_per_doc", _make_ingest_per_doc())
    graph.add_node("noop_ingest", _noop)

    # Per-doc classify fan-out
    graph.add_node("classify_per_doc", _make_classify_per_doc(llm=llm))
    graph.add_node("noop_classify", _noop)

    # Per-doc extract fan-out
    graph.add_node("extract_per_doc", _make_extract_per_doc(llm=llm))
    graph.add_node("noop_extract", _noop)

    # Per-doc rag index fan-out
    graph.add_node("rag_index_per_doc", _make_rag_index_per_doc(store))
    graph.add_node("noop_rag", _noop)

    # Quote validator (post-extract anti-halluc)
    graph.add_node("quote_validator", quote_validator_node)

    # Three-way compare
    graph.add_node("compare", compare_node)

    # Risk subgraph
    graph.add_node("risk", risk_subgraph)

    # Report (LLM exec summary-vel ha llm adott)
    graph.add_node("report", build_report_node(llm=llm))
    graph.add_node("finish_timer", finish_timer_node)

    # ----- Edges -----
    graph.add_edge(START, "start_timer")
    graph.add_conditional_edges(
        "start_timer",
        dispatch_ingest,
        ["ingest_per_doc", "noop_ingest"],
    )
    # Ingest fan-in → classify dispatch
    graph.add_node("ingest_join", _noop)
    graph.add_edge("ingest_per_doc", "ingest_join")
    graph.add_edge("noop_ingest", "ingest_join")

    graph.add_conditional_edges(
        "ingest_join",
        dispatch_classify,
        ["classify_per_doc", "noop_classify"],
    )

    # Classify fan-in → extract dispatch
    graph.add_node("classify_join", _noop)
    graph.add_edge("classify_per_doc", "classify_join")
    graph.add_edge("noop_classify", "classify_join")
    graph.add_conditional_edges(
        "classify_join",
        dispatch_extract,
        ["extract_per_doc", "noop_extract"],
    )

    # Extract fan-in → quote_validator → rag_index dispatch
    graph.add_node("extract_join", _noop)
    graph.add_edge("extract_per_doc", "extract_join")
    graph.add_edge("noop_extract", "extract_join")
    graph.add_edge("extract_join", "quote_validator")

    graph.add_conditional_edges(
        "quote_validator",
        _make_dispatch_rag_index(store),
        ["rag_index_per_doc", "noop_rag"],
    )

    # Rag fan-in → compare → risk → report → finish
    graph.add_node("rag_join", _noop)
    graph.add_edge("rag_index_per_doc", "rag_join")
    graph.add_edge("noop_rag", "rag_join")
    graph.add_edge("rag_join", "compare")
    graph.add_edge("compare", "risk")
    # FONTOS: a finish_timer a report ELŐTT fut, hogy a processing_seconds
    # rendelkezésre álljon a teljesítmény-metrikákhoz
    graph.add_edge("risk", "finish_timer")
    graph.add_edge("finish_timer", "report")
    graph.add_edge("report", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
