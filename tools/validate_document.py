"""validate_document tool — math + date + tax-id validation on a single document."""

from __future__ import annotations

from langchain_core.tools import tool

from domain_checks import validate_tax_cdv
from tools.context import ChatToolContext
from validation.date_logic import validate_contract_dates, validate_date_logic
from validation.invoice_math import validate_invoice_math
from validation.plausibility import validate_plausibility


def build_validate_document_tool(ctx: ChatToolContext):
    @tool
    def validate_document(filename: str) -> str:
        """Run mathematical + logical + tax-id validation on a single document.

        Invoice: line-item sums, net+VAT=gross, date logic, tax id CDV.
        Contract: effective/expiry date logic.

        Args:
            filename: the document filename
        """
        pd = ctx.get_document(filename)
        if pd is None:
            return f"Not found: '{filename}'. Available: {ctx.list_filenames()}"

        if pd.extracted is None:
            return f"'{filename}' has not been extracted yet (extracted=null)."

        raw = pd.extracted.raw
        doc_type = pd.classification.doc_type if pd.classification else "other"

        errors: list[dict] = []

        # Invoice math + dates
        errors.extend(validate_invoice_math(raw))
        errors.extend(validate_date_logic(raw))

        # Contract-specific
        if doc_type == "contract":
            errors.extend(validate_contract_dates(raw))

        # Plausibility
        errors.extend(validate_plausibility(raw))

        # Tax-id CDV (Hungarian mod-11 for HU tax IDs only)
        for party_key in ("issuer", "customer", "supplier"):
            party = raw.get(party_key)
            if isinstance(party, dict):
                tax = party.get("tax_id")
                if tax:
                    valid = validate_tax_cdv(str(tax))
                    if valid is False:
                        errors.append({
                            "type": "tax_cdv",
                            "severity": "high",
                            "message": f"{party_key} tax ID CDV invalid: {tax}",
                        })

        if not errors:
            return f"No issues found in '{filename}' (math + dates + tax id OK). [Source: {filename}]"

        lines = [f"Issues in '{filename}':"]
        for err in errors:
            sev = err.get("severity", "?")
            msg = err.get("message", "")
            lines.append(f"  [{sev}] {msg}")
        lines.append(f"\n[Source: {filename}]")
        return "\n".join(lines)

    return validate_document
