"""Date-logic validation — Python deterministic.

  * Invoice: payment_due_date < issue_date → "medium" severity

The contract date check (``check_14_contract_dates``) lives in domain_checks/.
This module covers only invoice-level date logic so that ``basic_risk_node``
does not duplicate ``check_14``.
"""

from __future__ import annotations


def validate_date_logic(extracted: dict) -> list[dict]:
    """Invoice date-logic check. Simple string comparison (works for ISO 8601)."""
    errors: list[dict] = []

    issue_date = extracted.get("issue_date")
    due_date = extracted.get("payment_due_date")

    if issue_date and due_date and isinstance(issue_date, str) and isinstance(due_date, str):
        if due_date < issue_date:
            errors.append({
                "type": "date_error",
                "severity": "medium",
                "message": (
                    f"Payment due date ({due_date}) is earlier than "
                    f"the issue date ({issue_date})"
                ),
            })

    return errors


def validate_contract_dates(extracted: dict) -> list[dict]:
    """Contract-specific date logic: expiry_date >= effective_date.

    The richer message is provided by ``domain_checks/check_14_contract_dates``;
    this function exists only as a fallback in the basic_risk_node flow.
    """
    from utils.numbers import is_null_alias

    errors: list[dict] = []

    effective_date = str(extracted.get("effective_date") or "")
    expiry_date = str(extracted.get("expiry_date") or "")

    indefinite_tokens = {"indefinite", "unlimited", "perpetual", "open-ended",
                         "határozatlan", "unbefristet"}

    if (effective_date and expiry_date
            and not is_null_alias(effective_date) and not is_null_alias(expiry_date)
            and expiry_date.lower() not in indefinite_tokens
            and expiry_date < effective_date):
        errors.append({
            "type": "date_error",
            "severity": "high",
            "message": (
                f"Date logic contradiction: expiry date ({expiry_date}) "
                f"precedes effective date ({effective_date})"
            ),
        })

    return errors
