"""DDState — the DD assistant multi-agent supervisor graph state.

Topology: contract_filter → per_contract_summary → supervisor (LLM router) →
specialist agents (audit/legal/compliance/financial) → dd_synthesizer.

Specialist outputs (Pydantic structs) accumulate in the state; the supervisor
decides the next specialist or routes to the synthesizer based on them.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field

from graph.states.pipeline_state import (
    DDPortfolioReport,
    ProcessedDocument,
)


class DDContractSummary(BaseModel):
    """Per-contract Python-computed summary (input to the specialist agents)."""

    file_name: str
    contract_type: str = "unknown"
    parties: list[str] = Field(default_factory=list)
    effective_date: str | None = None
    expiry_date: str | None = None
    total_value: float | None = None
    currency: str = "USD"
    monthly_fee: float | None = None
    monthly_fee_currency: str = "USD"
    risk_level: str = "low"  # low | medium | high
    risk_elements: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)


class AuditFindings(BaseModel):
    """Audit specialist output."""
    pricing_anomalies: list[str] = Field(default_factory=list)
    overcharging: list[str] = Field(default_factory=list)
    note: str = ""


class LegalFindings(BaseModel):
    """Legal specialist output."""
    red_flags: list[str] = Field(default_factory=list)
    change_of_control: list[str] = Field(default_factory=list)
    non_compete: list[str] = Field(default_factory=list)
    note: str = ""


class ComplianceFindings(BaseModel):
    """Compliance specialist output."""
    gdpr_issues: list[str] = Field(default_factory=list)
    aml_alerts: list[str] = Field(default_factory=list)
    note: str = ""


class FinancialFindings(BaseModel):
    """Financial specialist output."""
    monthly_obligations: dict[str, float] = Field(default_factory=dict)
    expiring_soon: list[str] = Field(default_factory=list)
    high_value_contracts: list[str] = Field(default_factory=list)
    note: str = ""


class DDState(TypedDict, total=False):
    """The dd_graph state."""

    documents: list[ProcessedDocument]
    """Input: the full pipeline_graph documents list. contract_filter narrows it."""

    contracts: list[DDContractSummary]
    """Output of per_contract_summary (Python-deterministic)."""

    # Specialist outputs
    audit_findings: AuditFindings | None
    legal_findings: LegalFindings | None
    compliance_findings: ComplianceFindings | None
    financial_findings: FinancialFindings | None

    # Supervisor state
    call_history: Annotated[list[str], add]
    """Specialists already invoked (string list, append-only)."""

    next_specialist: str | None
    """Supervisor decision: 'audit' | 'legal' | 'compliance' | 'financial' | 'DONE'."""

    iteration_count: int

    # Final result
    dd_report: DDPortfolioReport | None
