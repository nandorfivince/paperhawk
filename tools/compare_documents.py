"""compare_documents tool — compare two (or auto-detected three) documents.

Behavior:
  1. If the two documents are part of an invoice + delivery_note + purchase_order
     triplet, automatically locates the third and runs ``three_way_match()``.
  2. Otherwise runs ``compare_two_documents()`` on the matching fields.

Uses ``validation/compare.py`` for the underlying 4-pass item matching,
apples-to-apples amount comparison, and tolerance tiers.
"""

from __future__ import annotations

from langchain_core.tools import tool

from tools.context import ChatToolContext
from validation.compare import compare_two_documents, three_way_match


def _format_report(result, header: str, sources: list[str]) -> str:
    """ComparisonResult → user-friendly text."""
    lines = [
        f"Total: {result.total_checks} checks, "
        f"{result.ok_count} OK, {result.warning_count} warnings, "
        f"{result.critical_count} critical, {result.missing_count} missing",
    ]
    for m in result.matches:
        if m.severity != "ok":
            lines.append(f"  [{m.severity.upper()}] {m.message}")
    if result.ok_count == result.total_checks:
        lines.append("  All checks passed.")

    body = "\n".join(lines)
    src = f"[Source: {', '.join(sources)}]"
    return f"{header}\n{body}\n\n{src}"


def build_compare_documents_tool(ctx: ChatToolContext):
    @tool
    def compare_documents(filename_a: str, filename_b: str) -> str:
        """Compare the extracted data of two documents.

        Compares amounts, line items, and dates and reports discrepancies.
        If the two documents are part of an invoice + delivery_note +
        purchase_order triplet, automatically locates the third document
        and runs three-way matching.

        Args:
            filename_a: filename of the first document
            filename_b: filename of the second document
        """
        pd_a = ctx.get_document(filename_a)
        pd_b = ctx.get_document(filename_b)
        if pd_a is None or pd_b is None:
            missing = []
            if pd_a is None:
                missing.append(filename_a)
            if pd_b is None:
                missing.append(filename_b)
            return f"Not found: {', '.join(missing)}. Available: {ctx.list_filenames()}"

        a_raw = pd_a.extracted.raw if pd_a.extracted else {}
        b_raw = pd_b.extracted.raw if pd_b.extracted else {}

        type_a = pd_a.classification.doc_type if pd_a.classification else ""
        type_b = pd_b.classification.doc_type if pd_b.classification else ""
        types_set = {type_a, type_b}

        # If two of {invoice, delivery_note, purchase_order}, find the third
        triplet_types = {"invoice", "delivery_note", "purchase_order"}
        if types_set <= triplet_types and len(types_set) == 2:
            needed = triplet_types - types_set
            needed_type = needed.pop()
            third_filenames = [
                fn for fn in ctx.list_filenames()
                if (pd := ctx.get_document(fn)) is not None
                and pd.classification is not None
                and pd.classification.doc_type == needed_type
            ]
            if third_filenames:
                pd_third = ctx.get_document(third_filenames[0])
                if pd_third is not None and pd_third.extracted is not None:
                    docs_by_type = {
                        type_a: a_raw,
                        type_b: b_raw,
                        needed_type: pd_third.extracted.raw,
                    }
                    result = three_way_match(
                        invoice=docs_by_type["invoice"],
                        delivery_note=docs_by_type["delivery_note"],
                        purchase_order=docs_by_type["purchase_order"],
                    )
                    return _format_report(
                        result,
                        header=(
                            f"Three-way matching: invoice + delivery_note + purchase_order "
                            f"({filename_a}, {filename_b}, {third_filenames[0]})"
                        ),
                        sources=[filename_a, filename_b, third_filenames[0]],
                    )

        # Otherwise plain 2-doc compare on union of fields
        all_fields = list(set(a_raw.keys()) | set(b_raw.keys()))
        all_fields = [f for f in all_fields if not f.startswith("_")]
        result = compare_two_documents(a_raw, b_raw, all_fields)
        return _format_report(
            result,
            header=f"Compare: {filename_a} vs {filename_b}",
            sources=[filename_a, filename_b],
        )

    return compare_documents
