"""compare_node — three-way matching: invoice + delivery note + purchase order.

The 535-line ``validation/compare.py`` implements the algorithm; this node
glues it to the graph state:

  1. Find the first three-way (invoice + delivery_note + purchase_order)
  2. Call ``validation.compare.three_way_match()``
  3. Wrap the result into a ``ComparisonReport`` Pydantic model in the parent state
  4. Convert critical mismatches to Risks (``kind="cross_check"``)
"""

from __future__ import annotations

from graph.states.pipeline_state import (
    ComparisonReport,
    PipelineState,
    ProcessedDocument,
    Risk,
)
from validation.compare import three_way_match


def _to_pydantic_report(
    result, invoice_name: str, delivery_name: str, order_name: str,
) -> ComparisonReport:
    """``ComparisonResult`` (dataclass) → ``ComparisonReport`` (Pydantic) conversion."""
    overall = "ok"
    if result.critical_count > 0:
        overall = "critical"
    elif result.warning_count > 0:
        overall = "warning"
    elif result.missing_count > 0:
        overall = "missing"

    summary = (
        f"3-way match: {invoice_name} / {delivery_name} / {order_name} -- "
        f"{result.total_checks} checks, {result.ok_count} ok, "
        f"{result.warning_count} warning, {result.critical_count} critical, "
        f"{result.missing_count} missing"
    )

    return ComparisonReport(
        invoice_filename=invoice_name,
        delivery_note_filename=delivery_name,
        purchase_order_filename=order_name,
        matches=[m.to_dict() for m in result.matches],
        total_checks=result.total_checks,
        ok_count=result.ok_count,
        warning_count=result.warning_count,
        critical_count=result.critical_count,
        missing_count=result.missing_count,
        overall_status=overall,
        summary=summary,
    )


async def compare_node(state: PipelineState) -> dict:
    """Three-way match on the first invoice + delivery_note + purchase_order trio."""
    documents: list[ProcessedDocument] = state.get("documents") or []
    invoices = [d for d in documents if d.classification and d.classification.doc_type == "invoice"]
    delivery_notes = [d for d in documents if d.classification and d.classification.doc_type == "delivery_note"]
    purchase_orders = [d for d in documents if d.classification and d.classification.doc_type == "purchase_order"]

    if not (invoices and delivery_notes and purchase_orders):
        return {"comparison": None}

    inv = invoices[0]
    dn = delivery_notes[0]
    po = purchase_orders[0]

    if not (inv.extracted and dn.extracted and po.extracted):
        return {"comparison": None}

    # 4-pass item matching + apples-to-apples amount comparison
    result = three_way_match(
        invoice=inv.extracted.raw,
        delivery_note=dn.extracted.raw,
        purchase_order=po.extracted.raw,
    )

    report = _to_pydantic_report(
        result,
        invoice_name=inv.ingested.file_name,
        delivery_name=dn.ingested.file_name,
        order_name=po.ingested.file_name,
    )

    # Convert critical / warning matches → Risks (kind="cross_check"), with
    # description-level dedup.
    risks: list[Risk] = []
    seen: set[str] = set()
    for m in result.matches:
        if m.severity == "ok":
            continue
        msg = m.message
        if msg in seen:
            continue
        seen.add(msg)
        if m.severity == "critical":
            risks.append(Risk(
                description=msg,
                severity="high",
                rationale="Critical discrepancy across documents",
                kind="cross_check",
                source_check_id="compare_three_way",
            ))
        elif m.severity == "warning":
            risks.append(Risk(
                description=msg,
                severity="medium",
                rationale="Warning-level discrepancy",
                kind="cross_check",
                source_check_id="compare_three_way",
            ))

    out: dict = {"comparison": report}
    if risks:
        out["risks"] = risks
    return out
