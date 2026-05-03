"""Streamlit + asyncio integration helper.

Bridges Streamlit (uvloop) and LangGraph (asyncio) via a long-lived background
event loop (see app/async_runtime.py).

``run_async()`` and ``stream_async()`` are simple wrappers — every call uses
the same background loop, so persistent resources (ChromaDB, AsyncSqliteSaver,
sentence-transformers cache) are NOT rebuilt per call.

``run_with_progress()`` produces per-event progress-bar updates from the
``astream(stream_mode="updates")`` event stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Callable

from app.async_runtime import AsyncRuntime


def run_async(coro):
    """Sync wrapper: run a coroutine on the long-lived background loop."""
    return AsyncRuntime.get().submit(coro)


def stream_async(async_gen: AsyncIterator[Any]):
    """Async generator → sync iterator (compatible with Streamlit st.write_stream)."""
    yield from AsyncRuntime.get().submit_iter(async_gen)


_PROGRESS_LABEL_MAP = {
    "start_timer": "Starting",
    "ingest_per_doc": "Loading documents",
    "ingest_join": "Loading documents (join)",
    "classify_per_doc": "Classifying",
    "classify_join": "Classifying (join)",
    "extract_per_doc": "Extracting structured data",
    "extract_join": "Extracting (join)",
    "quote_validator": "Quote verification",
    "rag_index_per_doc": "Indexing",
    "rag_join": "Indexing (join)",
    "compare": "Cross-document checks",
    "risk": "Risk analysis",
    "report": "Generating report",
    "finish_timer": "Done",
}


def run_with_progress(
    graph,
    input_state: dict,
    on_progress: Callable[[int, int, str], None] | None = None,
    total_steps: int | None = None,
) -> dict:
    """LangGraph ``astream`` → progress-bar callback + final state.

    The background event loop drives the async generator; the ``on_progress``
    callback runs on the CALLER thread (Streamlit main thread) after every
    event — so ``st.progress(...)`` widgets can be updated safely.

    Args:
        graph: a CompiledStateGraph (or anything supporting astream).
        input_state: the graph entry state.
        on_progress: optional callback ``(step, total, label)``. Streamlit
                     widget calls are safe here (caller thread).
        total_steps: optional progress-bar denominator.

    Returns:
        The graph's final state (same as ``ainvoke()``).
    """

    async def _astream_events():
        """Async generator: split multi-stream-mode into (stream_mode, event) pairs."""
        async for stream_mode, event in graph.astream(
            input_state, stream_mode=["updates", "values"]
        ):
            yield (stream_mode, event)

    final_state: dict = {}
    step = 0

    # ``submit_iter`` turns an async iterator into a sync one on the caller thread,
    # so the progress callback runs on the Streamlit main thread.
    for stream_mode, event in AsyncRuntime.get().submit_iter(_astream_events()):
        if stream_mode == "updates":
            for node_name in (event or {}).keys():
                step += 1
                label = _PROGRESS_LABEL_MAP.get(node_name, node_name)
                if on_progress is not None:
                    total = total_steps if total_steps is not None else max(step, 12)
                    on_progress(step, total, label)
        elif stream_mode == "values":
            if isinstance(event, dict):
                final_state = event

    return final_state
