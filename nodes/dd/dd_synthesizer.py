"""dd_synthesizer — build the DD portfolio Pydantic report with an LLM exec summary.

  1. The 4 specialists (audit/legal/compliance/financial) have already run; their
     outputs live in the state (``audit_findings``, etc.).
  2. The per-contract Python summary (``contracts``) has also been built.
  3. Aggregate monthly obligations + expiring_soon come from ``financial_findings``.
  4. **One LLM call** with structured output: executive_summary +
     top_red_flags (3-7 items) + contract_risk_ratings (per-contract rating + rationale).
  5. The LLM rating overrides the per-contract Python-computed ``risk_level``.
  6. On error: a Python fallback executive summary.

Factory ``build_dd_synthesizer(llm)`` captures the LLM Runnable in a closure.
"""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from graph.states.dd_state import DDState
from graph.states.pipeline_state import DDPortfolioReport


def _normalize_string_list(raw) -> list[str]:
    """Sometimes the LLM emits ``<item>...</item>`` markup for a JSON list[str].

    We normalize before pydantic validates so ``top_red_flags`` and similar
    list fields parse cleanly even when the LLM wraps items.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if item is not None and str(item).strip()]
    if isinstance(raw, str):
        # 1. Try <item>...</item> XML-like parsing
        items = re.findall(r"<item>\s*(.*?)\s*</item>", raw, flags=re.DOTALL)
        if items:
            return [it.strip() for it in items if it.strip()]
        # 2. Line-by-line splitting
        lines = [line.strip() for line in raw.split("\n") if line.strip()]
        if len(lines) > 1:
            cleaned = []
            for line in lines:
                line = re.sub(r"^[\-\*•]\s+", "", line)
                line = re.sub(r"^\d+[\.\)]\s+", "", line)
                if line:
                    cleaned.append(line)
            return cleaned
        # 3. Fallback
        return [raw.strip()] if raw.strip() else []
    return []


DD_SUMMARY_SYSTEM_PROMPT = """You are a Due Diligence (DD) expert in the context of an
acquisition transaction. Based on the contract portfolio, you produce an
executive summary of transaction risks.

REQUIREMENTS:
1. Rely ONLY on FACTS that appear in the documents. Do not speculate.
2. Focus on DD-relevant risks:
   - Imminent expirations (6-12 months)
   - Change-of-control clauses (termination on owner change)
   - High monthly obligations
   - GDPR / data-protection issues
   - Excessively long termination notice periods
   - Unusual penalty clauses
3. Rank: most severe risks first.
4. English, concise, professional tone.
5. Avoid filler ("worth examining", "advisable to review") — give concrete
   observations, e.g. "The DataLab contract is +67% pricier under the NDA — a red flag".

Respond strictly per the JSON schema."""


class _ContractRiskRating(BaseModel):
    file_name: str
    risk_level: Literal["low", "medium", "high"] = "low"
    rationale: str = ""


class _DDReportLLM(BaseModel):
    """Structured LLM output for the DD synthesis."""
    executive_summary: str = ""
    top_red_flags: list[str] = Field(default_factory=list)
    contract_risk_ratings: list[_ContractRiskRating] = Field(default_factory=list)

    @field_validator("top_red_flags", mode="before")
    @classmethod
    def _normalize_red_flags(cls, v):
        return _normalize_string_list(v)


def _build_summary_prompt(state: DDState) -> str:
    """Structured input prompt."""
    contracts = state.get("contracts") or []
    parts = [
        "Contract portfolio for DD analysis:",
        "",
    ]
    for i, s in enumerate(contracts, start=1):
        parts.append(f"--- Contract {i}: {s.file_name} ---")
        parts.append(f"Type: {s.contract_type}")
        parts.append(f"Parties: {', '.join(s.parties)}")
        parts.append(f"Effective: {s.effective_date} -- expires: {s.expiry_date}")
        if s.total_value:
            parts.append(f"Value: {s.total_value} {s.currency}")
        if s.risk_elements:
            parts.append("Risk elements:")
            for k in s.risk_elements[:5]:
                parts.append(f"  - {k}")
        if s.red_flags:
            parts.append("Red flags:")
            for p in s.red_flags[:3]:
                parts.append(f"  - {p}")
        parts.append("")

    # Append the 4 specialists' findings to enrich the exec summary
    audit = state.get("audit_findings")
    legal = state.get("legal_findings")
    compliance = state.get("compliance_findings")
    financial = state.get("financial_findings")

    if any([audit, legal, compliance, financial]):
        parts.append("--- Specialist analyses ---")
        if audit:
            if audit.pricing_anomalies:
                parts.append(f"Audit (pricing anomalies): {', '.join(audit.pricing_anomalies[:3])}")
            if audit.overcharging:
                parts.append(f"Audit (overcharging): {', '.join(audit.overcharging[:3])}")
        if legal:
            if legal.red_flags:
                parts.append(f"Legal (red flags): {', '.join(legal.red_flags[:3])}")
            if legal.change_of_control:
                parts.append(f"Legal (CoC): {', '.join(legal.change_of_control[:2])}")
            if legal.non_compete:
                parts.append(f"Legal (non-compete): {', '.join(legal.non_compete[:2])}")
        if compliance:
            if compliance.gdpr_issues:
                parts.append(f"Compliance (GDPR): {', '.join(compliance.gdpr_issues[:3])}")
            if compliance.aml_alerts:
                parts.append(f"Compliance (AML): {', '.join(compliance.aml_alerts[:2])}")
        if financial:
            if financial.expiring_soon:
                parts.append(f"Financial (expiring soon): {', '.join(financial.expiring_soon[:3])}")
            if financial.high_value_contracts:
                parts.append(f"Financial (high value): {', '.join(financial.high_value_contracts[:3])}")
        parts.append("")

    parts.append(
        "Produce a DD executive summary, a top red flags list, and a per-contract "
        "risk rating with rationale."
    )
    return "\n".join(parts)


def build_dd_synthesizer(llm=None):
    """Factory: dd_synthesizer node that captures the LLM."""

    async def dd_synthesizer(state: DDState) -> dict:
        contracts = state.get("contracts") or []
        audit = state.get("audit_findings")
        legal = state.get("legal_findings")
        compliance = state.get("compliance_findings")
        financial = state.get("financial_findings")

        # Aggregated metrics (Python-deterministic)
        monthly_obligations = financial.monthly_obligations if financial else {}
        expiring_soon = list(financial.expiring_soon) if financial else []

        # LLM call (if llm is provided)
        executive_summary = ""
        top_red_flags: list[str] = []
        rating_map: dict[str, tuple[str, str]] = {}

        if llm is not None and contracts:
            try:
                structured_llm = llm.with_structured_output(_DDReportLLM)
                response: _DDReportLLM = await structured_llm.ainvoke([
                    SystemMessage(content=DD_SUMMARY_SYSTEM_PROMPT),
                    HumanMessage(content=_build_summary_prompt(state)),
                ])
                executive_summary = response.executive_summary or ""
                top_red_flags = list(response.top_red_flags or [])
                # Per-contract rating mapping (file_name → (risk_level, rationale))
                for r in response.contract_risk_ratings:
                    if r.file_name:
                        rating_map[r.file_name] = (r.risk_level, r.rationale)

                # LLM rating overrides Python-computed level
                for c in contracts:
                    if c.file_name in rating_map:
                        new_level, rationale = rating_map[c.file_name]
                        if new_level in ("low", "medium", "high"):
                            c.risk_level = new_level
                            if rationale:
                                c.red_flags.insert(0, f"DD assessment: {rationale}")
            except Exception as exc:
                # LLM error: Python fallback summary
                high_risk_count = sum(1 for c in contracts if c.risk_level == "high")
                executive_summary = (
                    f"LLM-based DD summary failed ({type(exc).__name__}). "
                    f"Python-based metrics: "
                    f"{len(contracts)} contracts, {high_risk_count} high-risk, "
                    f"{len(expiring_soon)} expiring soon."
                )

        # If no LLM or no contracts: minimal Python fallback
        if not executive_summary:
            high_risk_count = sum(1 for c in contracts if c.risk_level == "high")
            if not contracts:
                executive_summary = (
                    "No contract-type documents are present in the input. "
                    "Upload at least one contract for DD analysis."
                )
            else:
                executive_summary = (
                    f"DD portfolio: {len(contracts)} contracts, "
                    f"{high_risk_count} high-risk, "
                    f"{len(expiring_soon)} expiring soon."
                )

        # High risk list per the (LLM-overridden) per-contract rating
        high_risk_contracts = [c.file_name for c in contracts if c.risk_level == "high"]

        # Top red flags fallback: if the LLM didn't provide them, gather from Python red flags
        if not top_red_flags:
            for c in contracts:
                top_red_flags.extend(c.red_flags[:2])
            top_red_flags = top_red_flags[:7]

        # Specialist outputs (debug)
        specialist_outputs = {}
        if audit:
            specialist_outputs["audit"] = audit.model_dump()
        if legal:
            specialist_outputs["legal"] = legal.model_dump()
        if compliance:
            specialist_outputs["compliance"] = compliance.model_dump()
        if financial:
            specialist_outputs["financial"] = financial.model_dump()

        report = DDPortfolioReport(
            contract_count=len(contracts),
            contracts=[c.model_dump() for c in contracts],
            total_monthly_obligations=dict(monthly_obligations),
            expiring_soon=expiring_soon,
            high_risk_contracts=high_risk_contracts,
            top_red_flags=top_red_flags,
            executive_summary=executive_summary,
            specialist_outputs=specialist_outputs,
        )

        return {"dd_report": report}

    return dd_synthesizer


# Backward-compat
async def dd_synthesizer(state: DDState) -> dict:
    """Backward-compat wrapper — runs build_dd_synthesizer without an LLM."""
    inner = build_dd_synthesizer(llm=None)
    return await inner(state)
