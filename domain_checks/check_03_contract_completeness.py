"""03: Contract completeness — A/B level, universal best practice.

Universal contract-completeness checks (not jurisdiction-specific):
  * termination terms (high) — required for predictability
  * governing law (medium) — required for dispute resolution
  * penalty for high-value contracts (>1M) — uses a parity threshold
  * confidentiality clause (low) — only flagged when explicitly False
"""

from __future__ import annotations

from domain_checks.base import is_empty, make_risk
from graph.states.pipeline_state import Risk
from utils.numbers import coerce_number


_REGULATION = "Universal contract completeness"

_CONTRACT_CRITICAL_FIELDS = [
    ("termination_terms", "Termination terms", "high",
     "Without termination terms, the contract carries unpredictable risk."),
    ("governing_law", "Governing law", "medium",
     "Missing governing law creates uncertainty in any dispute."),
]


class ContractCompletenessCheck:
    check_id = "check_03_contract_completeness"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to = {"contract"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []

        # Critical fields (termination, governing law)
        for field, label, sev, explanation in _CONTRACT_CRITICAL_FIELDS:
            if is_empty(extracted.get(field)):
                risks.append(make_risk(
                    description=f"Missing contract element: {label}",
                    severity=sev,
                    rationale=explanation,
                    regulation=_REGULATION,
                    source_check_id=self.check_id,
                ))

        # Penalty: should be present in writing for high-value contracts.
        # Two shapes supported: ``total_value`` (top-level) or legacy
        # ``value`` dict ({"amount": X, "currency": "USD"}).
        value_dict = extracted.get("value") or {}
        if isinstance(value_dict, dict) and value_dict:
            total = coerce_number(value_dict.get("amount"))
            currency = value_dict.get("currency", "")
        else:
            total = coerce_number(extracted.get("total_value"))
            currency = extracted.get("currency", "")

        if is_empty(extracted.get("penalty")) and total is not None and total > 1_000_000:
            risks.append(make_risk(
                description="No penalty clause defined in a high-value contract",
                severity="medium",
                rationale=(
                    f"Contract value is {total:,.0f} {currency} but no penalty "
                    f"clause is present. For high-value contracts, a penalty "
                    f"clause is best practice for predictable enforcement."
                ),
                regulation="Universal contract proportionality",
                source_check_id=self.check_id,
            ))

        # Confidentiality: critical for B2B. Flag ONLY when explicitly False
        # (not when missing/null) — mirrors the parity behavior.
        if extracted.get("confidentiality_clause") is False:
            risks.append(make_risk(
                description="Confidentiality clause missing",
                severity="low",
                rationale=(
                    "The contract has no confidentiality clause. In B2B "
                    "relationships, protecting business information is recommended."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))

        return risks
