"""Dummy regex-based extractor — mock for the structured LLM extraction.

This module produces a flat dict with English field names matching the
``schemas/pydantic_models.py`` typed schemas. Multilingual regex patterns
support both English-generated and HU/DE legacy sample documents
(important for the multilingual demo flows).

In Phase 9 (test data regeneration), this module will be fully rewritten to
target the new English-generated sample PDFs. For now it provides a minimal,
structurally-correct stub so that downstream nodes (domain checks, anti-halluc
filters) receive English-keyed data and the dummy-mode pipeline runs end-to-end.

The ``_quotes`` field is populated from the matched text spans (the
quote_validator anti-halluc layer #7 verifies that those quotes actually
appear in the source full_text).
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Shared regex patterns (multilingual)
# ---------------------------------------------------------------------------

# Hungarian tax-id format: XXXXXXXX-X-XX
_TAX_ID_HU = re.compile(r"\b(\d{8})\s*-\s*(\d)\s*-\s*(\d{2})\b")

# US EIN: XX-XXXXXXX
_TAX_ID_US = re.compile(r"\b(\d{2})\s*-\s*(\d{7})\b")

# Date in any common format: YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD
_DATE = re.compile(r"\b(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\.?\b")

# Monetary amount with currency suffix: "1,234.56 USD" or "1 234 567 Ft" or "$1,234"
_MONEY = re.compile(
    r"(?:[\$€£]\s*)?([\d\s.,]+)\s*(USD|EUR|HUF|GBP|CHF|Ft|JPY|CZK|PLN|RON)?\b",
    re.I,
)


def _normalize_date(year: str, month: str, day: str) -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _parse_money(s: str) -> float | None:
    """Parse "1 234 567" or "1,234.56" → float."""
    if not s:
        return None
    cleaned = s.strip().replace(" ", "")
    has_dot = "." in cleaned
    has_comma = "," in cleaned
    if has_dot and has_comma:
        last_dot = cleaned.rfind(".")
        last_comma = cleaned.rfind(",")
        if last_dot > last_comma:
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(".", "").replace(",", ".")
    elif has_comma:
        last_comma = cleaned.rfind(",")
        if len(cleaned) - last_comma - 1 in {1, 2}:
            cleaned = cleaned[:last_comma].replace(",", "") + "." + cleaned[last_comma + 1:]
        else:
            cleaned = cleaned.replace(",", "")
    elif has_dot:
        n_dots = cleaned.count(".")
        if n_dots > 1:
            last_dot = cleaned.rfind(".")
            cleaned = cleaned[:last_dot].replace(".", "") + "." + cleaned[last_dot + 1:]
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def extract_dummy(full_text: str, doc_type: str, file_name: str) -> dict[str, Any]:
    """Doc-type-specific extractor → flat dict with EN field names."""
    extractors = {
        "invoice": _extract_invoice,
        "delivery_note": _extract_delivery_note,
        "purchase_order": _extract_purchase_order,
        "contract": _extract_contract,
        "financial_report": _extract_financial_report,
    }
    fn = extractors.get(doc_type, _extract_universal)
    out = fn(full_text, file_name)
    out.setdefault("_source", {"file_name": file_name})
    return out


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------


def _extract_invoice(text: str, file_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "_quotes": [],
        "_confidence": {},
    }

    # Invoice number — multilingual (EN/HU/DE)
    m = re.search(
        r"(?:invoice\s+(?:number|no\.?|#)|sz[aá]mla\s+sz[aá]m[a]?|Rechnungsnummer)\s*[:\#]?\s*(\S+)",
        text, re.I,
    )
    if m:
        out["invoice_number"] = m.group(1).rstrip(",.;")
        out["_quotes"].append(m.group(0)[:120])
        out["_confidence"]["invoice_number"] = "high"

    # Dates: issue, fulfillment, payment due
    for label, key in [
        (r"(?:issue\s+date|date\s+issued|ki[aá]ll[ií]t[aá]s\s*d[aá]tum[a]?|Rechnungsdatum)",
         "issue_date"),
        (r"(?:fulfillment\s+date|service\s+date|teljes[ií]t[eé]s\s*d[aá]tum[a]?|Leistungsdatum)",
         "fulfillment_date"),
        (r"(?:payment\s+due|due\s+date|fizet[eé]si\s*hat[aá]rid[oő]|F[aä]lligkeitsdatum)",
         "payment_due_date"),
    ]:
        m = re.search(rf"{label}\s*[:\#]?\s*({_DATE.pattern})", text, re.I)
        if m:
            try:
                # Group indices: 0=full, 1=date, 2=year, 3=month, 4=day
                date_str = _normalize_date(m.group(2), m.group(3), m.group(4))
                out[key] = date_str
                out["_quotes"].append(m.group(0)[:120])
                out["_confidence"][key] = "high"
            except (ValueError, IndexError):
                pass

    # Issuer + Customer parties (HU/EN labels)
    issuer_match = re.search(
        r"(?:issuer|seller|supplier|ki[aá]ll[ií]t[oó]|sz[aá]ll[ií]t[oó]|Aussteller)\s*[:\#]?\s*([A-Z][\w\s\.,&-]+?)(?=\n|adósz|tax|address|c[íi]m)",
        text, re.I,
    )
    if issuer_match:
        out["issuer"] = {"name": issuer_match.group(1).strip()}

    customer_match = re.search(
        r"(?:customer|buyer|client|vev[oő]|v[aá]s[aá]rl[oó]|Kunde)\s*[:\#]?\s*([A-Z][\w\s\.,&-]+?)(?=\n|adósz|tax|address|c[íi]m)",
        text, re.I,
    )
    if customer_match:
        out["customer"] = {"name": customer_match.group(1).strip()}

    # Tax IDs (HU format prioritized; US/EU fallback)
    tax_ids = _TAX_ID_HU.findall(text)
    if tax_ids and out.get("issuer"):
        first = tax_ids[0]
        out["issuer"]["tax_id"] = f"{first[0]}-{first[1]}-{first[2]}"

    # Totals — multilingual (EN/HU/DE)
    for label, key in [
        (r"(?:total\s+net|net\s+total|nett[oó]\s*v[eé]g[oö]ssz)", "total_net"),
        (r"(?:total\s+vat|vat\s+total|[aá]fa\s*v[eé]g[oö]ssz|MwSt[\.\s]+gesamt)", "total_vat"),
        (r"(?:total\s+gross|gross\s+total|brutt[oó]\s*v[eé]g[oö]ssz|Bruttogesamtbetrag|grand\s+total)",
         "total_gross"),
    ]:
        # The amount may carry a leading $/€/£ symbol — capture as optional prefix.
        m = re.search(rf"{label}\s*[:\#]?\s*[\$€£]?\s*([\d\s.,]+)", text, re.I)
        if m:
            val = _parse_money(m.group(1))
            if val is not None:
                out[key] = val
                out["_quotes"].append(m.group(0)[:120])
                out["_confidence"][key] = "high"

    # Currency detection
    if re.search(r"\b(USD|\$)\b", text):
        out["currency"] = "USD"
    elif re.search(r"\b(EUR|€)\b", text):
        out["currency"] = "EUR"
    elif re.search(r"\b(HUF|Ft)\b", text):
        out["currency"] = "HUF"
    elif re.search(r"\b(GBP|£)\b", text):
        out["currency"] = "GBP"

    return out


# ---------------------------------------------------------------------------
# Delivery Note
# ---------------------------------------------------------------------------


def _extract_delivery_note(text: str, file_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "_quotes": [],
        "_confidence": {},
    }
    m = re.search(
        r"(?:delivery\s+note(?:\s+number)?|szallitolev[eé]l\s*sz[aá]m|Lieferschein)\s*[:\#]?\s*(\S+)",
        text, re.I,
    )
    if m:
        out["document_number"] = m.group(1).rstrip(",.;")
        out["_quotes"].append(m.group(0)[:120])
    return out


# ---------------------------------------------------------------------------
# Purchase Order
# ---------------------------------------------------------------------------


def _extract_purchase_order(text: str, file_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "_quotes": [],
        "_confidence": {},
    }
    m = re.search(
        r"(?:purchase\s+order(?:\s+number)?|po\s*[:\#]|megrendel[eé]s\s*sz[aá]m|Bestellnummer)\s*[:\#]?\s*(\S+)",
        text, re.I,
    )
    if m:
        out["document_number"] = m.group(1).rstrip(",.;")
        out["_quotes"].append(m.group(0)[:120])
    return out


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def _extract_contract(text: str, file_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "_quotes": [],
        "_confidence": {},
        "parties": [],
    }

    # Contract type — keyword detection
    text_lower = text.lower()
    if "non-disclosure" in text_lower or "nda" in text_lower or "titoktart" in text_lower:
        out["contract_type"] = "NDA"
    elif "lease" in text_lower or "rental" in text_lower or "lizing" in text_lower:
        out["contract_type"] = "lease"
    elif "service" in text_lower or "szolgaltatas" in text_lower:
        out["contract_type"] = "service"
    elif "framework" in text_lower or "MSA" in text:
        out["contract_type"] = "MSA"

    # Effective + expiry dates
    for label, key in [
        (r"(?:effective\s+date|hat[aá]ly\s+kezdet|Vertragsbeginn)", "effective_date"),
        (r"(?:expiry\s+date|expiration|hat[aá]ly\s+v[eé]g|Vertragsende)", "expiry_date"),
    ]:
        m = re.search(rf"{label}\s*[:\#]?\s*({_DATE.pattern})", text, re.I)
        if m:
            try:
                out[key] = _normalize_date(m.group(2), m.group(3), m.group(4))
                out["_quotes"].append(m.group(0)[:120])
            except (ValueError, IndexError):
                pass

    # Governing law (multilingual)
    gov = re.search(
        r"(?:governing\s+law|applicable\s+law|ir[aá]ny[aá]d[oó]\s+jog|Anwendbares\s+Recht)\s*[:\.\,]?\s*([\w\s,]+)",
        text, re.I,
    )
    if gov:
        out["governing_law"] = gov.group(1).strip()[:120]

    # Termination clause detection
    if re.search(r"(?:termination|felmond[aá]s|K[üu]ndigung)", text, re.I):
        m = re.search(
            r"(?:termination\s+(?:terms|clause)|felmond[aá]si\s+felt[eé]tel\w*|K[üu]ndigungsfrist)\s*[:\#]?\s*(.{20,200}?)(?:\n\n|$)",
            text, re.I,
        )
        if m:
            out["termination_terms"] = m.group(1).strip()
            out["_quotes"].append(m.group(0)[:200])

    # Auto-renewal
    if re.search(r"(?:auto[\s-]?renewal|automatically\s+renewed|automatikusan\s+meg[uú]jul|automatische\s+Verl[aä]ngerung)", text, re.I):
        out["auto_renewal"] = {"enabled": True}

    # Change-of-control
    if re.search(r"(?:change[\s-]?of[\s-]?control|kontrollv[aá]ltoz[aá]s|Kontrollwechsel)", text, re.I):
        out["change_of_control"] = True

    # Non-compete
    if re.search(r"(?:non[\s-]?compete|versenytilalom|Wettbewerbsverbot)", text, re.I):
        out["non_compete"] = True

    # Confidentiality (NDA implies confidentiality even without the keyword)
    if re.search(r"(?:confidentiality|non[-\s]?disclosure|\bnda\b|titoktart|Vertraulichkeit)", text, re.I):
        out["confidentiality_clause"] = True

    return out


# ---------------------------------------------------------------------------
# Financial Report
# ---------------------------------------------------------------------------


def _extract_financial_report(text: str, file_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "_quotes": [],
        "_confidence": {},
    }

    text_lower = text.lower()
    if "income statement" in text_lower or "p&l" in text_lower or "profit" in text_lower:
        out["report_type"] = "income_statement"
    elif "balance sheet" in text_lower or "merleg" in text_lower:
        out["report_type"] = "balance_sheet"
    elif "cash flow" in text_lower:
        out["report_type"] = "cash_flow"

    # Accounting standard
    if "IFRS" in text:
        out["accounting_standard"] = "IFRS"
    elif "US-GAAP" in text or "US GAAP" in text:
        out["accounting_standard"] = "US-GAAP"
    elif "HU-GAAP" in text or "HÁR" in text:
        out["accounting_standard"] = "HU-GAAP"
    elif "HGB" in text:
        out["accounting_standard"] = "DE-HGB"

    # Period
    for label, key in [
        (r"(?:period\s+start|id[oő]szak\s+kezdet)", "period_start"),
        (r"(?:period\s+end|id[oő]szak\s+v[eé]g)", "period_end"),
    ]:
        m = re.search(rf"{label}\s*[:\#]?\s*({_DATE.pattern})", text, re.I)
        if m:
            try:
                out[key] = _normalize_date(m.group(2), m.group(3), m.group(4))
            except (ValueError, IndexError):
                pass

    return out


# ---------------------------------------------------------------------------
# Universal (any other doc type)
# ---------------------------------------------------------------------------


def _extract_universal(text: str, file_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "_quotes": [],
        "_confidence": {},
        "document_type": "other",
        "document_language": "en",
        "parties": [],
        "dates": {},
        "amounts": {},
        "line_items": [],
    }

    # Try to find any date as a generic signature
    m = _DATE.search(text)
    if m:
        try:
            out["dates"]["signature"] = _normalize_date(m.group(1), m.group(2), m.group(3))
        except (ValueError, IndexError):
            pass

    return out
