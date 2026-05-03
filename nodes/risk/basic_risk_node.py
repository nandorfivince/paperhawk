"""basic_risk_node — Python-deterministic math + date logic.

Per-doc fan-out: invoked via Send API on a per-document branch.
Input: ``{"doc_index": int, "extracted": dict, "doc_file_name": str, "doc_type": str}``
Output: ``{"risks": [Risk(...)]}`` — merged via the ``merge_risks`` reducer.
"""

from __future__ import annotations

from graph.states.pipeline_state import Risk
from validation.date_logic import validate_contract_dates, validate_date_logic
from validation.invoice_math import validate_invoice_math


async def basic_risk_node(state: dict) -> dict:
    extracted = state.get("extracted") or {}
    doc_type = state.get("doc_type", "other")
    file_name = state.get("doc_file_name", "")

    if not extracted:
        return {}

    # Invoice math + date logic
    errors = validate_invoice_math(extracted)
    errors.extend(validate_date_logic(extracted))

    # Contract date logic
    if doc_type == "contract":
        errors.extend(validate_contract_dates(extracted))

    risks = [
        Risk(
            description=err.get("message", ""),
            severity=_normalize_severity(err.get("severity", "medium")),
            rationale="Deterministic math/date validation result.",
            kind="validation",
            affected_document=file_name,
            source_check_id=f"basic_{err.get('type', 'unknown')}",
        )
        for err in errors
    ]
    return {"risks": risks} if risks else {}


def _normalize_severity(sev: str) -> str:
    """Normalize severity to the canonical EN literal set."""
    mapping = {
        # HU → EN (multilingual fallback)
        "alacsony": "low",
        "kozepes": "medium",
        "magas": "high",
        "kritikus": "high",
        # Already EN — pass through
        "low": "low",
        "medium": "medium",
        "high": "high",
        "critical": "high",
        "info": "info",
    }
    return mapping.get(sev.lower(), sev)
