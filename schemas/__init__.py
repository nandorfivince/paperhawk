"""Schema-rendszer: JSON schema betöltés + Pydantic mirror választás.

Használat:

    from schemas import load_schema, pydantic_for

    json_schema = load_schema("szamla")          # dict
    pydantic_cls = pydantic_for("szamla")        # InvoiceModel

A 6 doc_type:
  * szamla              → invoice.json + InvoiceModel
  * szallitolevle       → delivery_note.json + DeliveryNoteModel
  * megrendeles         → purchase_order.json + PurchaseOrderModel
  * szerzodes           → contract.json + ContractModel
  * penzugyi_kimutatas  → financial_report.json + FinancialReportModel
  * egyeb               → universal.json + UniversalModel
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from schemas.flatten_universal import flatten_universal
from schemas.pydantic_models import (
    ContractModel,
    DeliveryNoteModel,
    FinancialReportModel,
    InvoiceModel,
    PurchaseOrderModel,
    UniversalModel,
    pydantic_for,
)

SCHEMA_DIR = Path(__file__).parent

# doc_type → JSON fájlnév (relatív a schemas/ mappához)
SCHEMA_FILES = {
    "szamla": "invoice.json",
    "szallitolevle": "delivery_note.json",
    "megrendeles": "purchase_order.json",
    "szerzodes": "contract.json",
    "penzugyi_kimutatas": "financial_report.json",
    "egyeb": "universal.json",
}


@lru_cache(maxsize=8)
def load_schema(doc_type: str) -> dict:
    """A doc_type-hoz tartozó JSON schema-t adja vissza dict formában.

    Lru_cache: ugyanazt a dict-et adja vissza ismételten (a Pydantic mirror-rel
    együtt használjuk runtime validációhoz; a JSON schema az LLM-nek megy
    `with_structured_output(method="json_schema")`-en át).

    Ismeretlen doc_type → universal.json fallback.
    """
    fname = SCHEMA_FILES.get(doc_type, SCHEMA_FILES["egyeb"])
    path = SCHEMA_DIR / fname
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "load_schema",
    "pydantic_for",
    "flatten_universal",
    "InvoiceModel",
    "ContractModel",
    "DeliveryNoteModel",
    "PurchaseOrderModel",
    "FinancialReportModel",
    "UniversalModel",
]
