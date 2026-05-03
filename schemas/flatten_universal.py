"""Universal schema → flat field mapping.

The 14 domain checks read flat field names that mirror the typed schemas
(``invoice_number``, ``issuer.name``, ``line_items[].vat_rate``, ...). If
extract returns a payload following ``universal.json`` (unknown doc_type),
we flatten it first.
"""

from __future__ import annotations

from typing import Any


def flatten_universal(data: dict, doc_type: str | None = None) -> dict:
    """Universal-schema dict → flat dict with typed field names.

    Args:
        data: A dict shaped like ``universal.json`` (``document_type``,
              ``parties``, ``dates``, ``amounts``, ``line_items``,
              ``contract_elements`` ...).
        doc_type: Optional (``invoice``, ``contract``, ...). If provided, the
                  flatten optimizes for that target shape (e.g. for invoice we
                  split ``parties`` into ``issuer`` and ``customer``).

    Returns:
        Flat dict with field names matching the domain_checks expectations.
    """
    if not isinstance(data, dict):
        return data

    # Universal markers — these only appear in the universal.json shape (nested
    # structures). The ``parties`` key alone is NOT a sufficient indicator
    # because typed schemas (Contract/Invoice) use it as a top-level list too.
    # Only the truly universal-structural keys ("dates", "amounts",
    # "contract_elements") signal that flattening is needed.
    universal_indicators = {
        "dates",
        "amounts",
        "contract_elements",
        "document_type",
        "document_number",
    }
    if not (universal_indicators & set(data.keys())):
        return data

    flat: dict[str, Any] = {}

    # ----- Document-level basics -----
    flat["invoice_number"] = data.get("document_number")  # universal doc number
    flat["document_number"] = data.get("document_number")
    flat["document_type"] = data.get("document_type") or doc_type

    # ----- Dates -----
    dates = data.get("dates") or {}
    flat["issue_date"] = dates.get("issue")
    flat["fulfillment_date"] = dates.get("fulfillment")
    flat["payment_due_date"] = dates.get("payment_due")
    flat["effective_date"] = dates.get("effective")
    flat["expiry_date"] = dates.get("expiry")
    flat["signature_date"] = dates.get("signature")

    # ----- Amounts -----
    amounts = data.get("amounts") or {}
    flat["total_net"] = amounts.get("total_net")
    flat["total_vat"] = amounts.get("total_vat")
    flat["total_gross"] = amounts.get("total_gross")
    flat["currency"] = amounts.get("currency", "USD")

    # ----- Parties -----
    # Heuristic: split into issuer / customer based on role.
    parties = data.get("parties") or []
    issuer = None
    customer = None
    for party in parties:
        if not isinstance(party, dict):
            continue
        role = (party.get("role") or "").lower()
        if any(k in role for k in ("issuer", "supplier", "vendor", "seller", "kiallit", "szallit", "elado")):
            issuer = issuer or party
        elif any(k in role for k in ("customer", "buyer", "lessee", "vevo", "vasarlo", "berlo")):
            customer = customer or party
    # If role is ambiguous, first → issuer, second → customer
    if issuer is None and len(parties) >= 1:
        issuer = parties[0] if isinstance(parties[0], dict) else None
    if customer is None and len(parties) >= 2:
        customer = parties[1] if isinstance(parties[1], dict) else None

    flat["issuer"] = issuer
    flat["customer"] = customer

    # ----- Line items -----
    flat["line_items"] = data.get("line_items") or []

    # ----- Contract elements -----
    contract = data.get("contract_elements") or {}
    flat["contract_type"] = contract.get("contract_type")
    flat["termination_terms"] = contract.get("termination_terms")
    flat["penalty"] = contract.get("penalty")
    flat["confidentiality_clause"] = contract.get("confidentiality_clause")
    flat["governing_law"] = contract.get("governing_law")
    flat["key_clauses"] = contract.get("key_clauses") or []

    # ----- Anti-halluc fields preserved -----
    flat["_quotes"] = data.get("_quotes") or []
    flat["_confidence"] = data.get("_confidence") or {}
    flat["_source"] = data.get("_source") or {}

    # Strip None / empty values for cleaner JSON output (the domain checks use
    # ``is_empty()`` themselves, but cleaner output benefits the chat tools).
    return {k: v for k, v in flat.items() if v not in (None, [], {})}
