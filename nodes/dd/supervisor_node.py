"""supervisor_node — LLM router (or dummy heuristic) over DD specialists.

Dummy mode: deterministic rule — legal → financial → audit (if many contracts)
→ compliance (if PII detected) → DONE.

LLM mode: SUPERVISOR_PROMPT below + ``Command(goto=...)``.
"""

from __future__ import annotations

from langgraph.types import Command

from config import settings
from graph.states.dd_state import DDState


SUPERVISOR_PROMPT = """You are a DD coordinator LLM. Based on the contract portfolio
overview, decide which specialist to call AND in what order.

Specialists and their scope:
- audit: financial anomalies, pricing patterns, overcharging
- legal: contractual clauses, change-of-control, non-compete, penalty
- compliance: GDPR, AML, data protection
- financial: monthly obligations, expirations, value aggregation

Specialist calls so far: {call_history}

Return ONLY a specialist name or 'DONE' if every angle is covered.
A complete DD report needs AT LEAST legal and financial. Audit and compliance
are optional — call them only if the portfolio has relevant data.
"""


async def supervisor_node(state: DDState) -> Command:
    """Routing: which specialist next, or DONE → synthesizer.

    Dummy mode: legal → financial → audit → compliance → DONE (max 4 iter).
    """
    iter_count = state.get("iteration_count", 0)
    history = state.get("call_history") or []

    # Force-end after max iter
    if iter_count >= settings.dd_supervisor_max_iterations:
        return Command(goto="dd_synthesizer", update={"next_specialist": "DONE"})

    # Dummy heuristic: mandatory legal + financial; optional audit + compliance
    next_specialist: str | None = None
    if "legal" not in history:
        next_specialist = "legal"
    elif "financial" not in history:
        next_specialist = "financial"
    elif "audit" not in history:
        # only if 2+ contracts (anomaly potential)
        contracts = state.get("contracts") or []
        if len(contracts) >= 2:
            next_specialist = "audit"
    elif "compliance" not in history:
        # only if a contract carries PII / AML signals
        documents = state.get("documents") or []
        has_pii_or_aml = any(
            r.source_check_id in {"check_08_gdpr_28", "check_13_aml_sanctions"}
            for d in documents
            for r in d.risks
        )
        if has_pii_or_aml:
            next_specialist = "compliance"

    if next_specialist is None:
        return Command(goto="dd_synthesizer", update={"next_specialist": "DONE"})

    return Command(
        goto=f"{next_specialist}_specialist",
        update={
            "next_specialist": next_specialist,
            "iteration_count": iter_count + 1,
        },
    )
