"""SqliteSaver checkpointer factory + thread_id helpers.

A 4 graph (pipeline, chat, dd, package_insights) UGYANAZT a SqliteSaver-t használja,
közös `thread_id` tér. Ez lehetővé teszi, hogy a chat tool-ok a perzisztált
pipeline state-ből olvassanak.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from config import settings


def make_thread_id(session_id: str | None = None) -> str:
    """Egy stabil thread_id-t generál a Streamlit session-höz."""
    if session_id:
        return session_id
    return f"session_{uuid.uuid4().hex[:16]}"


@asynccontextmanager
async def open_async_checkpointer(db_path: Path | str | None = None):
    """AsyncSqliteSaver context manager — pipeline_graph.compile()-hoz.

    Használat:
        async with open_async_checkpointer() as checkpointer:
            graph = build_pipeline_graph(checkpointer=checkpointer)
            await graph.ainvoke(state, config=...)
    """
    path = Path(db_path or settings.checkpoint_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        yield checkpointer


def in_memory_checkpointer() -> InMemorySaver:
    """In-memory fallback CI/eval-hez (nincs persistencia)."""
    return InMemorySaver()
