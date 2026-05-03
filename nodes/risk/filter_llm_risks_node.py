"""filter_llm_risks_node — formal filter for the LLM risk list (anti-halluc layer 1).

Input (from ``llm_risk_node``):
    {"llm_risks_raw": list[Risk], "doc_file_name": str, "extracted": dict, "basic_risks": list[Risk]}

Output:
    {"llm_risks_raw": list[Risk]}  # filtered; the key is preserved for the next node
"""

from __future__ import annotations

from graph.states.pipeline_state import Risk
from validation.llm_risk_filters import filter_llm_risks


def _risk_to_dict(r: Risk) -> dict:
    """Pydantic Risk → dict (the filters operate on dicts)."""
    return {
        "description": r.description,
        "severity": r.severity,
        "rationale": r.rationale,
        "kind": r.kind,
        "affected_document": r.affected_document,
        "source_check_id": r.source_check_id,
        "regulation": r.regulation,
    }


def _dict_to_risk(d: dict) -> Risk:
    """Dict → Pydantic Risk."""
    return Risk(
        description=d.get("description", ""),
        severity=d.get("severity", "medium"),
        rationale=d.get("rationale", ""),
        kind=d.get("kind", "llm_analysis"),
        affected_document=d.get("affected_document"),
        source_check_id=d.get("source_check_id"),
        regulation=d.get("regulation"),
    )


async def filter_llm_risks_node(state: dict) -> dict:
    """Formal filter: ≥5 words, ≥2 domain terms, ≥1 concrete data point."""
    raw = state.get("llm_risks_raw") or []
    if not raw:
        return state

    raw_dicts = [_risk_to_dict(r) for r in raw]
    filtered_dicts = filter_llm_risks(raw_dicts)
    filtered = [_dict_to_risk(d) for d in filtered_dicts]

    return {
        **state,
        "llm_risks_raw": filtered,
    }
