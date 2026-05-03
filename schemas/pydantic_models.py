"""Pydantic v2 mirror models for the JSON schemas.

Purpose: runtime field validation in the extract_subgraph
(``InvoiceModel.model_validate(...)``) and type-strong downstream nodes (the
risk_subgraph receives Pydantic-typed data).

JSON schema remains the source of truth for the LLM ``with_structured_output()``
calls — the Pydantic mirror is for VALIDATION ONLY, it does not replace the
JSON schema.

The ``_quotes`` and ``_confidence`` fields are aliased in the JSON
(``"alias_": ...``); we keep the aliases here too so the JSON parses cleanly.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Common sub-models
# ---------------------------------------------------------------------------


class Party(BaseModel):
    """A party (issuer, customer, contracting party)."""

    name: str | None = None
    tax_id: str | None = None
    address: str | None = None
    role: str | None = None
    contact: str | None = None


class SourceRef(BaseModel):
    file_name: str | None = None
    page_number: int | None = None


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------


class InvoiceItem(BaseModel):
    item_code: str | None = None
    description: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_price_net: float | None = None
    vat_rate: float | None = None
    total_net: float | None = None
    total_vat: float | None = None
    total_gross: float | None = None


class InvoiceModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    invoice_number: str | None = None
    issue_date: str | None = None
    fulfillment_date: str | None = None
    payment_due_date: str | None = None
    payment_method: str | None = None
    currency: str = "USD"
    issuer: Party | None = None
    customer: Party | None = None
    line_items: list[InvoiceItem] = Field(default_factory=list)
    total_net: float | None = None
    total_vat: float | None = None
    total_gross: float | None = None
    quotes: list[str] = Field(default_factory=list, alias="_quotes")
    confidence: dict = Field(default_factory=dict, alias="_confidence")
    source: SourceRef | None = Field(default=None, alias="_source")


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


class ContractPenalty(BaseModel):
    amount: float | None = None
    condition: str | None = None


class AutoRenewal(BaseModel):
    enabled: bool = False
    condition: str | None = None


class KeyClause(BaseModel):
    name: str
    content: str
    risk_level: str = "low"  # low | medium | high


class ContractModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    contract_type: str | None = Field(
        None,
        description="The type of contract, e.g. 'NDA', 'service', 'works contract', "
                    "'lease', 'MSA', 'rental', 'IT framework agreement'. If the title "
                    "of the contract ('NON-DISCLOSURE AGREEMENT', 'LEASE AGREEMENT', etc.) "
                    "or the first paragraph contains it, fill it in.",
    )
    parties: list[Party] = Field(default_factory=list)
    effective_date: str | None = Field(
        None,
        description="Effective date of the contract. If 'Effective date', "
                    "'Vertragsbeginn', 'Hatály kezdete' appears in the text, "
                    "fill in ISO 8601 (YYYY-MM-DD) format.",
    )
    expiry_date: str | None = Field(
        None,
        description="Expiration date of the contract. If 'Expiry date', "
                    "'Vertragsende', 'Lejárat' appears, fill it in.",
    )
    total_value: float | None = None
    currency: str = "USD"
    monthly_fee: float | None = None
    monthly_fee_currency: str = "USD"
    termination_terms: str | None = Field(
        None,
        description="Textual summary of the termination conditions. MANDATORY to "
                    "fill in if the contract anywhere mentions 'Termination', "
                    "'Felmondás', 'Megszűnés', 'Kündigung' — whether 30/60/90 day "
                    "notice or immediate termination for material breach. ONLY null "
                    "if the contract has NO termination clause whatsoever.",
    )
    termination_period_days: int | None = Field(
        None,
        description="Number of days for the termination notice period (e.g. 30, 60, 90). Numeric.",
    )
    penalty: ContractPenalty | None = Field(
        None,
        description="Penalty / liquidated damages clause if mentioned. Fill in if "
                    "'Penalty', 'Liquidated damages', 'Kötbér', 'Vertragsstrafe' or a "
                    "concrete amount/condition is referenced.",
    )
    confidentiality_clause: bool | None = Field(
        None,
        description="True if the contract contains a 'Confidentiality', 'NDA', "
                    "'Titoktartás' clause as a separate section or by reference.",
    )
    governing_law: str | None = Field(
        None,
        description="Applicable law. MANDATORY to fill in if 'Governing law', "
                    "'Applicable law', 'Anwendbares Recht', 'Irányadó jog', "
                    "'Hungarian law', 'BGB' is referenced. E.g.: 'Hungarian Civil Code', "
                    "'Hungarian and German BGB'.",
    )
    auto_renewal: AutoRenewal | None = Field(
        None,
        description="Auto-renewal clause. Fill in if 'auto-renewal', 'evergreen "
                    "clause', 'automatically renewed', 'automatische Verlängerung' is mentioned.",
    )
    change_of_control: bool | None = Field(
        None,
        description="True if the contract contains a 'change-of-control', "
                    "'change of control', 'kontroll-változás', 'termination on "
                    "ownership change' clause.",
    )
    non_compete: bool | None = Field(
        None,
        description="True if the contract contains a 'non-compete', "
                    "'versenytilalom', 'Wettbewerbsverbot' clause.",
    )
    key_clauses: list[KeyClause] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list, alias="_quotes")
    confidence: dict = Field(default_factory=dict, alias="_confidence")
    source: SourceRef | None = Field(default=None, alias="_source")


# ---------------------------------------------------------------------------
# Delivery Note
# ---------------------------------------------------------------------------


class DeliveryItem(BaseModel):
    item_code: str | None = None
    description: str | None = None
    quantity: float | None = None
    unit: str | None = None


class DeliveryNoteModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    document_number: str | None = None
    issue_date: str | None = None
    delivery_date: str | None = None
    purchase_order_reference: str | None = None
    supplier: Party | None = None
    customer: Party | None = None
    line_items: list[DeliveryItem] = Field(default_factory=list)
    notes: str | None = None
    quotes: list[str] = Field(default_factory=list, alias="_quotes")
    confidence: dict = Field(default_factory=dict, alias="_confidence")
    source: SourceRef | None = Field(default=None, alias="_source")


# ---------------------------------------------------------------------------
# Purchase Order
# ---------------------------------------------------------------------------


class PurchaseOrderItem(BaseModel):
    item_code: str | None = None
    description: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_price_net: float | None = None
    total_net: float | None = None


class PurchaseOrderModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    document_number: str | None = None
    date: str | None = None
    delivery_due_date: str | None = None
    payment_due_date: str | None = None
    supplier: Party | None = None
    customer: Party | None = None
    line_items: list[PurchaseOrderItem] = Field(default_factory=list)
    total_net: float | None = None
    total_vat: float | None = None
    total_gross: float | None = None
    quotes: list[str] = Field(default_factory=list, alias="_quotes")
    confidence: dict = Field(default_factory=dict, alias="_confidence")
    source: SourceRef | None = Field(default=None, alias="_source")


# ---------------------------------------------------------------------------
# Financial Report
# ---------------------------------------------------------------------------


class FinancialLineItem(BaseModel):
    description: str
    value: float | None = None
    value_prior_period: float | None = None


class FinancialReportModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    report_type: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    company_name: str | None = None
    company_tax_id: str | None = None
    currency: str = "USD"
    accounting_standard: str | None = None
    """One of: 'IFRS' | 'US-GAAP' | 'HU-GAAP' | 'DE-HGB' | None."""
    line_items: list[FinancialLineItem] = Field(default_factory=list)
    revenue: float | None = None
    operating_income: float | None = None
    pretax_income: float | None = None
    tax: float | None = None
    net_income: float | None = None
    quotes: list[str] = Field(default_factory=list, alias="_quotes")
    confidence: dict = Field(default_factory=dict, alias="_confidence")
    source: SourceRef | None = Field(default=None, alias="_source")


# ---------------------------------------------------------------------------
# Universal — optional, because flatten_universal maps to the typed schemas
# ---------------------------------------------------------------------------


class UniversalDates(BaseModel):
    issue: str | None = None
    fulfillment: str | None = None
    payment_due: str | None = None
    effective: str | None = None
    expiry: str | None = None
    signature: str | None = None
    other_dates: list[dict] = Field(default_factory=list)


class UniversalAmounts(BaseModel):
    total_net: float | None = None
    total_vat: float | None = None
    total_gross: float | None = None
    currency: str = "USD"
    vat_rate: float | None = None


class UniversalContractElements(BaseModel):
    contract_type: str | None = None
    termination_terms: str | None = None
    penalty: dict | None = None
    confidentiality_clause: bool | None = None
    governing_law: str | None = None
    key_clauses: list[KeyClause] = Field(default_factory=list)


class UniversalModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    document_type: str | None = None
    document_language: str = "en"
    document_number: str | None = None
    parties: list[Party] = Field(default_factory=list)
    dates: UniversalDates | None = None
    amounts: UniversalAmounts | None = None
    line_items: list[InvoiceItem] = Field(default_factory=list)
    contract_elements: UniversalContractElements | None = None
    risk_elements: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list, alias="_quotes")
    confidence: dict = Field(default_factory=dict, alias="_confidence")
    source: SourceRef | None = Field(default=None, alias="_source")


# ---------------------------------------------------------------------------
# Schema selection
# ---------------------------------------------------------------------------


def pydantic_for(doc_type: str) -> type[BaseModel]:
    """Return the Pydantic model class for the given doc_type."""
    mapping = {
        "invoice": InvoiceModel,
        "delivery_note": DeliveryNoteModel,
        "purchase_order": PurchaseOrderModel,
        "contract": ContractModel,
        "financial_report": FinancialReportModel,
        "other": UniversalModel,
    }
    return mapping.get(doc_type, UniversalModel)
