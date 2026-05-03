"""drop_business_normal_node — semantic cross-check against extracted_data.

Filters out the 6 NORMAL business patterns (fulfillment ≤14 days, payment due
0–120 days, standard VAT, subjective high-price, missing PO reference, delivery
note without amount).

Input:
    {"llm_risks_raw": list[Risk], "extracted": dict, ...}

Output:
    {"llm_risks_raw": list[Risk]}  # filtered
"""

from __future__ import annotations

from nodes.risk.filter_llm_risks_node import _dict_to_risk, _risk_to_dict
from validation.llm_risk_filters import drop_business_normal_risks


async def drop_business_normal_node(state: dict) -> dict:
    """Semantic filter: cross-check against ``extracted_data``."""
    raw = state.get("llm_risks_raw") or []
    extracted = state.get("extracted") or {}
    if not raw:
        return state

    raw_dicts = [_risk_to_dict(r) for r in raw]
    filtered_dicts = drop_business_normal_risks(raw_dicts, extracted)
    filtered = [_dict_to_risk(d) for d in filtered_dicts]

    return {
        **state,
        "llm_risks_raw": filtered,
    }
