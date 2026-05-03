"""contract_filter_node — keep only contracts from the documents list."""

from __future__ import annotations

from graph.states.dd_state import DDState
from graph.states.pipeline_state import ProcessedDocument


async def contract_filter_node(state: DDState) -> dict:
    documents: list[ProcessedDocument] = state.get("documents") or []
    contracts = [
        d for d in documents
        if d.classification and d.classification.doc_type == "contract"
    ]
    return {"documents": contracts}
