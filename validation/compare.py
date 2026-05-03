"""Cross-document checks — three-way matching and two-doc compare.

Pure Python, no LLM calls. ``utils.numbers.coerce_number`` provides tolerant
numeric normalization (HU/US/EU/FR formats, currency tokens, null aliases).

Two APIs:
  * ``three_way_match(invoice, delivery_note, purchase_order)`` → ComparisonResult
  * ``compare_two_documents(doc_a, doc_b, fields)`` → ComparisonResult

``ComparisonResult`` is dict-shaped (Pydantic-compatible). The ``compare_node``
wraps it into a ``ComparisonReport`` Pydantic model in the parent state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from utils.numbers import coerce_number


@dataclass
class MatchResult:
    """One comparison result."""
    status: str  # "match" | "mismatch" | "missing"
    severity: str  # "ok" | "warning" | "critical"
    message: str
    field_name: str
    expected: str | float | None = None
    actual: str | float | None = None
    source_a: str = ""
    source_b: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
            "field_name": self.field_name,
            "expected": self.expected,
            "actual": self.actual,
            "source_a": self.source_a,
            "source_b": self.source_b,
        }


@dataclass
class ComparisonResult:
    """Aggregated three-way / pair-wise comparison output."""
    matches: list[MatchResult] = field(default_factory=list)
    total_checks: int = 0
    ok_count: int = 0
    warning_count: int = 0
    critical_count: int = 0
    missing_count: int = 0

    def add(self, result: MatchResult) -> None:
        self.matches.append(result)
        self.total_checks += 1
        if result.severity == "ok":
            self.ok_count += 1
        elif result.severity == "warning":
            self.warning_count += 1
        elif result.severity == "critical":
            self.critical_count += 1
        if result.status == "missing":
            self.missing_count += 1


# ---------------------------------------------------------------------------
# Apples-to-apples amount extraction (multilingual EN-first + HU/legacy fallback)
# ---------------------------------------------------------------------------


def _get_gross_amount(data: dict) -> float | None:
    if not isinstance(data, dict):
        return None
    for field_name in (
        "total_gross", "gross_total", "gross_amount",
        # Legacy / multilingual fallback
        "brutto_vegosszeg", "brutto_osszeg", "brutto_vegosszeg_huf",
    ):
        val = coerce_number(data.get(field_name))
        if val is not None:
            return val
    return None


def _get_net_amount(data: dict) -> float | None:
    if not isinstance(data, dict):
        return None
    for field_name in (
        "total_net", "net_total", "net_amount",
        # Legacy / multilingual fallback
        "netto_vegosszeg", "netto_osszeg", "netto_vegosszeg_huf",
    ):
        val = coerce_number(data.get(field_name))
        if val is not None:
            return val
    return None


def _get_generic_amount(data: dict) -> float | None:
    if not isinstance(data, dict):
        return None
    for field_name in ("amount", "total", "value", "osszeg", "ertek"):
        val = coerce_number(data.get(field_name))
        if val is not None:
            return val
    return None


# ---------------------------------------------------------------------------
# Amount comparison with tolerance tiers
# ---------------------------------------------------------------------------


def _compare_amounts(
    report: ComparisonResult,
    label: str,
    amount_a, amount_b,
    source_a: str = "",
    source_b: str = "",
    tolerance_pct: float = 0.01,
) -> None:
    """Compare two amounts with tolerance tiers.

    Tolerance levels:
      * ≤ 1 absolute diff → OK
      * ≤ 1% diff → OK (rounding edge)
      * ≤ 5% diff → warning
      * > 5% diff → critical
    """
    a = coerce_number(amount_a)
    b = coerce_number(amount_b)

    if a is None or b is None:
        return

    if a == 0 and b == 0:
        return

    diff = abs(a - b)
    max_val = max(abs(a), abs(b))
    pct_diff = (diff / max_val * 100) if max_val > 0 else 0

    if diff <= 1:
        report.add(MatchResult(
            status="match", severity="ok",
            message=f"{label}: matches ({a:.0f})",
            field_name=label,
        ))
    elif pct_diff <= tolerance_pct * 100:
        report.add(MatchResult(
            status="match", severity="ok",
            message=f"{label}: diff within rounding tolerance ({diff:.0f})",
            field_name=label,
        ))
    elif pct_diff <= 5:
        report.add(MatchResult(
            status="mismatch", severity="warning",
            message=f"{label}: {pct_diff:.1f}% diff ({a:.0f} vs {b:.0f})",
            field_name=label, expected=a, actual=b,
            source_a=source_a, source_b=source_b,
        ))
    else:
        report.add(MatchResult(
            status="mismatch", severity="critical",
            message=f"{label}: {pct_diff:.1f}% diff ({a:.0f} vs {b:.0f})",
            field_name=label, expected=a, actual=b,
            source_a=source_a, source_b=source_b,
        ))


def _compare_doc_amounts(
    report: ComparisonResult,
    doc_a: dict, doc_b: dict,
    label_a: str, label_b: str,
) -> None:
    """Apples-to-apples amount comparison between two documents.

    Order of preference: gross-gross > net-net > generic-generic.
    Documents at different levels (one only gross, the other only net) are skipped.
    """
    source_a = doc_a.get("_source", {}).get("file_name", label_a) if isinstance(doc_a.get("_source"), dict) else label_a
    source_b = doc_b.get("_source", {}).get("file_name", label_b) if isinstance(doc_b.get("_source"), dict) else label_b

    # Gross-gross
    gross_a = _get_gross_amount(doc_a)
    gross_b = _get_gross_amount(doc_b)
    if gross_a is not None and gross_b is not None:
        _compare_amounts(
            report, f"Gross total ({label_a} vs {label_b})",
            gross_a, gross_b, source_a, source_b,
        )
        return

    # Net-net
    net_a = _get_net_amount(doc_a)
    net_b = _get_net_amount(doc_b)
    if net_a is not None and net_b is not None:
        _compare_amounts(
            report, f"Net total ({label_a} vs {label_b})",
            net_a, net_b, source_a, source_b,
        )
        return

    # Generic-generic
    gen_a = _get_generic_amount(doc_a)
    gen_b = _get_generic_amount(doc_b)
    if gen_a is not None and gen_b is not None:
        _compare_amounts(
            report, f"Amount ({label_a} vs {label_b})",
            gen_a, gen_b, source_a, source_b,
        )


# ---------------------------------------------------------------------------
# Line-item comparison (4-pass matching)
# ---------------------------------------------------------------------------


def _get_item_quantity(item: dict) -> float | None:
    if not isinstance(item, dict):
        return None
    for field_name in ("quantity", "qty", "mennyiseg", "db", "darabszam", "menny"):
        val = coerce_number(item.get(field_name))
        if val is not None:
            return val
    return None


def _get_item_code(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    for field_name in ("item_code", "code", "sku", "article", "article_number",
                       "cikkszam", "cikk_szam"):
        val = item.get(field_name)
        if val:
            return str(val).lower().strip()
    return ""


def _get_item_description(item: dict) -> str:
    """Return the line-item description, multilingual fallback."""
    if not isinstance(item, dict):
        return ""
    for field_name in ("description", "name", "megnevezes"):
        val = item.get(field_name)
        if val:
            return str(val).lower().strip()
    return ""


def _fuzzy_match_strict(a: str, b: str) -> bool:
    """Strict fuzzy match: 0.8 word overlap + diff-token must not contain digits."""
    if not a or not b:
        return False
    if a == b:
        return True

    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return False

    intersection = len(words_a & words_b)
    max_size = max(len(words_a), len(words_b))
    overlap = intersection / max_size

    if overlap < 0.8:
        return False

    diff_words = words_a ^ words_b
    for word in diff_words:
        if any(c.isdigit() for c in word):
            return False

    return True


def _find_matching_item(name_a: str, code_a: str, items_b: list) -> dict | None:
    """4-pass line-item matching.

    Pass 1: item_code exact (strongest)
    Pass 2: exact name
    Pass 3: substring (one contains the other)
    Pass 4: strict fuzzy (0.8 overlap, diff token must not contain digits)
    """
    valid_b = [item for item in items_b if isinstance(item, dict)]

    # Pass 1: item_code
    if code_a:
        for item_b in valid_b:
            code_b = _get_item_code(item_b)
            if code_b and code_b == code_a:
                return item_b

    # Pass 2: exact name
    for item_b in valid_b:
        name_b = _get_item_description(item_b)
        if name_b and name_a == name_b:
            return item_b

    # Pass 3: substring
    for item_b in valid_b:
        name_b = _get_item_description(item_b)
        if not name_b:
            continue
        if name_a in name_b or name_b in name_a:
            return item_b

    # Pass 4: strict fuzzy
    for item_b in valid_b:
        name_b = _get_item_description(item_b)
        if not name_b:
            continue
        if _fuzzy_match_strict(name_a, name_b):
            return item_b

    return None


def _compare_items_between(
    report: ComparisonResult,
    doc_a: dict, doc_b: dict,
    label_a: str, label_b: str,
) -> None:
    """Pair line items between two documents and compare quantities.

    Missing item: missing/warning. Different qty: warning (<2 units) or critical (≥2 units).
    """
    items_a = doc_a.get("line_items") or doc_a.get("tetelek") or []
    items_b = doc_b.get("line_items") or doc_b.get("tetelek") or []

    if not items_a or not items_b:
        return

    source_a = doc_a.get("_source", {}).get("file_name", label_a) if isinstance(doc_a.get("_source"), dict) else label_a
    source_b = doc_b.get("_source", {}).get("file_name", label_b) if isinstance(doc_b.get("_source"), dict) else label_b

    for item_a in items_a:
        if not isinstance(item_a, dict):
            continue
        name_a_raw = item_a.get("description") or item_a.get("megnevezes", "")
        name_a = str(name_a_raw).lower().strip()
        if not name_a:
            continue

        qty_a = _get_item_quantity(item_a)
        code_a = _get_item_code(item_a)

        matched_item = _find_matching_item(name_a, code_a, items_b)

        if matched_item is None:
            report.add(MatchResult(
                status="missing",
                severity="warning",
                message=(
                    f"Item not found: '{name_a_raw}' present in {label_a} "
                    f"but missing from {label_b}"
                ),
                field_name="line_item",
                actual=name_a_raw,
                source_a=source_a,
                source_b=source_b,
            ))
            continue

        qty_b = _get_item_quantity(matched_item)
        if qty_a is None or qty_b is None:
            continue

        diff = abs(qty_a - qty_b)
        if diff < 0.01:
            report.add(MatchResult(
                status="match",
                severity="ok",
                message=f"Item matches: '{name_a_raw}' ({label_a} vs {label_b})",
                field_name="line_item",
            ))
        else:
            severity = "critical" if diff >= 2 else "warning"
            report.add(MatchResult(
                status="mismatch",
                severity=severity,
                message=(
                    f"Quantity discrepancy: '{name_a_raw}' — "
                    f"{label_a}: {qty_a:g}, {label_b}: {qty_b:g} "
                    f"(diff: {diff:g})"
                ),
                field_name="quantity",
                expected=qty_a,
                actual=qty_b,
                source_a=source_a,
                source_b=source_b,
            ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def three_way_match(
    invoice: dict, delivery_note: dict, purchase_order: dict,
) -> ComparisonResult:
    """Three-way matching (invoice + delivery note + purchase order).

    All three pairs:
      - invoice ↔ purchase order
      - invoice ↔ delivery note
      - delivery note ↔ purchase order

    + apples-to-apples amounts + 4-pass line-item matching + date logic.
    """
    report = ComparisonResult()

    # Amounts
    _compare_doc_amounts(report, invoice, purchase_order, "invoice", "purchase_order")
    _compare_doc_amounts(report, invoice, delivery_note, "invoice", "delivery_note")
    _compare_doc_amounts(report, delivery_note, purchase_order, "delivery_note", "purchase_order")

    # Line items
    _compare_items_between(report, invoice, purchase_order, "invoice", "purchase_order")
    _compare_items_between(report, invoice, delivery_note, "invoice", "delivery_note")
    _compare_items_between(report, delivery_note, purchase_order, "delivery_note", "purchase_order")

    # Date logic: invoice date should NOT precede the purchase order date
    inv_date = invoice.get("issue_date") or invoice.get("kiallitas_datuma")
    po_date = (purchase_order.get("date") or purchase_order.get("order_date")
               or purchase_order.get("megrendeles_datuma") or purchase_order.get("datum"))
    if (isinstance(inv_date, str) and isinstance(po_date, str)
            and len(inv_date) >= 10 and len(po_date) >= 10):
        if inv_date[:10] < po_date[:10]:
            report.add(MatchResult(
                status="mismatch",
                severity="warning",
                message=(
                    f"Invoice issue date ({inv_date[:10]}) is earlier than the "
                    f"purchase order date ({po_date[:10]})"
                ),
                field_name="date",
                expected=po_date,
                actual=inv_date,
            ))

    return report


def compare_two_documents(
    doc_a: dict, doc_b: dict, fields: list[str],
) -> ComparisonResult:
    """Compare specified fields between two documents.

    Numbers are compared numerically; strings exact-comparable.
    """
    report = ComparisonResult()

    for field_name in fields:
        if field_name.startswith("_"):
            continue

        val_a = doc_a.get(field_name)
        val_b = doc_b.get(field_name)

        if val_a is None and val_b is None:
            continue
        if val_a is None or val_b is None:
            report.add(MatchResult(
                status="missing",
                severity="warning",
                message=f"'{field_name}' missing from one of the documents",
                field_name=field_name,
                expected=val_a,
                actual=val_b,
            ))
            continue

        num_a = coerce_number(val_a)
        num_b = coerce_number(val_b)

        if num_a is not None and num_b is not None:
            _compare_amounts(
                report, field_name, num_a, num_b,
                doc_a.get("_source", {}).get("file_name", "A") if isinstance(doc_a.get("_source"), dict) else "A",
                doc_b.get("_source", {}).get("file_name", "B") if isinstance(doc_b.get("_source"), dict) else "B",
            )
        elif isinstance(val_a, (dict, list)) or isinstance(val_b, (dict, list)):
            continue
        elif str(val_a).strip().lower() != str(val_b).strip().lower():
            report.add(MatchResult(
                status="mismatch",
                severity="warning",
                message=f"'{field_name}' differs: '{val_a}' vs '{val_b}'",
                field_name=field_name,
                expected=val_a,
                actual=val_b,
            ))
        else:
            report.add(MatchResult(
                status="match",
                severity="ok",
                message=f"'{field_name}' matches",
                field_name=field_name,
            ))

    return report
