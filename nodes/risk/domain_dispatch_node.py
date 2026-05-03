"""domain_dispatch_node + apply_domain_check_node — 14 domain rules in parallel.

``domain_dispatch_node`` Send-fans-out the (doc, applicable_check) pairs.
``apply_domain_check_node`` runs a single check; the output flows through
the ``merge_risks`` reducer back into the global ``risks`` list.

Skipped checks (separate entry points):
  * check_06_evidence_score — called directly after classification
  * check_12_duplicate_invoice — package-level, separate node
"""

from __future__ import annotations

from langgraph.types import Send

from domain_checks import CHECK_REGISTRY, SKIP_FROM_DISPATCH, get_check
from graph.states.pipeline_state import PipelineState, ProcessedDocument


def domain_dispatch_node(state: PipelineState) -> list[Send]:
    """Fan-out: every (doc × applicable_check) gets its own Send.

    HU-specific vs universal split is governed by the ``is_hu_specific`` flag.
    Doc-type filter via ``applies_to``. For a 5-doc package, this typically
    issues ~30 parallel Sends (~50-100ms total batch).
    """
    sends: list[Send] = []
    documents: list[ProcessedDocument] = state.get("documents") or []
    for doc in documents:
        if doc.classification is None or doc.extracted is None:
            continue
        doc_type = doc.classification.doc_type
        is_hu = doc.classification.language.lower() in {"hu", "magyar", "hungarian"}

        for check in CHECK_REGISTRY:
            if check.check_id in SKIP_FROM_DISPATCH:
                continue
            if check.is_hu_specific and not is_hu:
                continue
            if "*" not in check.applies_to and doc_type not in check.applies_to:
                continue
            sends.append(Send("apply_domain_check", {
                "check_id": check.check_id,
                "extracted": doc.extracted.raw,
                "doc_file_name": doc.ingested.file_name,
                "doc_type": doc_type,
            }))
    return sends


async def apply_domain_check_node(state: dict) -> dict:
    """Run a single check (Send payload: check_id, extracted, doc_file_name)."""
    check_id = state.get("check_id")
    extracted = state.get("extracted") or {}
    doc_file_name = state.get("doc_file_name", "")
    if not check_id:
        return {}
    check = get_check(check_id)
    if check is None:
        return {}
    risks = check.apply(extracted)
    # The check usually fills affected_document, but we add a safety net:
    for r in risks:
        if r.affected_document is None:
            r.affected_document = doc_file_name
    return {"risks": risks} if risks else {}
