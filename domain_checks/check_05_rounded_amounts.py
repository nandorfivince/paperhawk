"""05: Rounded-amount ratio (ISA 240, Journal of Accountancy) — B/C level, invoice.

Thresholds (based on ISA 240 + Journal of Accountancy 2018 fraud research):
  * > 24.3% suspiciously rounded → MEDIUM
  * > 14.7% rounded → LOW
  * < 3 data points → skip (not statistically meaningful)

A single amount is "suspiciously rounded" if:
  * abs > 10_417 (parity watermark) AND
  * abs % 10_000 == 0 (divisible by 10,000)
"""

from __future__ import annotations

from domain_checks.base import make_risk
from graph.states.pipeline_state import Risk
from utils.numbers import coerce_number


_REGULATION = "ISA 240"
_HIGH_RATIO = 0.243
_LOW_RATIO = 0.147


def _is_suspiciously_round(amount: float) -> bool:
    """Suspiciously rounded if > 10,417 AND divisible by 10,000."""
    if amount == 0:
        return False
    abs_amount = abs(amount)
    if abs_amount > 10_417 and abs_amount % 10_000 == 0:
        return True
    return False


class RoundedAmountsCheck:
    check_id = "check_05_rounded_amounts"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to = {"invoice"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []
        amounts: list[float] = []

        # Collect line-item amounts
        for item in (extracted.get("line_items") or []):
            if not isinstance(item, dict):
                continue
            for field in ("total_net", "total_gross"):
                val = coerce_number(item.get(field))
                if val is not None and val != 0:
                    amounts.append(val)

        # Top-level totals
        for field in ("total_net", "total_gross"):
            val = coerce_number(extracted.get(field))
            if val is not None and val != 0:
                amounts.append(val)

        if len(amounts) < 3:
            return risks  # Not statistically meaningful

        round_count = sum(1 for a in amounts if _is_suspiciously_round(a))
        ratio = round_count / len(amounts)

        if ratio > _HIGH_RATIO:
            risks.append(make_risk(
                description=(
                    f"High proportion of rounded amounts: {round_count}/{len(amounts)} "
                    f"({ratio:.0%})"
                ),
                severity="medium",
                rationale=(
                    f"{ratio:.0%} of the amounts are suspiciously rounded "
                    f"(divisible by 10,000 and >10,000). Above 25% may indicate "
                    f"fraud (Journal of Accountancy, 2018)."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))
        elif ratio > _LOW_RATIO:
            risks.append(make_risk(
                description=(
                    f"Notable proportion of rounded amounts: {round_count}/{len(amounts)} "
                    f"({ratio:.0%})"
                ),
                severity="low",
                rationale=(
                    f"{ratio:.0%} of the amounts are rounded. Above 15% is higher "
                    f"than the typical baseline."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))

        return risks
