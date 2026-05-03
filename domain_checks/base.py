"""DomainCheck Protocol — every one of the 14 domain rules implements this.

Unification:
  * ``check_id``: stable identifier (debug, logging, registry lookup)
  * ``regulation``: ISA 240, GDPR Article 28, HU VAT Act §169, etc.
  * ``is_hu_specific``: True → only runs on Hungarian-jurisdiction documents
  * ``applies_to``: set of doc_types where the check runs, or ``{"*"}`` = anywhere
  * ``apply(extracted)``: returns a list of Risks based on the flat dict

``domain_checks/__init__.py`` lists all 14 in ``CHECK_REGISTRY``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from graph.states.pipeline_state import Risk


@runtime_checkable
class DomainCheck(Protocol):
    """Protocol-level interface — every check class implements this."""

    check_id: str
    regulation: str
    is_hu_specific: bool
    applies_to: set[str]

    def apply(self, extracted: dict) -> list[Risk]: ...


def make_risk(
    description: str,
    severity: str,
    rationale: str,
    regulation: str,
    source_check_id: str,
) -> Risk:
    """Unified Risk builder for the domain checks."""
    return Risk(
        description=description,
        severity=severity,
        rationale=rationale,
        kind="domain_rule",
        regulation=regulation,
        source_check_id=source_check_id,
    )


def is_empty(value) -> bool:
    """Mirror of ``prototype-agentic/domain_checks.py:_is_empty``."""
    from utils.numbers import is_null_alias

    if value is None:
        return True
    if isinstance(value, str):
        return is_null_alias(value) or value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False
