"""rag_query_subgraph -- a search_documents chat tool dedikált subgraph-ja.

Topológia:
  embed_query → hybrid_search → rerank → format → END

A LangSmith trace-ben ez a subgraph kibontva látszik (4 node), tisztán
elválasztva a chat agent-loop-tól. A `prototype-agentic` `rag/store.search_hybrid`
átfedéses mintát követjük.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from store import HybridStore


class RAGQueryState(TypedDict, total=False):
    query: str
    top_k: int
    raw_hits: list[dict]
    reranked_hits: list[dict]
    output: str


def _make_hybrid_search_node(store: HybridStore):
    async def hybrid_search_node(state: RAGQueryState) -> dict:
        query = state.get("query", "")
        top_k = state.get("top_k", 5)
        if not query:
            return {"raw_hits": []}
        hits = await store.search_hybrid(query, top_k=top_k)
        return {"raw_hits": hits}

    return hybrid_search_node


async def rerank_node(state: RAGQueryState) -> dict:
    """Egyszerű kulcsszó-overlap rerank a top-k-on belül.

    A RRF már egy fusion-rangsor, de a kulcsszó-boost az egzakt-match-eket előrébb
    hozhatja (pl. "HI-100" cikkszám pontosan szerepel-e a chunkban).
    """
    raw = state.get("raw_hits") or []
    if not raw:
        return {"reranked_hits": []}

    query = state.get("query", "").lower()
    query_tokens = set(query.split())

    def boost(hit: dict) -> float:
        text_lower = hit.get("text", "").lower()
        # Kulcsszó-overlap arány
        token_hits = sum(1 for t in query_tokens if t in text_lower)
        match_ratio = token_hits / max(1, len(query_tokens))
        return hit.get("score", 0.0) + 0.1 * match_ratio

    reranked = sorted(raw, key=boost, reverse=True)
    return {"reranked_hits": reranked}


async def format_node(state: RAGQueryState) -> dict:
    """Emberi olvasásra alkalmas output [Forrás: X] hivatkozásokkal."""
    hits = state.get("reranked_hits") or state.get("raw_hits") or []
    if not hits:
        return {"output": "Nem találtam releváns találatot a feltöltött dokumentumokban."}

    lines: list[str] = []
    for i, h in enumerate(hits, 1):
        meta = h.get("metadata") or {}
        source = meta.get("source", "ismeretlen")
        score = h.get("score", 0.0)
        text = h.get("text", "")
        # Max 200 karakter idézet a chunkból
        snippet = text[:200] + ("..." if len(text) > 200 else "")
        lines.append(
            f"[Forrás: {source}, relevancia: {score:.3f}]\n{snippet}"
        )

    return {"output": "\n\n---\n\n".join(lines)}


def build_rag_query_subgraph(store: HybridStore):
    """Compile-olt rag_query subgraph."""
    graph = StateGraph(RAGQueryState)
    graph.add_node("hybrid_search", _make_hybrid_search_node(store))
    graph.add_node("rerank", rerank_node)
    graph.add_node("format", format_node)
    graph.add_edge(START, "hybrid_search")
    graph.add_edge("hybrid_search", "rerank")
    graph.add_edge("rerank", "format")
    graph.add_edge("format", END)
    return graph.compile()
