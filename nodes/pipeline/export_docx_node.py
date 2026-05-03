"""export_docx_node — lazy DOCX export.

NOT part of the pipeline_graph; the Streamlit Report tab button calls
``build_docx_sync`` directly via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio

from graph.states.pipeline_state import PipelineState
from utils.docx_export import build_docx_sync


async def export_docx_node(state: PipelineState) -> dict:
    """Async-friendly wrapper around the blocking python-docx call."""
    docx_bytes = await asyncio.to_thread(build_docx_sync, state)
    return {"docx_bytes": docx_bytes}
