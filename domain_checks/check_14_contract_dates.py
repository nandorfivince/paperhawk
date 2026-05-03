"""14: Contract date anomalies — A level, universal.

  * expiry_date < effective_date → HIGH (logically impossible)
  * "indefinite" / "unlimited" string and null aliases skipped (NOT flagged)
"""

from __future__ import annotations

from domain_checks.base import make_risk
from graph.states.pipeline_state import Risk
from utils.numbers import is_null_alias


_REGULATION = "Contract date best practice"


_INDEFINITE_TOKENS = {
    "indefinite", "unlimited", "perpetual", "open-ended",
    "határozatlan", "unbefristet",
}


class ContractDatesCheck:
    check_id = "check_14_contract_dates"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to = {"contract"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []

        effective_date = str(extracted.get("effective_date") or "")
        expiry_date = str(extracted.get("expiry_date") or "")

        # expiry_date < effective_date (string comparison works for YYYY-MM-DD)
        if (effective_date and expiry_date
                and not is_null_alias(effective_date) and not is_null_alias(expiry_date)
                and expiry_date.lower() not in _INDEFINITE_TOKENS
                and expiry_date < effective_date):
            risks.append(make_risk(
                description=(
                    f"Date logic contradiction: expiry date ({expiry_date}) "
                    f"precedes effective date ({effective_date})"
                ),
                severity="high",
                rationale=(
                    f"The contract's expiry date ({expiry_date}) is earlier than "
                    f"its effective date ({effective_date}). This is logically "
                    f"impossible and threatens the contract's enforceability."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))

        return risks
