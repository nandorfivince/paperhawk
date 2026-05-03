"""AsyncRuntime — long-lived background event loop for the Streamlit thread.

PROBLEM:
  * Streamlit runs a synchronous event loop (uvloop) that CANNOT be patched
    with ``nest_asyncio``.
  * LangGraph (and every async resource: ChromaDB connections, the LLM HTTP
    session, AsyncSqliteSaver checkpointers) assumes a LONG-LIVED async context.
  * Opening a new loop per invoke means async-bound resources never amortize:
    every chat message rebuilds the SQLite pool, the Chroma client, and the
    HTTP session.

SOLUTION:
  * A DEDICATED background thread that runs a single ``asyncio.new_event_loop()``
    with ``run_forever`` for the entire app lifetime.
  * The Streamlit thread (sync) hands coroutines to the background loop via
    ``asyncio.run_coroutine_threadsafe(coro, loop)``; the returned Future
    blocks the Streamlit thread until the result is ready.
  * Singleton — started once, same instance reused.

This is the classic "embedded async runtime" pattern (see LangChain,
JupyterLab, ipykernel implementations). Robust and scales well.
"""

from __future__ import annotations

import asyncio
import atexit
import threading
from collections.abc import AsyncIterator
from typing import Any, TypeVar

T = TypeVar("T")


class AsyncRuntime:
    """Singleton background event loop. Thread-safe submit + stream API."""

    _instance: AsyncRuntime | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        # Lazy start: the loop and thread start on the first submit()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    @classmethod
    def get(cls) -> AsyncRuntime:
        """Singleton accessor — created on first call, same instance after."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = AsyncRuntime()
        return cls._instance

    def _ensure_started(self) -> None:
        """Start the background loop if not already running."""
        if self._started.is_set():
            return
        with self._lock:
            if self._started.is_set():
                return

            ready = threading.Event()

            def _run() -> None:
                # Inside the thread, create the loop and run it
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                ready.set()
                try:
                    self._loop.run_forever()
                finally:
                    self._loop.close()

            self._thread = threading.Thread(
                target=_run,
                name="async-runtime",
                daemon=True,  # auto-stops when the app exits
            )
            self._thread.start()
            ready.wait(timeout=5.0)  # wait until the loop is actually running
            self._started.set()

            # Cleanup at app shutdown
            atexit.register(self._shutdown)

    def submit(self, coro) -> Any:
        """Submit a coroutine to the background loop, block on the result.

        This is the Streamlit thread's main API: synchronous-looking, but the
        coroutine runs on a long-lived loop so async resources (Chroma,
        SqliteSaver, embeddings) stay PERSISTENT across calls.
        """
        self._ensure_started()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def submit_iter(self, async_gen: AsyncIterator[T]):
        """Async generator → sync iterator wrapper for Streamlit st.write_stream.

        The Streamlit thread iterates over the (token-)stream from the astream call.
        """
        self._ensure_started()
        assert self._loop is not None

        # We drive the async generator on the background loop by submitting
        # ``__anext__()`` calls one at a time.
        while True:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    async_gen.__anext__(), self._loop
                )
                yield future.result()
            except StopAsyncIteration:
                break

    def _shutdown(self) -> None:
        """atexit handler — gracefully stop the background loop."""
        if self._loop is None or not self._started.is_set():
            return
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass
