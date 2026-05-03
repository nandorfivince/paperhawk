"""SUMMARY.md generátor a tests/e2e_api/results/ JSON-jeiből.

Használat: python tests/e2e_api/generate_summary.py
Output: tests/e2e_api/results/SUMMARY.md
"""

from __future__ import annotations

import json
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _read_results() -> list[dict]:
    out = []
    for p in sorted(RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["__file__"] = p.name
            out.append(data)
        except Exception:
            continue
    return out


def _format_assertion(a: dict) -> str:
    icon = "OK" if a.get("passed") else "FAIL"
    t = a.get("type", "?")
    if t == "must_contain_keyword":
        return f"  [{icon}] must contain `{a.get('keyword')}`"
    if t == "must_contain_any_of":
        return f"  [{icon}] must contain any of {a.get('keywords')}"
    if t == "must_not_contain":
        return f"  [{icon}] must NOT contain `{a.get('keyword')}`"
    if t == "risk_count_min":
        return f"  [{icon}] risk_count >= {a.get('min')} (actual: {a.get('actual')})"
    if t == "risk_count_max":
        return f"  [{icon}] risk_count <= {a.get('max')} (actual: {a.get('actual')})"
    if t == "severity_max":
        return f"  [{icon}] severity_max <= `{a.get('max_allowed')}` (actual: `{a.get('actual_max')}`)"
    if t == "doc_type":
        return f"  [{icon}] doc_type == `{a.get('expected')}` (actual: `{a.get('actual')}`)"
    if t == "doc_types_set":
        return f"  [{icon}] doc_types == {a.get('expected')} (actual: {a.get('actual')})"
    if t == "doc_types_all":
        return f"  [{icon}] all doc_types == `{a.get('expected_all')}`"
    return f"  [{icon}] {t}"


def _summary_pipeline(data: dict) -> str:
    lines = []
    name = data.get("test_name") or data.get("__file__", "?").replace(".json", "")
    elapsed = data.get("pipeline_seconds", 0)
    n_doc = data.get("document_count", 0)
    n_risk = data.get("risk_count", 0)
    assertions = data.get("paritas_assertions", [])
    n_pass = sum(1 for a in assertions if a.get("passed"))
    n_fail = sum(1 for a in assertions if not a.get("passed"))
    overall = "PASS" if n_fail == 0 else ("PARTIAL" if n_pass > 0 else "FAIL")

    lines.append(f"### `{name}` — {overall}")
    lines.append(f"- Fájlok: {data.get('files', [])}")
    lines.append(f"- Pipeline-idő: {elapsed:.1f}s, doksik: {n_doc}, risks: {n_risk}")
    lines.append(f"- Assertek: {n_pass} OK, {n_fail} FAIL ({len(assertions)} össz)")
    if assertions:
        lines.append("")
        for a in assertions:
            lines.append(_format_assertion(a))
    # Risk-leírások (ha van)
    risks = data.get("risks", [])
    if risks:
        lines.append("")
        lines.append("**Tényleges risk-ek (top 5):**")
        sev_order = {"magas": 0, "kozepes": 1, "alacsony": 2, "info": 3}
        for r in sorted(risks, key=lambda x: sev_order.get(x.get("sulyossag", "info"), 4))[:5]:
            sev = (r.get("sulyossag") or "info").upper()
            tipus = r.get("tipus") or ""
            jog = r.get("jogszabaly") or ""
            jog_str = f" [{jog}]" if jog else ""
            lines.append(f"  - **{sev}** ({tipus}){jog_str}: {r.get('leiras', '')}")
    # Comparison ha van
    comp = data.get("comparison")
    if comp:
        lines.append("")
        lines.append("**Three-way matching:**")
        matches = comp.get("matches", [])
        for m in matches[:5]:
            sev = m.get("severity", "?")
            field = m.get("field", "")
            msg = m.get("message", "")
            lines.append(f"  - **{sev.upper()}** {field}: {msg}")
    # Package insights
    pkg = data.get("package_insights")
    if pkg:
        lines.append("")
        lines.append("**Package insights — exec summary:**")
        lines.append(f"  > {pkg.get('executive_summary', '')[:300]}")
    # DD report
    dd = data.get("dd_report")
    if dd:
        lines.append("")
        lines.append("**DD report — top red flags:**")
        for flag in (dd.get("top_red_flags") or [])[:5]:
            lines.append(f"  - {flag}")
    lines.append("")
    return "\n".join(lines), overall


def _summary_chat(data: dict) -> tuple[str, str]:
    lines = []
    scenario = data.get("scenario", "?")
    elapsed = data.get("elapsed_seconds", 0)
    qa = data.get("qa", [])
    n_pass = 0
    n_fail = 0
    n_error = 0
    for r in qa:
        if r.get("error"):
            n_error += 1
        elif all(a.get("passed") for a in r.get("assertions", [])):
            n_pass += 1
        else:
            n_fail += 1
    overall = "PASS" if n_fail == 0 and n_error == 0 else ("PARTIAL" if n_pass > 0 else "FAIL")

    lines.append(f"### `chat / {scenario}` — {overall}")
    lines.append(f"- Idő: {elapsed:.1f}s, kérdés: {len(qa)} (OK: {n_pass}, FAIL: {n_fail}, ERROR: {n_error})")
    lines.append("")
    for i, r in enumerate(qa, 1):
        if r.get("error"):
            lines.append(f"**Q{i}**: {r.get('q', '')}")
            lines.append(f"  - ERROR: {r.get('error')}")
            continue
        passed = all(a.get("passed") for a in r.get("assertions", []))
        icon = "OK" if passed else "FAIL"
        lines.append(f"**Q{i}** [{icon}]: {r.get('q', '')}")
        ans = (r.get("a") or "").strip().replace("\n", " ")
        lines.append(f"  - A: {ans[:300]}{'...' if len(ans) > 300 else ''}")
        for a in r.get("assertions", []):
            lines.append(_format_assertion(a))
        lines.append("")
    return "\n".join(lines), overall


def main() -> None:
    results = _read_results()
    if not results:
        print("Nincsenek eredmények a results/ mappában")
        return

    summary_lines = [
        "# E2E API Paritás-teszt SUMMARY",
        "",
        f"_{len(results)} JSON eredmény feldolgozva._",
        "",
        "## Kvantitatív összegzés",
        "",
        "| Csoport | Teszt | Eredmény | Risks | Idő (s) |",
        "|---------|-------|----------|-------|---------|",
    ]

    detailed_blocks = []
    counts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0}

    for data in results:
        if data.get("__file__", "").startswith("10_chat_"):
            block, overall = _summary_chat(data)
            counts[overall] = counts.get(overall, 0) + 1
            qa = data.get("qa", [])
            n_pass = sum(1 for r in qa if not r.get("error") and all(a.get("passed") for a in r.get("assertions", [])))
            summary_lines.append(
                f"| 10_chat | {data.get('scenario', '?')} | **{overall}** | "
                f"{n_pass}/{len(qa)} kérdés | {data.get('elapsed_seconds', 0):.1f} |"
            )
            detailed_blocks.append(block)
        else:
            block, overall = _summary_pipeline(data)
            counts[overall] = counts.get(overall, 0) + 1
            test_name = data.get("test_name", "?")
            n_risk = data.get("risk_count", 0)
            elapsed = data.get("pipeline_seconds", 0)
            csoport = test_name.split("_")[0] if test_name else "?"
            summary_lines.append(
                f"| {csoport} | {test_name} | **{overall}** | {n_risk} | {elapsed:.1f} |"
            )
            detailed_blocks.append(block)

    summary_lines.append("")
    summary_lines.append(
        f"**Összesítés:** PASS: {counts.get('PASS', 0)}, "
        f"PARTIAL: {counts.get('PARTIAL', 0)}, FAIL: {counts.get('FAIL', 0)} (összesen: {len(results)})"
    )
    summary_lines.append("")
    summary_lines.append("---")
    summary_lines.append("")
    summary_lines.append("## Részletes eredmények")
    summary_lines.append("")
    summary_lines.extend(detailed_blocks)

    out_path = RESULTS_DIR / "SUMMARY.md"
    out_path.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"Generálva: {out_path}")
    print(f"PASS: {counts.get('PASS', 0)}, PARTIAL: {counts.get('PARTIAL', 0)}, FAIL: {counts.get('FAIL', 0)}")


if __name__ == "__main__":
    main()
