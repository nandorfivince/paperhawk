"""drop_repeats_node — 70% word-overlap dedup between LLM and basic risks.

Drops the "same thing in different words" duplicates.

Input:
    {"llm_risks_raw": list[Risk], "basic_risks": list[Risk], ...}

Output:
    {"risks": list[Risk]}  # final, filtered LLM risk list — merged into the
                             parent state's ``risks`` reducer
"""

from __future__ import annotations

from graph.states.pipeline_state import Risk
from nodes.risk.filter_llm_risks_node import _dict_to_risk, _risk_to_dict
from validation.llm_risk_filters import drop_repeats_of_basic


async def drop_repeats_node(state: dict) -> dict:
    """Drop LLM risks that overlap >=70% in content words with a basic risk.

    After this node, ``llm_risks_raw`` is published into ``risks``, where the
    ``merge_risks`` reducer dedups it back into the parent state — closing
    the LLM risk-analysis chain.
    """
    raw = state.get("llm_risks_raw") or []
    basic = state.get("basic_risks") or []
    if not raw:
        return {}

    raw_dicts = [_risk_to_dict(r) for r in raw]
    basic_dicts = [
        _risk_to_dict(b) if isinstance(b, Risk)
        else {"description": b.get("description", "") if isinstance(b, dict) else ""}
        for b in basic
    ]
    filtered_dicts = drop_repeats_of_basic(raw_dicts, basic_dicts)
    filtered = [_dict_to_risk(d) for d in filtered_dicts]

    # Close the chain: write the result under ``risks``, where merge_risks
    # dedups it into the parent state.
    return {"risks": filtered}
