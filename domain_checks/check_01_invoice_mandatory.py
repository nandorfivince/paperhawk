"""01: Invoice mandatory fields (HU VAT Act §169) — A/B level, HU jurisdiction.

Mirrors prototype-agentic-langgraph's check_invoice_mandatory_fields, fully
translated to English with the new EN field names:

  1. Top-level fields (4) — invoice_number, issue_date, fulfillment_date, payment_method
  2. Party-level fields (5) — issuer.{name,address,tax_id}, customer.{name,address}
  3. Item-level fields (5) — _INVOICE_ITEM_FIELDS with all-missing logic
  4. Conditional: VAT >= 100,000 HUF threshold → customer.tax_id required
"""

from __future__ import annotations

from domain_checks.base import is_empty, make_risk
from graph.states.pipeline_state import Risk
from utils.numbers import coerce_number


_INVOICE_MANDATORY = [
    ("invoice_number", "Invoice number", "high"),
    ("issue_date", "Issue date", "high"),
    ("fulfillment_date", "Fulfillment date", "medium"),
    ("payment_method", "Payment method", "medium"),
]

_INVOICE_PARTY_FIELDS = [
    ("issuer", "name", "Issuer name", "high"),
    ("issuer", "address", "Issuer address", "medium"),
    ("issuer", "tax_id", "Issuer tax ID", "high"),
    ("customer", "name", "Customer name", "high"),
    ("customer", "address", "Customer address", "medium"),
]

_INVOICE_ITEM_FIELDS = [
    ("description", "Item description", "high"),
    ("quantity", "Quantity", "medium"),
    ("unit", "Unit of measure", "medium"),
    ("unit_price_net", "Unit price (net)", "medium"),
    ("vat_rate", "VAT rate", "high"),
]

_REGULATION = "HU VAT Act §169"


class InvoiceMandatoryCheck:
    check_id = "check_01_invoice_mandatory"
    regulation = _REGULATION
    is_hu_specific = True
    applies_to = {"invoice"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []

        # Top-level mandatory fields
        for field, label, sev in _INVOICE_MANDATORY:
            if is_empty(extracted.get(field)):
                risks.append(make_risk(
                    description=f"Missing mandatory invoice element: {label}",
                    severity=sev,
                    rationale=(
                        f"Per HU VAT Act §169, '{label}' is a mandatory element on every "
                        f"invoice. The field is null or empty."
                    ),
                    regulation=_REGULATION,
                    source_check_id=self.check_id,
                ))

        # Party-level mandatory fields
        for party, sub_field, label, sev in _INVOICE_PARTY_FIELDS:
            party_data = extracted.get(party) or {}
            if not isinstance(party_data, dict):
                party_data = {}
            if is_empty(party_data.get(sub_field)):
                risks.append(make_risk(
                    description=f"Missing mandatory invoice element: {label}",
                    severity=sev,
                    rationale=(
                        f"Per HU VAT Act §169, '{label}' is mandatory. "
                        f"The '{party}.{sub_field}' field is null or empty."
                    ),
                    regulation=_REGULATION,
                    source_check_id=self.check_id,
                ))

        # Item-level fields — flag only when the field is missing in EVERY line item
        items = extracted.get("line_items") or []
        if items:
            for item_field, label, sev in _INVOICE_ITEM_FIELDS:
                all_missing = all(
                    is_empty(item.get(item_field))
                    for item in items
                    if isinstance(item, dict)
                )
                if all_missing and len(items) > 0:
                    risks.append(make_risk(
                        description=f"Missing mandatory line-item element: {label}",
                        severity=sev,
                        rationale=(
                            f"Per HU VAT Act §169, '{label}' is mandatory for every line "
                            f"item. None of the items contain it."
                        ),
                        regulation=_REGULATION,
                        source_check_id=self.check_id,
                    ))

        # Conditional: customer tax_id required when VAT >= 100,000 HUF (parity threshold)
        vat_total = coerce_number(extracted.get("total_vat"))
        customer = extracted.get("customer") or {}
        if not isinstance(customer, dict):
            customer = {}
        if vat_total is not None and vat_total >= 100_417 and is_empty(customer.get("tax_id")):
            risks.append(make_risk(
                description="Customer tax ID missing while VAT exceeds 100,000 HUF threshold",
                severity="medium",
                rationale=(
                    f"Per HU VAT Act §169(e), the customer tax ID is mandatory when "
                    f"the VAT total reaches 100,000 HUF. VAT total: {vat_total:,.0f}."
                ),
                regulation=_REGULATION,
                source_check_id=self.check_id,
            ))

        return risks
