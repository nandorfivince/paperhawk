"""DD specialist agents: Audit, Legal, Compliance, Financial.

Dummy implementation: Python-deterministic aggregates over ``contracts``.
The Phase 7+ vLLM/Qwen path will replace these with ``with_structured_output``
Pydantic structs (this is the LangGraph-native form, ready for the LLM swap).
"""

from __future__ import annotations

from graph.states.dd_state import (
    AuditFindings,
    ComplianceFindings,
    DDState,
    FinancialFindings,
    LegalFindings,
)
from utils.dates import is_expiring_soon


# ---------------------------------------------------------------------------
# Audit — financial anomalies, price changes
# ---------------------------------------------------------------------------


async def audit_specialist(state: DDState) -> dict:
    contracts = state.get("contracts") or []
    pricing_anomalies: list[str] = []
    overcharging: list[str] = []

    # Heuristic: 2+ contracts with the same parties → if values differ > 30% → anomaly
    if len(contracts) >= 2:
        groups: dict[tuple, list] = {}
        for c in contracts:
            key = tuple(sorted(c.parties))
            groups.setdefault(key, []).append(c)
        for parties, group in groups.items():
            if len(group) < 2:
                continue
            values = [c.total_value for c in group if c.total_value]
            if len(values) >= 2 and min(values) > 0:
                ratio = max(values) / min(values)
                if ratio > 1.3:
                    pricing_anomalies.append(
                        f"Between parties {list(parties)}: value ratio {ratio:.1f}x "
                        f"(min: {min(values):.0f}, max: {max(values):.0f})"
                    )

    findings = AuditFindings(
        pricing_anomalies=pricing_anomalies,
        overcharging=overcharging,
        note=f"{len(contracts)} contracts analyzed from an audit perspective.",
    )
    return {
        "audit_findings": findings,
        "call_history": ["audit"],
    }


# ---------------------------------------------------------------------------
# Legal — clauses, change-of-control, non-compete, penalty
# ---------------------------------------------------------------------------


async def legal_specialist(state: DDState) -> dict:
    contracts = state.get("contracts") or []
    red_flags: list[str] = []
    coc_list: list[str] = []
    nc_list: list[str] = []

    for c in contracts:
        for flag in c.red_flags:
            red_flags.append(f"{c.file_name}: {flag}")
            if "change-of-control" in flag.lower():
                coc_list.append(c.file_name)
            if "non-compete" in flag.lower() or "versenytilalom" in flag.lower():
                nc_list.append(c.file_name)

    findings = LegalFindings(
        red_flags=red_flags[:7],  # top-7
        change_of_control=coc_list,
        non_compete=nc_list,
        note=f"{len(contracts)} contracts analyzed from a legal perspective; {len(red_flags)} red flags.",
    )
    return {
        "legal_findings": findings,
        "call_history": ["legal"],
    }


# ---------------------------------------------------------------------------
# Compliance — GDPR, AML
# ---------------------------------------------------------------------------


async def compliance_specialist(state: DDState) -> dict:
    documents = state.get("documents") or []  # only contracts here, after contract_filter
    gdpr_issues: list[str] = []
    aml_alerts: list[str] = []

    for d in documents:
        if d.ingested is None:
            continue
        for r in d.risks:
            if r.source_check_id == "check_08_gdpr_28":
                gdpr_issues.append(f"{d.ingested.file_name}: {r.description}")
            elif r.source_check_id == "check_13_aml_sanctions":
                aml_alerts.append(f"{d.ingested.file_name}: {r.description}")

    findings = ComplianceFindings(
        gdpr_issues=gdpr_issues[:5],
        aml_alerts=aml_alerts[:5],
        note=f"{len(gdpr_issues)} GDPR + {len(aml_alerts)} AML signals.",
    )
    return {
        "compliance_findings": findings,
        "call_history": ["compliance"],
    }


# ---------------------------------------------------------------------------
# Financial — monthly obligations, expirations
# ---------------------------------------------------------------------------


async def financial_specialist(state: DDState) -> dict:
    contracts = state.get("contracts") or []
    monthly_obligations: dict[str, float] = {}
    expiring_soon: list[str] = []
    high_value: list[str] = []

    for c in contracts:
        if c.monthly_fee and c.monthly_fee > 0:
            currency = c.monthly_fee_currency or "USD"
            monthly_obligations[currency] = monthly_obligations.get(currency, 0.0) + c.monthly_fee
        if is_expiring_soon(c.expiry_date, months=12):
            expiring_soon.append(c.file_name)
        if c.total_value and c.total_value >= 10_000_000:
            high_value.append(c.file_name)

    findings = FinancialFindings(
        monthly_obligations=monthly_obligations,
        expiring_soon=expiring_soon,
        high_value_contracts=high_value,
        note=f"{len(contracts)} contracts analyzed from a financial perspective.",
    )
    return {
        "financial_findings": findings,
        "call_history": ["financial"],
    }
