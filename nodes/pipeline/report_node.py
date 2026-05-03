"""report_node — report generation (Python structure + LLM exec summary).

Factory ``build_report_node(llm=None)``:
  * If ``llm`` is provided, the LLM produces a 2-4 sentence English exec summary
    from the top risks + package-level findings (``REPORT_SYSTEM_PROMPT`` +
    bureaucratic-jargon ban list).
  * If ``llm`` is None, ``executive_summary`` stays empty (backward-compatible).

``state["package_insights"]`` and ``state["dd_report"]`` (when present) are
folded into the report — the UI Report tab and the DOCX export render the
full sections from this dict.
"""

from __future__ import annotations

from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from graph.states.pipeline_state import (
    ComparisonReport,
    DDPortfolioReport,
    PackageInsights,
    PipelineState,
    ProcessedDocument,
    Risk,
)


# Manual-handling-time estimates (per doc_type, in minutes)
_MANUAL_MINUTES = {
    "invoice": 8,
    "delivery_note": 6,
    "purchase_order": 6,
    "contract": 35,
    "financial_report": 25,
    "other": 15,
}


REPORT_SYSTEM_PROMPT = """You write an audit report executive summary in English.

REQUIRED RULES:
1. Work only from the concrete numbers and data points provided. Do not fabricate anything.
2. Use the numbers VERBATIM — do not round, do not reinterpret.
3. Write in natural, concise English. No bureaucratic, robotic phrasing.
4. AVOID these words and phrases: "comprehensive", "thorough", "in-depth",
   "regulatory requirements", "recommended actions", "implement", "leveraging",
   "going forward" — these are filler.
5. Do not invent words. If unsure, choose a simpler word.
6. If there are no critical findings, say so plainly: "No critical discrepancies found."
7. 2-4 sentences, max 80 words. Be tight.
8. Plain prose. No headings, no bullet points."""


def _bucketize_risks(risks: list[Risk]) -> dict[str, list[dict]]:
    """Group risks by severity (UI rendering helper)."""
    out: dict[str, list[dict]] = {"high": [], "medium": [], "low": [], "info": []}
    for r in risks:
        sev = r.severity.lower()
        bucket = sev if sev in out else "low"
        out[bucket].append(r.model_dump())
    return out


def _evidence_for(doc_type: str) -> int:
    from domain_checks import get_evidence_score
    return get_evidence_score(doc_type)


def _build_summary_prompt(
    documents: list[ProcessedDocument],
    risks: list[Risk],
    comparison: ComparisonReport | None,
    package_insights: PackageInsights | None,
) -> str:
    """Structured line-based prompt so the LLM only uses the provided values."""
    doc_count = len(documents)
    high = [r for r in risks if r.severity == "high"]
    medium = [r for r in risks if r.severity == "medium"]
    top_risks = [r.description for r in high[:3]]
    top_warnings = [r.description for r in medium[:3]]

    parts = [
        "Audit results — write a 2-4 sentence English executive summary from these.",
        "Use the numbers EXACTLY; do not change them.",
        "",
        f"Documents processed: {doc_count}",
    ]

    if comparison:
        ok = sum(1 for m in comparison.matches if m.get("severity") == "ok")
        warn = sum(1 for m in comparison.matches if m.get("severity") == "warning")
        crit = sum(1 for m in comparison.matches if m.get("severity") == "critical")
        parts.append(
            f"Cross-document checks: {ok} ok, "
            f"{warn} warnings, {crit} critical discrepancies"
        )

    parts.append(f"Identified risks: {len(high)} high, {len(medium)} medium")

    if top_risks:
        parts.append("")
        parts.append("Top high-severity risks:")
        for r in top_risks:
            parts.append(f"- {r}")
    if top_warnings:
        parts.append("")
        parts.append("Top warnings:")
        for r in top_warnings:
            parts.append(f"- {r}")

    # Package-level findings
    if package_insights is not None and package_insights.findings:
        top_pkg_high = [
            f.get("description") or f.get("leiras", "")
            for f in package_insights.findings
            if (f.get("severity") or f.get("sulyossag") or "").lower() == "high"
            or (f.get("severity") or f.get("sulyossag") or "").lower() == "magas"
        ][:3]
        top_pkg_med = [
            f.get("description") or f.get("leiras", "")
            for f in package_insights.findings
            if (f.get("severity") or f.get("sulyossag") or "").lower() in ("medium", "kozepes", "közepes")
        ][:2]
        if top_pkg_high or top_pkg_med:
            parts.append("")
            parts.append("Package-level findings (cross-doc):")
            for r in top_pkg_high:
                parts.append(f"- [HIGH] {r}")
            for r in top_pkg_med:
                parts.append(f"- [MEDIUM] {r}")

    return "\n".join(parts)


def build_report_node(llm=None):
    """Factory: capture ``llm`` in a closure for the exec summary call.

    Args:
        llm: optional BaseChatModel-like Runnable. If provided, it generates a
             2-4 sentence English executive summary from the structured input.
             If None, the summary stays empty.
    """

    async def report_node(state: PipelineState) -> dict:
        documents: list[ProcessedDocument] = state.get("documents") or []
        risks: list[Risk] = state.get("risks") or []
        comparison: ComparisonReport | None = state.get("comparison")
        package_insights: PackageInsights | None = state.get("package_insights")
        dd_report: DDPortfolioReport | None = state.get("dd_report")
        processing_seconds = state.get("processing_seconds") or 0.0

        # Per-doc info + manual_total computation
        docs_info = []
        manual_total = 0
        for d in documents:
            if d.ingested is None:
                continue
            doc_type = d.classification.doc_type if d.classification else "other"
            manual = _MANUAL_MINUTES.get(doc_type, 15)
            manual_total += manual
            docs_info.append({
                "file": d.ingested.file_name,
                "type": d.classification.doc_type_display if d.classification else "Other",
                "extracted_fields": (
                    len(d.extracted.raw) if d.extracted and isinstance(d.extracted.raw, dict) else 0
                ),
                "evidence_score": _evidence_for(doc_type),
            })

        speedup = (manual_total * 60.0) / processing_seconds if processing_seconds > 0 else 0.0

        report: dict = {
            "generated_at": datetime.now().isoformat(),
            "document_count": len(documents),
            "performance": {
                "processing_seconds": round(processing_seconds, 2),
                "documents": len(documents),
                "manual_estimate_minutes": manual_total,
                "speedup": round(speedup, 1),
            },
            "documents": docs_info,
            "risks": _bucketize_risks(risks),
            "comparison": comparison.model_dump() if comparison else None,
            "executive_summary": "",
            # Opt-in sections — populated only when demo flow or DD tab ran
            "package_insights": None,
            "dd_analysis": None,
        }

        # Package-level analysis integration
        if package_insights is not None:
            report["package_insights"] = {
                "executive_summary": package_insights.executive_summary or "",
                "findings": list(package_insights.findings or []),
                "key_observations": list(package_insights.key_observations or []),
                "package_type": package_insights.package_type or "general",
            }

        # DD analysis integration
        if dd_report is not None and dd_report.executive_summary:
            report["dd_analysis"] = {
                "executive_summary": dd_report.executive_summary,
                "top_red_flags": list(dd_report.top_red_flags or []),
                "contracts": list(dd_report.contracts or []),
                "total_monthly_obligations": dict(dd_report.total_monthly_obligations or {}),
                "high_risk_contracts": list(dd_report.high_risk_contracts or []),
                "expiring_soon": list(dd_report.expiring_soon or []),
            }

        # LLM exec summary — when llm is provided
        if llm is not None:
            try:
                summary_prompt = _build_summary_prompt(
                    documents, risks, comparison, package_insights,
                )
                response = await llm.ainvoke([
                    SystemMessage(content=REPORT_SYSTEM_PROMPT),
                    HumanMessage(content=summary_prompt),
                ])
                content = response.content
                if isinstance(content, str):
                    report["executive_summary"] = content.strip()
                elif isinstance(content, list):
                    text_parts = [
                        part.get("text", "") for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    ]
                    report["executive_summary"] = "\n".join(t for t in text_parts if t).strip()
            except Exception:
                # Empty summary on error — the rest of the report is still useful
                report["executive_summary"] = ""

        return {"report": report}

    return report_node


# Backward-compat: keep the legacy report_node API (llm=None default)
async def report_node(state: PipelineState) -> dict:
    """Backward-compat wrapper — runs build_report_node without an LLM."""
    inner = build_report_node(llm=None)
    return await inner(state)
