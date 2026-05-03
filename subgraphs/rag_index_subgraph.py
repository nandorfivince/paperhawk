"""rag_index_subgraph — egy doksi chunkokra darabolása + ChromaDB+BM25 indexelés.

A pipeline_graph `dispatch_rag_index` Send API-val fan-out-ol minden doksira.
Ez a subgraph minden doksira lefuttat:
  1. chunker_node:    full_text → chunkok természetes vágási ponttal
  2. embed_upsert_node: a chunkokat batch-ben embeddoljuk és HybridStore-ba tesszük

A HybridStore singleton (a pipeline_graph compile-időben kapja meg).
A subgraph a `state["store"]` kulcson keresztül éri el — closure pattern.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from graph.states.pipeline_state import IngestedDocument
from store import HybridStore, chunk_document


class RAGIndexState(TypedDict, total=False):
    """A rag_index subgraph belső state-je (nem a parent PipelineState)."""

    file_name: str
    ingested: IngestedDocument
    doc_type: str
    chunks: list[dict]
    chunks_indexed: int

    # Closure: a HybridStore instance — a build_rag_index_subgraph() build-időben kapja meg
    # és bezárja a node-okba.


def _make_chunker_node():
    async def chunker_node(state: RAGIndexState) -> dict:
        ing = state.get("ingested")
        if ing is None or not ing.full_text:
            return {"chunks": []}
        chunks = chunk_document(
            file_name=ing.file_name,
            full_text=ing.full_text,
            doc_type=state.get("doc_type", "egyeb"),
        )
        return {"chunks": chunks}

    return chunker_node


def _make_embed_upsert_node(store: HybridStore):
    """Closure-ban kapja meg a HybridStore-t a parent graph-ról."""

    async def embed_upsert_node(state: RAGIndexState) -> dict:
        chunks = state.get("chunks") or []
        if not chunks:
            return {"chunks_indexed": 0}
        n = await store.add_chunks(chunks)
        return {"chunks_indexed": n}

    return embed_upsert_node


def build_rag_index_subgraph(store: HybridStore):
    """Compile-olt subgraph egy doksi RAG-indexelésre.

    Args:
        store: a HybridStore singleton — a node-okba bezárva a closure-ön.
    """
    graph = StateGraph(RAGIndexState)
    graph.add_node("chunker", _make_chunker_node())
    graph.add_node("embed_upsert", _make_embed_upsert_node(store))
    graph.add_edge(START, "chunker")
    graph.add_edge("chunker", "embed_upsert")
    graph.add_edge("embed_upsert", END)
    return graph.compile()
