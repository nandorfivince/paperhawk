"""evidence_score_node — ISA 500 evidence score per-doc.

Separate entry point (NOT Send-fan-out via the domain checks) because the
score depends on doc_type and produces a per-document info-level risk.
"""

from __future__ import annotations

from domain_checks import EvidenceScoreCheck
from graph.states.pipeline_state import PipelineState, ProcessedDocument


async def evidence_score_node(state: PipelineState) -> dict:
    documents: list[ProcessedDocument] = state.get("documents") or []
    check = EvidenceScoreCheck()
    risks: list = []

    for doc in documents:
        if doc.classification is None:
            continue
        doc_risks = check.apply(
            extracted=doc.extracted.raw if doc.extracted else {},
            doc_type=doc.classification.doc_type,
        )
        for r in doc_risks:
            r.affected_document = doc.ingested.file_name
        risks.extend(doc_risks)

    return {"risks": risks} if risks else {}
