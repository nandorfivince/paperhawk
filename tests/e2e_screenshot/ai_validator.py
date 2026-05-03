"""AI-validáló: a Playwright screenshot-jait és a chat-válaszokat
ellenőrzi Claude vision-API-val az `EXPECTED_FINDINGS` paritás-elvárások
alapján.

A `prototype-agentic` E2E manuális tesztelést a user szemmel ellenőrizte:
látta-e MAGAS finding az audit_demo-ban, GDPR-aszimmetria a compliance-ben,
top red flags a DD-ben. Ez a modul ezt **automatizálja** Claude-dal:

  validate_screenshot(image_path, expected_findings: list[str]) → ValidationResult

Minden screenshot-ra/válaszra a Claude egy strukturált értékelést ad:
  * mely várt findingek látszanak (igen/részben/nem)
  * vannak-e meglepetések (false positive vagy hiányzó)
  * áttekintés (1-2 mondat)

A modul fail-fast: ha az ANTHROPIC_API_KEY nincs beállítva, üzenettel skip.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


@dataclass
class ValidationResult:
    """Egy teszt-eset AI-validáció eredménye."""
    test_case: str
    expected_count: int
    found_count: int
    missing: list[str]
    surprises: list[str]
    overall: Literal["pass", "partial", "fail"]
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


def _claude_vision_validate(
    image_b64: str,
    test_case_label: str,
    expected_findings: list[str],
    raw_text_context: str = "",
) -> ValidationResult:
    """Claude vision-hívás screenshot + szöveges várt-finding listával.

    Részletes magyar prompt: a Claude visszaad JSON-t ami megmondja, melyik
    expected_finding látszik a screenshot-on (vagy a raw_text-ben).
    """
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        return ValidationResult(
            test_case=test_case_label,
            expected_count=len(expected_findings),
            found_count=0,
            missing=expected_findings,
            surprises=[],
            overall="fail",
            summary="langchain_anthropic nincs telepítve",
        )

    expected_block = "\n".join(f"  - {f}" for f in expected_findings)
    user_prompt = f"""Egy screenshot-ot és egy szöveges kontextust adok az `Agentic Document Intelligence Platform` UI-jából.

Teszt-eset: **{test_case_label}**

Várt findingek (paritás a `prototype-agentic` `EXPECTED_FINDINGS.md`-vel):
{expected_block}

Szöveges kontextus (ha van):
{raw_text_context[:3000] if raw_text_context else "(üres)"}

Feladatod: állapítsd meg, mely várt findingek látszanak a screenshot-on
vagy a szöveges kontextusban. Adj vissza JSON-t a következő mezőkkel:
- `found`: list[str] — a megtalált findingek (`expected_findings`-ből)
- `missing`: list[str] — a NEM megtalált findingek
- `surprises`: list[str] — más, nem várt findingek vagy gyanús minták (max 5)
- `overall`: "pass" | "partial" | "fail"
  ("pass" = minden megvan, "partial" = legalább 50%, "fail" = kevesebb mint 50%)
- `summary`: 1-2 mondatos értékelés magyarul

Strict JSON, magyarázat nélkül."""

    try:
        llm = ChatAnthropic(
            model_name=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
            temperature=0,
        )
        from langchain_core.messages import HumanMessage
        msg = HumanMessage(content=[
            {"type": "text", "text": user_prompt},
            {
                "type": "image",
                "source_type": "base64",
                "data": image_b64,
                "mime_type": "image/png",
            },
        ])
        response = llm.invoke([msg])
        content = response.content
        text = content if isinstance(content, str) else "\n".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
        # JSON-extract
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0:
            raise ValueError("Nem talált JSON-t a Claude-válaszban")
        data = json.loads(text[start:end + 1])
        return ValidationResult(
            test_case=test_case_label,
            expected_count=len(expected_findings),
            found_count=len(data.get("found", [])),
            missing=data.get("missing", []),
            surprises=data.get("surprises", []),
            overall=data.get("overall", "partial"),
            summary=data.get("summary", ""),
        )
    except Exception as exc:
        return ValidationResult(
            test_case=test_case_label,
            expected_count=len(expected_findings),
            found_count=0,
            missing=expected_findings,
            surprises=[],
            overall="fail",
            summary=f"AI-validáció hiba: {type(exc).__name__}: {exc}",
        )


def validate_screenshot(
    image_path: Path,
    test_case_label: str,
    expected_findings: list[str],
    raw_text_context: str = "",
) -> ValidationResult:
    """A screenshot fájl + várt findings → ValidationResult.

    Args:
        image_path: a Playwright `full_page=True` screenshot
        test_case_label: pl. "audit_demo / Eredmények tab"
        expected_findings: paritás-listák a `prototype-agentic/test_data/EXPECTED_FINDINGS.md`-ből
        raw_text_context: opcionális szöveges kontextus (pl. chat-válasz, DOCX-text)
    """
    if not image_path.exists():
        return ValidationResult(
            test_case=test_case_label,
            expected_count=len(expected_findings),
            found_count=0,
            missing=expected_findings,
            surprises=[],
            overall="fail",
            summary=f"Nem létezik a screenshot: {image_path}",
        )

    image_b64 = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
    return _claude_vision_validate(image_b64, test_case_label, expected_findings, raw_text_context)


def write_validation_report(out_dir: Path, results: list[ValidationResult]) -> None:
    """Markdown report írás a `snapshots/{testcase}/ai_validation.md`-be."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md = ["# AI-validáció", ""]
    for r in results:
        emoji = {"pass": "[OK]", "partial": "[RÉSZBEN]", "fail": "[FAIL]"}[r.overall]
        md.append(f"## {emoji} {r.test_case}")
        md.append(f"- Várt: {r.expected_count}, talált: {r.found_count}")
        if r.missing:
            md.append(f"- Hiányzó: {', '.join(r.missing)}")
        if r.surprises:
            md.append(f"- Meglepetések: {', '.join(r.surprises)}")
        md.append(f"- {r.summary}")
        md.append("")
    (out_dir / "ai_validation.md").write_text("\n".join(md), encoding="utf-8")

    # JSON is, gépi feldolgozáshoz
    (out_dir / "ai_validation.json").write_text(
        json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
