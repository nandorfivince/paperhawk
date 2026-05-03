"""Domain check registry — 14 deterministic rules with a unified API.

The ``risk_subgraph`` uses the Send API to fan out (per-doc, per-applicable-check)
pairs; each Send invokes an ``apply_domain_check`` node which looks up and runs
the check from this registry.

Two SEPARATE entry points (skipped from dispatch via the ``SKIP_FROM_DISPATCH`` set):
  * ``check_06_evidence_score``: per-doc info, called directly after classification
  * ``check_12_duplicate_invoice``: package-level O(n²), called from a separate
    node in the ``risk_subgraph``
"""

from __future__ import annotations

from domain_checks.base import DomainCheck, is_empty, make_risk
from domain_checks.check_01_invoice_mandatory import InvoiceMandatoryCheck
from domain_checks.check_02_tax_cdv import TaxCDVCheck, compute_cdv, validate_tax_cdv
from domain_checks.check_03_contract_completeness import ContractCompletenessCheck
from domain_checks.check_04_proportionality import ProportionalityCheck
from domain_checks.check_05_rounded_amounts import RoundedAmountsCheck
from domain_checks.check_06_evidence_score import EvidenceScoreCheck, get_evidence_score
from domain_checks.check_07_materiality import MaterialityCheck
from domain_checks.check_08_gdpr_28 import GDPR28Check
from domain_checks.check_09_dd_red_flags import DDRedFlagsCheck
from domain_checks.check_10_incoterms import INCOTERMS_2020, IncotermsCheck
from domain_checks.check_11_ifrs_har import IFRSHARCheck
from domain_checks.check_12_duplicate_invoice import (
    DuplicateInvoiceCheck,
    check_duplicate_invoices,
)
from domain_checks.check_13_aml_sanctions import AMLSanctionsCheck
from domain_checks.check_14_contract_dates import ContractDatesCheck


# Unified registry of all 14 checks. The risk_subgraph's domain_dispatch_node
# iterates this list and Send-fans-out the (doc, check) pairs. Skipped
# checks (06: evidence score, 12: duplicate detection) are called via separate
# entry points.
CHECK_REGISTRY: list[DomainCheck] = [
    InvoiceMandatoryCheck(),       # 01: HU VAT Act §169 (HU jurisdiction)
    TaxCDVCheck(),                 # 02: HU Tax Procedure Act §22 mod-11 (HU jurisdiction)
    ContractCompletenessCheck(),   # 03: Universal contract completeness
    ProportionalityCheck(),        # 04: Universal contract proportionality
    RoundedAmountsCheck(),         # 05: ISA 240
    EvidenceScoreCheck(),          # 06: ISA 500 (separate entry point)
    MaterialityCheck(),            # 07: ISA 320
    GDPR28Check(),                 # 08: GDPR Article 28
    DDRedFlagsCheck(),             # 09: M&A DD best practice
    IncotermsCheck(),              # 10: Incoterms 2020
    IFRSHARCheck(),                # 11: IFRS / national GAAP comparison
    DuplicateInvoiceCheck(),       # 12: ISA 240 package-level (separate entry point)
    AMLSanctionsCheck(),           # 13: AML / Sanctions screening
    ContractDatesCheck(),          # 14: Contract date best practice
]

# Skipped check_ids (NOT Send-fanned out; called by separate nodes)
SKIP_FROM_DISPATCH = {"check_06_evidence_score", "check_12_duplicate_invoice"}


def get_check(check_id: str) -> DomainCheck | None:
    """Look up a check by check_id."""
    for c in CHECK_REGISTRY:
        if c.check_id == check_id:
            return c
    return None


def get_applied_standards(risks) -> list[str]:
    """Return the list of standards/regulations actually applied to the package.

    The UI footer only shows standards that had at least one risk finding,
    OR that always run (e.g. ISA 500 evidence score).
    """
    # Standards that always run (universal, every jurisdiction)
    always = {"ISA 500"}

    # Standards referenced in actual risks (i.e. triggered)
    from_risks: set[str] = set()
    for r in risks or []:
        if hasattr(r, "regulation"):
            reg = r.regulation
        elif isinstance(r, dict):
            reg = r.get("regulation") or r.get("jogszabaly")  # legacy compat
        else:
            reg = None
        if reg:
            from_risks.add(reg)

    all_standards = always | from_risks

    # Sorted display order for the UI footer
    order = [
        "HU VAT Act §169", "HU Tax Procedure Act §22",
        "Universal contract completeness", "Universal contract proportionality",
        "ISA 240", "ISA 240 (duplicate invoice)",
        "ISA 500", "ISA 320",
        "GDPR Article 28", "M&A DD best practice",
        "Incoterms 2020", "IFRS / national GAAP comparison",
        "AML / Sanctions screening",
        "Contract date best practice",
        "EU VAT Directive",
    ]
    result = [s for s in order if s in all_standards]
    # Append any standards not in the fixed order
    for s in sorted(all_standards):
        if s and s not in result:
            result.append(s)
    return result


__all__ = [
    "DomainCheck",
    "CHECK_REGISTRY",
    "SKIP_FROM_DISPATCH",
    "get_check",
    "get_applied_standards",
    "is_empty",
    "make_risk",
    # Check classes
    "InvoiceMandatoryCheck",
    "TaxCDVCheck",
    "ContractCompletenessCheck",
    "ProportionalityCheck",
    "RoundedAmountsCheck",
    "EvidenceScoreCheck",
    "MaterialityCheck",
    "GDPR28Check",
    "DDRedFlagsCheck",
    "IncotermsCheck",
    "IFRSHARCheck",
    "DuplicateInvoiceCheck",
    "AMLSanctionsCheck",
    "ContractDatesCheck",
    # Helpers
    "compute_cdv",
    "validate_tax_cdv",
    "get_evidence_score",
    "INCOTERMS_2020",
    "check_duplicate_invoices",
]
