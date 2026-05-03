"""Plausibility checks — flag unusual values as info-level warnings.

Does not drop anything; only marks. Language- and country-agnostic.
"""

from __future__ import annotations

from utils.dates import parse_date_safe
from utils.numbers import coerce_number, is_null_alias


# Known VAT rates across countries
KNOWN_VAT_RATES = {0, 5, 7, 8, 10, 12, 13, 15, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27}


def validate_plausibility(extracted: dict) -> list[dict]:
    """Flag unusual values as warnings.

    Returns: list of {"type": "plausibility", "severity": ..., "message": ...}
    """
    warnings: list[dict] = []

    # VAT rate per line item
    items = extracted.get("line_items") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        vat_rate = coerce_number(item.get("vat_rate"))
        if vat_rate is None:
            continue
        name = item.get("description", "?")
        if vat_rate < 0:
            warnings.append({
                "type": "plausibility",
                "severity": "medium",
                "message": f"Negative VAT rate ({vat_rate:g}%) on line '{name}'",
            })
        elif vat_rate > 50:
            warnings.append({
                "type": "plausibility",
                "severity": "medium",
                "message": f"Unusually high VAT rate ({vat_rate:g}%) on line '{name}'",
            })
        elif int(vat_rate) not in KNOWN_VAT_RATES and vat_rate != 0:
            warnings.append({
                "type": "plausibility",
                "severity": "low",
                "message": f"Non-standard VAT rate ({vat_rate:g}%) on line '{name}'",
            })

    # Negative totals
    for field in ("total_net", "total_vat", "total_gross", "amount"):
        amount = coerce_number(extracted.get(field))
        if amount is not None and amount < 0:
            warnings.append({
                "type": "plausibility",
                "severity": "medium",
                "message": f"Negative amount: {field} = {amount:.0f}",
            })

    # Date plausibility (skip null aliases)
    for field in (
        "issue_date", "fulfillment_date", "payment_due_date",
        "order_date", "delivery_due_date", "delivery_date",
        "effective_date", "expiry_date",
    ):
        date_str = extracted.get(field)
        if not date_str or not isinstance(date_str, str):
            continue
        if is_null_alias(date_str):
            continue
        # parse_date_safe supports YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD, DD.MM.YYYY
        # — multilingual helper for HU/DE/EN dates.
        dt = parse_date_safe(date_str)
        if dt is None:
            warnings.append({
                "type": "plausibility",
                "severity": "low",
                "message": f"Unparseable date: {field} = '{date_str}'",
            })
        elif dt.year < 2000:
            warnings.append({
                "type": "plausibility",
                "severity": "low",
                "message": f"Old date: {field} = {date_str} (before 2000)",
            })
        elif dt.year > 2030 and field not in ("expiry_date", "effective_date"):
            # Contract expiry can naturally be in the distant future
            warnings.append({
                "type": "plausibility",
                "severity": "low",
                "message": f"Future date: {field} = {date_str} (after 2030)",
            })

    return warnings
