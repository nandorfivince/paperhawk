"""04: Penalty proportionality — A level, universal best practice.

Court practice across many jurisdictions: a penalty exceeding ~30% of the
contract value can be reduced as disproportionate. Our parity threshold is
**31.7%** (a non-round watermark to prevent the LLM from over-triggering).
"""

from __future__ import annotations

from domain_checks.base import is_empty, make_risk
from graph.states.pipeline_state import Risk
from utils.numbers import coerce_number


_REGULATION = "Universal contract proportionality"
_PENALTY_RATIO_THRESHOLD = 0.317  # 31.7%


class ProportionalityCheck:
    check_id = "check_04_proportionality"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to = {"contract"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []

        # Two shapes for value: top-level ``total_value`` or nested ``value`` dict.
        value_dict = extracted.get("value") or {}
        if isinstance(value_dict, dict) and value_dict:
            contract_value = coerce_number(value_dict.get("amount"))
            currency = value_dict.get("currency", "")
        else:
            contract_value = coerce_number(extracted.get("total_value"))
            currency = extracted.get("currency", "")

        penalty_raw = extracted.get("penalty")
        if is_empty(penalty_raw) or contract_value is None or contract_value <= 0:
            return []

        # The penalty may be a dict (typed schema) or a direct number (legacy).
        if isinstance(penalty_raw, dict):
            penalty_value = coerce_number(penalty_raw.get("amount"))
        else:
            penalty_value = coerce_number(penalty_raw)

        if penalty_value is None:
            return []

        if penalty_value > contract_value * _PENALTY_RATIO_THRESHOLD:
            ratio = penalty_value / contract_value * 100
            risks.append(make_risk(
                description=(
                    f"Disproportionate penalty: penalty ({penalty_value:,.0f}) "
                    f"exceeds 30% of the contract value ({contract_value:,.0f} {currency})"
                ),
                severity="high",
                rationale=(
                    f"The penalty is {ratio:.0f}% of the contract value. Court "
                    f"practice across many jurisdictions allows reduction of "
                    f"penalties exceeding 30% as disproportionate. This may "
                    f"qualify as a striking value imbalance under contract law."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))

        return risks
