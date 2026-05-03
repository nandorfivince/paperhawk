"""E2E teljes flow Playwright + AI-validáció.

A `prototype-agentic/docs/prototype-agentic-tesztek/` 72 manuális screenshot-os
tesztet automatizáljuk. 4 demo-eset (audit_demo, dd_demo, compliance_demo,
multi_doc) + minden tab full-page screenshot + chat-szekvencia + AI-validáció.

Futtatás:
  pytest tests/e2e_screenshot/ -v -s

A `streamlit_server` session-fixture indítja a portot a 8520-on. A
`ai_validator.py` Claude vision-API-val validál a screenshotok alapján.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.e2e_screenshot.ai_validator import (
    ValidationResult,
    validate_screenshot,
    write_validation_report,
)
from tests.e2e_screenshot.conftest import SNAPSHOTS_DIR


# ---------------------------------------------------------------------------
# Várt findingek a `prototype-agentic/test_data/EXPECTED_FINDINGS.md`-ből
# ---------------------------------------------------------------------------

EXPECTED_AUDIT_DEMO = [
    "Magas kerekített összeg arány",
    "50% árnövekedés a márciusi számlán",
    "Hiányzó kötelező számlaelem (cím vagy fizetési mód)",
    "Csomag-szintű cross-doc anomália",
]

EXPECTED_DD_DEMO = [
    "Change-of-control klauzula",
    "Non-compete (versenytilalom) klauzula",
    "Automatikus megújulás",
    "Top red flags lista (3+)",
    "Per-szerződés kockázati szint",
    "Havi kötelezettségek aggregálva",
]

EXPECTED_COMPLIANCE_DEMO = [
    "GDPR 28. cikk hiányzó elemek (kritikus)",
    "Kontraszt: a-szerz teljes vs b-szerz hiányos",
    "Csomag-szintű compliance aszimmetria",
    "Személyes adatok feldolgozása PII-indikátor",
]

EXPECTED_MULTI_DOC = [
    "Three-way matching mennyiségi eltérés",
    "Critical/warning a keresztellenőrzésben",
    "HI-100 cikkszám említése",
]


# ---------------------------------------------------------------------------
# Helper-ek
# ---------------------------------------------------------------------------


def _click_tab(page, tab_name: str) -> None:
    """Streamlit tab-kattintás (a tab-szöveg alapján).

    A Streamlit tab-jai `role="tab"` szerepben vannak — pontos szelektor,
    hogy a sidebar gombokat (pl. "Chat előzmények törlése") NE találja el.
    """
    # Elsődleges: pontos role+név egyezés a tablist-en belül
    tab = page.get_by_role("tab", name=tab_name, exact=True).first
    if tab.count() > 0:
        tab.scroll_into_view_if_needed()
        tab.click()
    else:
        # Fallback: explicit data-testid alapú szelektor (Streamlit st.tabs)
        candidates = page.locator(f"[data-baseweb='tab']:has-text('{tab_name}')").all()
        if candidates:
            candidates[0].click()
        else:
            # Régi fallback (kockázatos, de jobb mint semmi)
            page.locator(f"button:has-text('{tab_name}')").first.click()
    page.wait_for_load_state("networkidle", timeout=10000)
    time.sleep(1.5)  # Streamlit re-render


def _full_page_screenshot(page, path: Path) -> None:
    """Teljes oldal screenshot (görgetett tartalom is).

    A Streamlit shadow DOM-ja miatt a Playwright `full_page=True` csak a
    viewport-ot rögzíti. Trükk: dinamikusan a tartalom magasságához állítjuk
    a viewport-ot, scrollozunk az aljáig és vissza (lazy render trigger),
    majd kérünk full_page screenshot-ot.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # 1. Görgetés aljáig hogy a virtual scroll alatt is mountolódjon
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(0.6)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.4)
        # 2. Tartalom magasság detektálás (a max-ot vesszük a body és main között)
        height = page.evaluate(
            """() => Math.max(
                document.body.scrollHeight,
                document.documentElement.scrollHeight,
                document.body.offsetHeight,
                document.documentElement.offsetHeight,
                document.querySelector('main')?.scrollHeight || 0,
                document.querySelector('section[data-testid=\\"stMain\\"]')?.scrollHeight || 0
            )"""
        )
        height = max(int(height or 0), 1000)
        # Maximalizáljuk: ne legyen hatalmas ha a content kicsi, de fedjen le mindent
        target = min(height + 200, 12000)
        page.set_viewport_size({"width": 1600, "height": target})
        time.sleep(0.6)
    except Exception:
        pass
    page.screenshot(path=str(path), full_page=True)
    # Visszaállítás az alapviewport-ra (a következő művelet kompatibilitásához)
    try:
        page.set_viewport_size({"width": 1600, "height": 1000})
        time.sleep(0.3)
    except Exception:
        pass


def _wait_for_demo_complete(page, timeout: float = 600.0) -> None:
    """Megvárja amíg a demo-pipeline befejeződik.

    A `st.success("...betöltve...")` üzenet a `st.rerun()` után eltűnik —
    helyette a sidebar **"Feldolgozott dokumentumok: N"** zöld dobozra várunk,
    mert ez a `st.session_state.pipeline_state` jelenlétét tükrözi.

    A Claude API hívásokra elég idő: 3 doksi × ~6 LLM hívás + package_insights
    + DD synthesizer = 25-30 LLM hívás Haiku-val ≈ 4-7 perc.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # A sidebar success-doboz "Feldolgozott dokumentumok: N" → pipeline_state kész
        if page.locator("text=Feldolgozott dokumentumok").count() > 0:
            time.sleep(3.0)
            return
        # Backup: ha a Feltöltés tabon megjelenik a "Jelenleg N feldolgozott" üzenet
        if page.locator("text=feldolgozott dokumentum van").count() > 0:
            time.sleep(3.0)
            return
        # Az Alkalmazott szabványok footer is csak a pipeline-state után renderelődik
        if page.locator("text=Alkalmazott szabványok").count() > 0:
            time.sleep(3.0)
            return
        time.sleep(1.5)
    raise TimeoutError(f"Demo nem fejeződött be {timeout}s alatt")


def _click_demo_button(page, label: str) -> None:
    """Demo gomb kattintás. A `Indítás` gomb a `label` alatti card-ban van.

    A 3 demo card mindegyikében pontosan egyetlen "Indítás" feliratú gomb van —
    a `Feldolgozás indítása` upload-gomb tág match miatt nem rontja el a
    sorrendet, mert exact-name szelektort használunk.
    """
    label_to_idx = {
        "Audit Demo": 0,
        "Due Diligence Demo": 1,
        "Compliance Demo": 2,
    }
    idx = label_to_idx[label]
    # Pontos szöveg-egyezés: csak az "Indítás" gomb (NEM "Feldolgozás indítása")
    buttons = page.get_by_role("button", name="Indítás", exact=True).all()
    if not buttons:
        # Fallback: regex-pattern-rel pontosan az "Indítás" szöveggel
        import re as _re
        buttons = page.get_by_role("button", name=_re.compile(r"^Indítás$")).all()
    if len(buttons) <= idx:
        raise RuntimeError(
            f"Csak {len(buttons)} db 'Indítás' gomb van, de a {idx}. (label={label}) kéne"
        )
    buttons[idx].scroll_into_view_if_needed()
    buttons[idx].click()


def _manual_upload_files(page, file_paths: list[Path]) -> None:
    """Streamlit `st.file_uploader` programmatikus fájl-feltöltés.

    A `app/main.py:feltoltes_tab`-ban `accept_multiple_files=True` van — egyszerre
    többfájlos átadás OK. A feltöltés UTÁN megjelenik a "Feldolgozás indítása"
    gomb (csak ha van fájl), arra kattintunk.

    Args:
        page: Playwright page objektum
        file_paths: lista a feltöltendő fájlok abszolút útvonalairól
    """
    # `st.file_uploader` egy hidden `<input type='file'>` egy stXxxx wrapper-ben
    file_input = page.locator("input[type='file']").first
    file_input.set_input_files([str(p) for p in file_paths])
    time.sleep(2.0)  # Streamlit re-render hogy a "Feldolgozás indítása" megjelenjen
    upload_btn = page.get_by_role("button", name="Feldolgozás indítása", exact=True).first
    upload_btn.scroll_into_view_if_needed()
    upload_btn.click()


def _open_all_expanders(page, max_count: int = 20) -> None:
    """Minden Streamlit expander-t kinyit (DD/Riport tabokon hasznos)."""
    expanders = page.locator("button[aria-expanded='false']").all()
    for exp in expanders[:max_count]:
        try:
            exp.click(timeout=2000)
            time.sleep(0.3)
        except Exception:
            pass
    time.sleep(0.5)


def _capture_5_tabs_and_chat(
    page,
    case_dir: Path,
    questions: list[str],
) -> list[dict]:
    """A pipeline befejezése UTÁN: 5 tab full-page screenshot + chat-szekvencia.

    Returns:
        chat_responses lista a JSON mentéshez (és AI-validáció kontextushoz).
    """
    # 03. Eredmények tab
    _click_tab(page, "Eredmények")
    time.sleep(2.0)
    _full_page_screenshot(page, case_dir / "03_eredmenyek_full.png")

    # 04. Chat tab — szekvencia kérdésekkel (kérdésenként külön screenshot)
    _click_tab(page, "Chat")
    time.sleep(2.0)
    chat_responses: list[dict] = []
    for i, q in enumerate(questions, start=1):
        try:
            answer = _ask_chat_question(page, q)
        except Exception as exc:
            answer = f"[HIBA: {type(exc).__name__}: {exc}]"
        chat_responses.append({"question": q, "answer": answer})
        _full_page_screenshot(page, case_dir / f"04_chat_q{i:02d}.png")

    (case_dir / "chat_responses.json").write_text(
        json.dumps(chat_responses, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 05. DD Asszisztens tab
    _click_tab(page, "DD Asszisztens")
    time.sleep(2.0)
    _open_all_expanders(page)
    _full_page_screenshot(page, case_dir / "05_dd_full.png")

    # 06. Riport tab
    _click_tab(page, "Riport")
    time.sleep(2.0)
    json_exp = page.locator("button:has-text('JSON nézet')").first
    if json_exp.count() > 0:
        try:
            json_exp.click(timeout=2000)
            time.sleep(1.0)
        except Exception:
            pass
    _full_page_screenshot(page, case_dir / "06_riport_full.png")

    return chat_responses


def _run_ai_validation(
    case_dir: Path,
    label: str,
    expected: list[str],
    chat_responses: list[dict],
) -> list[ValidationResult]:
    """AI-validáció a 3 fő screenshot-on (Eredmények + Chat 1. válasz + Riport)."""
    chat_text = "\n\n".join(
        f"Q: {r['question']}\nA: {r['answer']}" for r in chat_responses
    )
    results: list[ValidationResult] = []

    results.append(validate_screenshot(
        case_dir / "03_eredmenyek_full.png",
        f"{label} / Eredmények tab",
        expected,
    ))
    if (case_dir / "04_chat_q01.png").exists():
        results.append(validate_screenshot(
            case_dir / "04_chat_q01.png",
            f"{label} / Chat (1. válasz)",
            expected,
            raw_text_context=chat_text,
        ))
    results.append(validate_screenshot(
        case_dir / "06_riport_full.png",
        f"{label} / Riport tab",
        expected,
    ))
    write_validation_report(case_dir, results)
    return results


def _ask_chat_question(page, question: str) -> str:
    """Chat-input kitöltés + várás a válaszra. Visszaadja a válasz nyers szövegét."""
    # Görgessünk az oldal aljáig hogy a chat_input mountolódjon (Streamlit lazy)
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(0.7)
    except Exception:
        pass
    chat_input = page.locator("textarea[data-testid='stChatInputTextArea'], textarea[placeholder*='Kérdezz']").first
    # Várjuk meg hogy láthatóvá váljon — Streamlit chat_input fixed pozícióban van
    try:
        chat_input.wait_for(state="visible", timeout=15000)
    except Exception:
        # Második próba: scroll_into_view_if_needed + várás
        try:
            chat_input.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
    chat_input.fill(question)
    chat_input.press("Enter")
    # 15 másodperces fix várás. A Claude rövid válaszai 3-5s alatt kész, a hosszabb
    # multi-doc/multi-szerződés kérdések 10-15s. A 15s középút: minden gyakori chat
    # válasz kész, és csak +3 perc plusz idő a 4-scenario futáshoz.
    time.sleep(15.0)

    # Az utolsó assistant üzenet szövege
    msgs = page.locator("[data-testid='stChatMessage']").all()
    if not msgs:
        return ""
    return msgs[-1].inner_text()


# ---------------------------------------------------------------------------
# Tesztek
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize("demo,expected,questions", [
    (
        "audit_demo",
        EXPECTED_AUDIT_DEMO,
        [
            "Mit lehet tudni ezekről a számlákról és mi az összefüggés köztük?",
            "Hány százalékkal drágább a legutolsó számla a legelsőhöz képest?",
            "Van matematikai hiba vagy hiányzó kötelező mező a számlákon?",
        ],
    ),
    (
        "dd_demo",
        EXPECTED_DD_DEMO,
        [
            "Milyen DD-szempontból kritikus klauzulák szerepelnek a szerződésekben?",
            "Mekkora az aggregált havi kötelezettség?",
            "Van change-of-control vagy non-compete klauzula bárhol?",
        ],
    ),
    (
        "compliance_demo",
        EXPECTED_COMPLIANCE_DEMO,
        [
            "Megfelel-e a két szerződés a GDPR 28. cikknek?",
            "Hasonlítsd össze a két szerződést compliance szempontból.",
            "Van olyan szerződés, ami személyes adatot dolgoz fel adatvédelmi záradék nélkül?",
        ],
    ),
])
def test_demo_full_flow(streamlit_server, browser, demo, expected, questions):
    """Demo gomb kattintás → 5 tab végig + chat-szekvencia + AI-validáció."""
    case_dir = SNAPSHOTS_DIR / demo
    case_dir.mkdir(parents=True, exist_ok=True)

    page = browser.new_page()
    page.goto(streamlit_server)
    page.wait_for_load_state("networkidle", timeout=30000)
    # Streamlit komplet renderelést várjuk: a "Gyors demo" h2 megjelenik
    page.wait_for_selector("text=Gyors demo", timeout=30000)
    time.sleep(2)

    # 01. Feltöltés tab — alap állapot (teljes UI render után)
    _full_page_screenshot(page, case_dir / "01_feltoltes_alap.png")

    # 02. Demo gomb kattintás
    label_map = {
        "audit_demo": "Audit Demo",
        "dd_demo": "Due Diligence Demo",
        "compliance_demo": "Compliance Demo",
    }
    _click_demo_button(page, label_map[demo])
    time.sleep(3.0)
    _full_page_screenshot(page, case_dir / "02_demo_gomb_kattintva.png")

    # Várás a feldolgozás befejeződésére (3 doksi × ~6 LLM hívás + package + DD ≈ 5-7 perc)
    try:
        _wait_for_demo_complete(page, timeout=600.0)
    except TimeoutError:
        _full_page_screenshot(page, case_dir / "ERROR_timeout.png")
        raise

    # 03. Eredmények tab full-page
    _click_tab(page, "Eredmények")
    time.sleep(2.0)
    _full_page_screenshot(page, case_dir / "03_eredmenyek_full.png")

    # 04. Chat tab — szekvencia kérdésekkel
    _click_tab(page, "Chat")
    time.sleep(2.0)
    chat_responses: list[dict] = []
    for i, q in enumerate(questions, start=1):
        try:
            answer = _ask_chat_question(page, q)
        except Exception as exc:
            answer = f"[HIBA: {type(exc).__name__}: {exc}]"
        chat_responses.append({"question": q, "answer": answer})
        _full_page_screenshot(page, case_dir / f"04_chat_q{i:02d}.png")

    # Mentsük el a chat válaszokat JSON-be
    (case_dir / "chat_responses.json").write_text(
        json.dumps(chat_responses, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 05. DD Asszisztens tab full-page
    _click_tab(page, "DD Asszisztens")
    time.sleep(2.0)
    # Minden expander nyitva legyen — minden expander gombra kattintunk
    expanders = page.locator("button[aria-expanded='false']").all()
    for exp in expanders[:20]:  # max 20 a végtelen ciklus elkerüléséhez
        try:
            exp.click(timeout=2000)
            time.sleep(0.3)
        except Exception:
            pass
    time.sleep(1.0)
    _full_page_screenshot(page, case_dir / "05_dd_full.png")

    # 06. Riport tab full-page
    _click_tab(page, "Riport")
    time.sleep(2.0)
    # JSON-expander nyitva
    json_exp = page.locator("button:has-text('JSON nézet')").first
    if json_exp.count() > 0:
        try:
            json_exp.click(timeout=2000)
            time.sleep(1.0)
        except Exception:
            pass
    _full_page_screenshot(page, case_dir / "06_riport_full.png")

    # 07. AI-validáció — minden screenshot + chat-válasz alapján
    chat_text = "\n\n".join(f"Q: {r['question']}\nA: {r['answer']}" for r in chat_responses)
    results: list[ValidationResult] = []

    eredmenyek_validation = validate_screenshot(
        case_dir / "03_eredmenyek_full.png",
        f"{demo} / Eredmények tab",
        expected,
    )
    results.append(eredmenyek_validation)

    chat_validation = validate_screenshot(
        case_dir / "04_chat_q01.png",
        f"{demo} / Chat (1. válasz)",
        expected,
        raw_text_context=chat_text,
    )
    results.append(chat_validation)

    riport_validation = validate_screenshot(
        case_dir / "06_riport_full.png",
        f"{demo} / Riport tab",
        expected,
    )
    results.append(riport_validation)

    write_validation_report(case_dir, results)
    page.close()

    # Asszertálás — a végén legalább 1 "pass" vagy "partial" legyen
    overall_states = {r.overall for r in results}
    assert "pass" in overall_states or "partial" in overall_states, (
        f"AI-validáció FAIL minden szekcióra: {[r.summary for r in results]}"
    )


# ---------------------------------------------------------------------------
# (b) — Manuális upload szimuláció (4 forgatókönyv) ALAP TESZTI ARZENÁLLAL
# ---------------------------------------------------------------------------


# Várt findingek a manuális forgatókönyvekhez (paritás a tests/e2e_api/expected_findings.py-pel)

EXPECTED_MANUAL_SZAMLAK = [
    "5 számla feldolgozva (HU + EN + DE)",
    "Helyes nyelv-detekció (magyar/english/deutsch)",
    "Classify confidence ≥ 90% mind",
    "0 hamis-pozitív (NEM flag-eli a 0% VAT-ot, 27% ÁFA-t, 19% MwSt-et)",
    "Max KOZEPES finding (Hiányzó Fizetési mód a HU számlákon)",
]

EXPECTED_MANUAL_SZERZODESEK = [
    "4 szerződés feldolgozva (NDA + MSSA + IT support + leasing)",
    "Felmondási feltételek mező kitöltve (legalább 2 szerz)",
    "Irányadó jog mező kitöltve (legalább 2 szerz)",
    "Change-of-control klauzula MSSA-ban detektálva",
    "GDPR 28. cikk finding az IT-supporton vagy lízingen",
]

EXPECTED_MANUAL_MULTI_DOC = [
    "3-utas keresztellenőrzés (megrendelés + szállítólevél + számla)",
    "KRITIKUS HI-100 mennyiségi eltérés (40 vs 38)",
    "I-gerenda 6m cikkszám említése",
    "Comparison overall_status: critical",
]

EXPECTED_MANUAL_ADVERSARIAL = [
    "Math-error detektálva: nettó+ÁFA != bruttó (50 000 Ft eltérés)",
    "Hiányos szerződés finding: Felmondási feltételek hiánya MAGAS",
    "Bilingual HU/EN szerződés Incoterms CIP detektálva",
    "Dátum-logikai ellentmondás finding",
    "3+ MAGAS severity összesen a 4 doksin",
]


@pytest.mark.e2e
@pytest.mark.parametrize("scenario,subdir,glob_pattern,expected,questions", [
    (
        "manual_szamlak",
        "szamlak",
        "*.pdf",
        EXPECTED_MANUAL_SZAMLAK,
        [
            "Hány számla van feltöltve és milyen nyelvűek?",
            "Van matematikai hiba vagy hiányzó kötelező mező a számlákon?",
            "Hasonlítsd össze az ÁFA-kulcsokat a számlákon. Van valami szokatlan?",
        ],
    ),
    (
        "manual_szerzodesek",
        "szerzodesek",
        "*.pdf",
        EXPECTED_MANUAL_SZERZODESEK,
        [
            "Mely szerződésekben van change-of-control vagy non-compete klauzula?",
            "Mi az irányadó jog a szerződésekben?",
            "Van automatikus megújulási klauzula bárhol?",
        ],
    ),
    (
        "manual_multi_doc",
        "multi_doc",
        "*.pdf",
        EXPECTED_MANUAL_MULTI_DOC,
        [
            "Mekkora a HI-100 I-gerenda mennyisége a megrendelésen vs szállítólevélen vs számlán?",
            "Mennyi a HI-100 hiány nettó értéke?",
            "És bruttóban mennyibe kerül az előző hiány?",
        ],
    ),
    (
        "manual_adversarial",
        "adversarial",
        "*.pdf",
        EXPECTED_MANUAL_ADVERSARIAL,
        [
            "Van matematikai hiba valamelyik dokumentumban?",
            "Van olyan szerződés, amiben hiányoznak kötelező elemek?",
            "Van olyan dokumentum, amiben dátum-logikai ellentmondás van?",
        ],
    ),
])
def test_manual_upload_full_flow(
    streamlit_server, browser,
    scenario, subdir, glob_pattern, expected, questions,
):
    """Manuális fájl-feltöltés az `st.file_uploader`-be → 5 tab + chat-szekvencia + AI-validáció.

    Eltérés a `test_demo_full_flow`-hoz képest:
      * A 3 demo-gomb HELYETT a Feltöltés tab `st.file_uploader`-ébe töltjük a fájlokat
      * A teljes test_data/<subdir>/*.pdf készletet egyszerre adjuk át (5/4/3/4 fájl)
      * A "Feldolgozás indítása" gomb futtatja a pipeline-t (UI-szintű, NEM demo-flow)
      * Per-scenario teljes 5 tab + 3 chat kérdés
    """
    from tests.e2e_screenshot.conftest import PROJECT_ROOT
    case_dir = SNAPSHOTS_DIR / scenario
    case_dir.mkdir(parents=True, exist_ok=True)

    # Fájlok betöltése a test_data-ból
    file_paths = sorted((PROJECT_ROOT / "test_data" / subdir).glob(glob_pattern))
    assert file_paths, f"Nincs fájl: test_data/{subdir}/{glob_pattern}"

    page = browser.new_page()
    page.goto(streamlit_server)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_selector("text=Gyors demo", timeout=30000)
    time.sleep(2)

    # 01. Feltöltés tab — alapállapot
    _full_page_screenshot(page, case_dir / "01_feltoltes_alap.png")

    # 02. Manuális upload + Feldolgozás indítása
    _manual_upload_files(page, file_paths)
    time.sleep(3.0)
    _full_page_screenshot(page, case_dir / "02_upload_indul.png")

    # Várás: Claude pipeline + esetleg DD report (csak szerződésnél). Idő: 3-7 perc
    try:
        _wait_for_demo_complete(page, timeout=600.0)
    except TimeoutError:
        _full_page_screenshot(page, case_dir / "ERROR_timeout.png")
        page.close()
        raise

    # 03-06. Tabok + chat
    chat_responses = _capture_5_tabs_and_chat(page, case_dir, questions)

    # 07. AI-validáció
    results = _run_ai_validation(case_dir, scenario, expected, chat_responses)

    page.close()

    overall_states = {r.overall for r in results}
    assert "pass" in overall_states or "partial" in overall_states, (
        f"AI-validáció FAIL minden szekcióra: {[r.summary for r in results]}"
    )
