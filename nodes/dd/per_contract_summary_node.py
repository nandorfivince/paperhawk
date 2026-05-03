"""per_contract_summary_node — Python-deterministic per-contract summary.

Risk-level heuristic: count of risk_elements + red_flags determines
``low``/``medium``/``high``.
"""

from __future__ import annotations

from graph.states.dd_state import DDContractSummary, DDState
from graph.states.pipeline_state import ProcessedDocument
from utils.numbers import coerce_number


def _build_summary(d: ProcessedDocument) -> DDContractSummary:
    extracted = d.extracted.raw if d.extracted else {}

    # Parties
    parties_raw = extracted.get("parties") or []
    party_names = []
    if isinstance(parties_raw, list):
        for party in parties_raw:
            if isinstance(party, dict) and party.get("name"):
                party_names.append(str(party["name"]))

    # Red flags (DD red flags + GDPR issues + auto-renewal)
    red_flags: list[str] = []
    if extracted.get("change_of_control") is True:
        red_flags.append("change-of-control clause")
    if extracted.get("non_compete") is True:
        red_flags.append("non-compete (restrictive covenant)")
    auto_renewal = extracted.get("auto_renewal")
    if isinstance(auto_renewal, dict) and auto_renewal.get("enabled"):
        red_flags.append("auto-renewal clause")

    # Risk elements (from per-doc risks)
    risk_elements: list[str] = []
    for r in d.risks:
        if r.severity in {"high", "medium"}:
            risk_elements.append(r.description)

    # Risk-level heuristic
    if red_flags or len(risk_elements) >= 2:
        level = "high"
    elif risk_elements:
        level = "medium"
    else:
        level = "low"

    return DDContractSummary(
        file_name=d.ingested.file_name if d.ingested else "?",
        contract_type=str(extracted.get("contract_type", "unknown")),
        parties=party_names,
        effective_date=extracted.get("effective_date"),
        expiry_date=extracted.get("expiry_date"),
        total_value=coerce_number(extracted.get("total_value")),
        currency=extracted.get("currency") or "USD",
        monthly_fee=coerce_number(extracted.get("monthly_fee")),
        monthly_fee_currency=extracted.get("monthly_fee_currency") or "USD",
        risk_level=level,
        risk_elements=risk_elements,
        red_flags=red_flags,
    )


async def per_contract_summary_node(state: DDState) -> dict:
    documents = state.get("documents") or []
    contracts = [_build_summary(d) for d in documents if d.ingested is not None]
    return {"contracts": contracts}
