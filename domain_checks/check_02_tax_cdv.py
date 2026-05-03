"""02: Hungarian tax ID check digit (mod-11) — A level, HU jurisdiction.

Hungarian tax ID format: ``XXXXXXXX-X-XX`` (8 digits + 1 CDV + 2 county code).
The legal algorithm is mod-11; the practical implementation is mod-10:
  - ``checksum = sum(digit[i] * weight[i] for i in range(7))``  — first 7 digits
  - ``expected_cdv = (10 - (checksum % 10)) % 10``
  - ``digit[7]`` (8th digit) == expected_cdv → valid

Weights: ``[9, 7, 3, 1, 9, 7, 3]`` (legally fixed).
"""

from __future__ import annotations

from domain_checks.base import is_empty, make_risk
from graph.states.pipeline_state import Risk


_REGULATION = "HU Tax Procedure Act §22"

# Legally fixed weights
_CDV_WEIGHTS = [9, 7, 3, 1, 9, 7, 3]


def compute_cdv(first7: str) -> int | None:
    """Compute the CDV check digit from the first 7 digits.

    Args:
        first7: the first 7 digits as a string.

    Returns:
        Computed CDV (0-9) or None for invalid input.
    """
    if not first7 or len(first7) < 7 or not first7[:7].isdigit():
        return None
    checksum = sum(int(d) * w for d, w in zip(first7[:7], _CDV_WEIGHTS, strict=False))
    return (10 - (checksum % 10)) % 10


def validate_tax_cdv(tax_number: str) -> bool | None:
    """Validate a Hungarian tax ID's check digit.

    Format: XXXXXXXX-X-XX (8 digits + 1 CDV + 2 county code).
    Returns: True (valid), False (CDV mismatch), None (invalid format).
    """
    if not tax_number or not isinstance(tax_number, str):
        return None
    clean = tax_number.replace("-", "").replace(" ", "")
    if len(clean) != 11 or not clean.isdigit():
        return None
    expected = compute_cdv(clean[:7])
    if expected is None:
        return None
    return int(clean[7]) == expected


class TaxCDVCheck:
    check_id = "check_02_tax_cdv"
    regulation = _REGULATION
    is_hu_specific = True
    applies_to = {"invoice", "contract", "delivery_note", "purchase_order", "other"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []

        # Issuer / customer tax IDs (invoices and similar)
        for party_key, party_label in [("issuer", "Issuer"), ("customer", "Customer")]:
            party = extracted.get(party_key)
            if not isinstance(party, dict):
                continue
            tax_num = party.get("tax_id")
            if is_empty(tax_num):
                continue
            result = validate_tax_cdv(str(tax_num))
            if result is False:
                risks.append(make_risk(
                    description=f"{party_label} tax ID check digit invalid: {tax_num}",
                    severity="high",
                    rationale=(
                        f"The tax ID {tax_num} has an invalid mod-11 check digit. "
                        f"This indicates an invalid Hungarian tax ID."
                    ),
                    regulation=_REGULATION,
                    source_check_id=self.check_id,
                ))

        # Contract parties' tax IDs
        parties = extracted.get("parties") or []
        if isinstance(parties, list):
            for party in parties:
                if not isinstance(party, dict):
                    continue
                tax_num = party.get("tax_id")
                if is_empty(tax_num):
                    continue
                name = party.get("name", "unknown")
                result = validate_tax_cdv(str(tax_num))
                if result is False:
                    risks.append(make_risk(
                        description=f"Party tax ID check digit invalid: {name} ({tax_num})",
                        severity="high",
                        rationale=(
                            f"The tax ID {tax_num} has an invalid mod-11 check digit."
                        ),
                        regulation=_REGULATION,
                        source_check_id=self.check_id,
                    ))

        return risks
