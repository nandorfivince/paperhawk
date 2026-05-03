"""duplicate_detector_node — package-level ISA 240 duplicate detection.

Operates over all documents at once (NOT a Send fan-out) — O(n²) cross-pairing
with up to ~25 docs is well within budget; the Send overhead would dominate.
"""

from __future__ import annotations

from domain_checks import check_duplicate_invoices
from graph.states.pipeline_state import PipelineState, ProcessedDocument


async def duplicate_detector_node(state: PipelineState) -> dict:
    documents: list[ProcessedDocument] = state.get("documents") or []
    if len(documents) < 2:
        return {}

    docs_for_check = [
        {
            "file_name": d.ingested.file_name,
            "doc_type": d.classification.doc_type if d.classification else "other",
            "extracted": d.extracted.raw if d.extracted else {},
        }
        for d in documents
        if d.ingested is not None
    ]

    risks = check_duplicate_invoices(docs_for_check)
    return {"risks": risks} if risks else {}
