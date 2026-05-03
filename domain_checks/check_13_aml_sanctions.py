"""13: AML / Sanctions screening — A level, universal.

Two perspectives:
  1. Sanctioned entity match (fuzzy name, EU/OFAC/UN snapshot) → HIGH
  2. High-risk country (FATF/EU list, by tax-ID prefix) → MEDIUM

The ``data/sanctions_snapshot.json`` shape:
``{"entities": [...], "high_risk_countries": [...]}``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from domain_checks.base import make_risk
from graph.states.pipeline_state import Risk


_REGULATION = "AML / Sanctions screening"

DATA_DIR = Path(__file__).parent.parent / "data"


@lru_cache(maxsize=1)
def _load_sanctions() -> dict:
    """Load ``data/sanctions_snapshot.json`` (lru_cache → loaded once)."""
    path = DATA_DIR / "sanctions_snapshot.json"
    if not path.exists():
        return {"entities": [], "high_risk_countries": []}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _fuzzy_name_match(name: str, sanctions_name: str) -> bool:
    """Simple name matching — case-insensitive substring."""
    if not name or not sanctions_name:
        return False
    return (sanctions_name.lower() in name.lower()
            or name.lower() in sanctions_name.lower())


class AMLSanctionsCheck:
    check_id = "check_13_aml_sanctions"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to = {"invoice", "contract", "delivery_note", "purchase_order", "other"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []
        sanctions = _load_sanctions()

        if not sanctions.get("entities") and not sanctions.get("high_risk_countries"):
            return risks

        # Collect parties (invoice: issuer + customer; contract: parties[])
        parties: list[dict] = []
        for party_key in ("issuer", "customer"):
            p = extracted.get(party_key)
            if isinstance(p, dict) and p.get("name"):
                parties.append({"name": p["name"], "source": party_key})
        for party in (extracted.get("parties") or []):
            if isinstance(party, dict) and party.get("name"):
                parties.append({"name": party["name"], "source": "party"})

        if not parties:
            return risks

        # Entity matching
        for party in parties:
            party_name = party["name"]
            for sanctioned in sanctions.get("entities", []):
                if _fuzzy_name_match(party_name, sanctioned["name"]):
                    risks.append(make_risk(
                        description=(
                            f"Sanctions list match: {party_name} ~ "
                            f"{sanctioned['name']} ({sanctioned['country']})"
                        ),
                        severity="high",
                        rationale=(
                            f"'{party_name}' ({party['source']}) matches the EU/OFAC "
                            f"sanctioned entity '{sanctioned['name']}' "
                            f"(country: {sanctioned['country']}). "
                            f"Verify whether the sanctions status is current."
                        ),
                        regulation=_REGULATION,
                        source_check_id=self.check_id,
                    ))

        # High-risk country detection (from tax_id prefix)
        high_risk = set(sanctions.get("high_risk_countries", []))
        for party in (extracted.get("parties") or []):
            if not isinstance(party, dict):
                continue
            tax_id = str(party.get("tax_id") or "")
            # EU VAT-ID prefix (e.g. "GB123456789" → GB)
            if len(tax_id) >= 2 and tax_id[:2].isalpha():
                country_code = tax_id[:2].upper()
                if country_code in high_risk:
                    risks.append(make_risk(
                        description=(
                            f"High-risk country: {party.get('name', '?')} "
                            f"({country_code})"
                        ),
                        severity="medium",
                        rationale=(
                            f"The party tax-ID prefix ({country_code}) indicates a "
                            f"high-risk country (FATF/EU list). Enhanced Due "
                            f"Diligence is required."
                        ),
                        regulation=_REGULATION,
                        source_check_id=self.check_id,
                    ))

        return risks
