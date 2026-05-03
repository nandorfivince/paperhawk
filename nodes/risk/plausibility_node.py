"""plausibility_node — flag unusual values as warnings."""

from __future__ import annotations

from graph.states.pipeline_state import Risk
from nodes.risk.basic_risk_node import _normalize_severity
from validation.plausibility import validate_plausibility


async def plausibility_node(state: dict) -> dict:
    extracted = state.get("extracted") or {}
    file_name = state.get("doc_file_name", "")
    if not extracted:
        return {}

    warnings = validate_plausibility(extracted)
    risks = [
        Risk(
            description=w.get("message", ""),
            severity=_normalize_severity(w.get("severity", "low")),
            rationale="Plausibility check — unusual value, verify against the source.",
            kind="plausibility",
            affected_document=file_name,
            source_check_id=f"plausibility_{w.get('type', 'unknown')}",
        )
        for w in warnings
    ]
    return {"risks": risks} if risks else {}
