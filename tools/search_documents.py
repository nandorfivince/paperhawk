"""search_documents tool -- a rag_query_subgraph-ot hívja.

A chat search-intent-jénél az LLM ezt a tool-t választja. A tool egy belső
LangGraph subgraph-ot futtat, ami a hibrid keresést végzi (vektor + BM25 + RRF
+ rerank + format).

A LangSmith trace-ben a subgraph kibontva látszik a tool-call alatt -- szakmai
mélység jelzés a pitch demón.
"""

from __future__ import annotations

from langchain_core.tools import tool

from subgraphs.rag_query_subgraph import build_rag_query_subgraph
from tools.context import ChatToolContext


def build_search_documents_tool(ctx: ChatToolContext):
    # A subgraph-ot egyszer compile-oljuk a build-időben (closure-ben tartjuk)
    rag_subgraph = build_rag_query_subgraph(ctx.store)

    @tool
    def search_documents(query: str) -> str:
        """Szemantikus + kulcsszavas hibrid keresés a feltöltött dokumentumokban.

        Használd ha konkrét információt keresel a dokumentum-szövegekben:
        klauzulák, dátumok, határidők, tételek megnevezései.

        Args:
            query: keresési kifejezés magyarul (pl. 'szállítási határidő')
        """
        # Sync wrapper az async subgraph köré.
        #
        # Egységes minta a teljes alkalmazásban: az AsyncRuntime singleton
        # (long-lived background event loop) futtat minden async coroutine-t.
        # Ez biztosítja:
        #   * Stabil uvloop-mentes futás Streamlit alatt (nincs nest_asyncio)
        #   * Resource-megosztás: ChromaDB pool, sentence-transformers cache,
        #     AsyncSqliteSaver kapcsolat NEM épül újra hívásonként
        #   * Skálázódás: 100+ párhuzamos chat-kérés ugyanazt a loopot használja
        from app.async_runtime import AsyncRuntime

        result = AsyncRuntime.get().submit(
            rag_subgraph.ainvoke({"query": query, "top_k": 5})
        )
        return result.get("output", "Nem találtam releváns találatot.")

    return search_documents
