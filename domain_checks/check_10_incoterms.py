"""10: Incoterms 2020 detection — info level, contract.

Incoterms 2020 defines 11 rules for international shipping. If a word-boundary
regex matches an Incoterm code in the contract, an info-level risk is emitted
for each match.
"""

from __future__ import annotations

import re

from domain_checks.base import make_risk
from domain_checks.check_08_gdpr_28 import _get_full_text
from graph.states.pipeline_state import Risk


_REGULATION = "Incoterms 2020"


INCOTERMS_2020: dict[str, dict] = {
    "EXW": {"name": "Ex Works", "risk": "Buyer bears almost all risk and cost"},
    "FCA": {"name": "Free Carrier", "risk": "Seller clears for export, buyer takes the main carriage"},
    "CPT": {"name": "Carriage Paid To", "risk": "Seller pays carriage, risk transfers at handover"},
    "CIP": {"name": "Carriage and Insurance Paid", "risk": "Seller pays carriage + insurance (ICC A)"},
    "DAP": {"name": "Delivered at Place", "risk": "Seller delivers to the destination, buyer clears import"},
    "DPU": {"name": "Delivered at Place Unloaded", "risk": "Seller delivers + unloads, buyer clears import"},
    "DDP": {"name": "Delivered Duty Paid", "risk": "Seller bears all costs and risk including import duties"},
    "FAS": {"name": "Free Alongside Ship", "risk": "Maritime — seller delivers alongside the ship"},
    "FOB": {"name": "Free on Board", "risk": "Maritime — risk transfers when goods are loaded on board"},
    "CFR": {"name": "Cost and Freight", "risk": "Maritime — seller pays freight, risk transfers at loading"},
    "CIF": {"name": "Cost Insurance and Freight", "risk": "Maritime — seller pays freight + insurance (ICC C)"},
}


class IncotermsCheck:
    check_id = "check_10_incoterms"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to = {"contract"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []
        full_text = _get_full_text(extracted)

        found_terms: list[tuple[str, dict]] = []
        upper_text = full_text.upper()
        for code, info in INCOTERMS_2020.items():
            # Word-boundary so "CIP Budapest" matches but "principal" doesn't
            if re.search(r'\b' + code + r'\b', upper_text):
                found_terms.append((code, info))

        for code, info in found_terms:
            risks.append(make_risk(
                description=f"Incoterms 2020 term detected: {code} ({info['name']})",
                severity="info",
                rationale=(
                    f"{info['risk']}. Incoterms 2020 defines the allocation of "
                    f"shipping risk and cost between the parties."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))

        return risks
