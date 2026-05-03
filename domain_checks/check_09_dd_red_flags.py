"""09: DD red flags (M&A best practice) — A/B level, universal.

4 red flags:
  1. Missing change-of-control clause for high-value contracts (MEDIUM)
     — value > 4.83M parity watermark
  2. Auto-renewal (MEDIUM) — unpredictable obligation
  3. Non-compete clause (MEDIUM) — buyer flexibility constraint
  4. Non-assignable contract (HIGH) — critical for M&A
"""

from __future__ import annotations

from domain_checks.base import make_risk
from domain_checks.check_08_gdpr_28 import _get_full_text, _text_contains_any
from graph.states.pipeline_state import Risk
from utils.numbers import coerce_number


_REGULATION = "M&A DD best practice"
_VALUE_THRESHOLD = 4_830_000  # parity watermark for ~5M


class DDRedFlagsCheck:
    check_id = "check_09_dd_red_flags"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to = {"contract"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []

        full_text = _get_full_text(extracted)

        # 1. Missing change-of-control clause — value > threshold AND no mention
        value_dict = extracted.get("value") or {}
        if isinstance(value_dict, dict) and value_dict:
            total = coerce_number(value_dict.get("amount"))
        else:
            total = coerce_number(extracted.get("total_value"))

        has_coc = _text_contains_any(full_text, [
            "change of control", "change-of-control", "ownership change",
            "acquisition", "buyout",
            "tulajdonosváltozás", "irányításváltozás", "változás az irányításban",
            "kontrollváltozás", "felvasárl", "akvizíció",
            "Kontrollwechsel", "Eigentümerwechsel",
        ])
        if total is not None and total > _VALUE_THRESHOLD and not has_coc:
            risks.append(make_risk(
                description="Missing change-of-control clause in a high-value contract",
                severity="medium",
                rationale=(
                    f"Contract value is {total:,.0f}, but no change-of-control "
                    f"clause is present. In an acquisition, the contract's "
                    f"future would be uncertain."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))

        # 2. Auto-renewal
        has_auto_renewal = _text_contains_any(full_text, [
            "auto-renewal", "automatic renewal", "evergreen clause",
            "automatically renewed",
            "automatikusan megújul", "hallgatólagos megújítás", "meghosszabbodik",
            "automatische Verlängerung",
        ])
        if has_auto_renewal:
            risks.append(make_risk(
                description="Auto-renewal clause detected",
                severity="medium",
                rationale=(
                    "The contract contains an auto-renewal clause. From a DD "
                    "perspective, this creates an open-ended obligation."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))

        # 3. Non-compete / restrictive covenant
        has_non_compete = _text_contains_any(full_text, [
            "non-compete", "non compete", "restrictive covenant",
            "may not engage in",
            "versenytilalm", "versenykorlátozás", "versenytilalom", "nem folytathat",
            "Wettbewerbsverbot",
        ])
        if has_non_compete:
            risks.append(make_risk(
                description="Non-compete clause detected",
                severity="medium",
                rationale=(
                    "The contract contains a non-compete clause. In an M&A "
                    "context, EU practice limits these to a maximum of 2 years."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))

        # 4. Non-assignable contract
        has_no_assignment = _text_contains_any(full_text, [
            "not assignable", "assignment prohibited", "no assignment",
            "may not be assigned",
            "nem ruházható át", "nem engedményezhető", "átruházás tilalma",
            "nicht übertragbar",
        ])
        if has_no_assignment:
            risks.append(make_risk(
                description="Contract assignment restriction",
                severity="high",
                rationale=(
                    "The contract is non-assignable. After an acquisition, the "
                    "new owner cannot automatically step into the contract."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))

        return risks
