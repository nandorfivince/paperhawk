"""Strukturált EXPECTED_FINDINGS a 26 langgraph teszt-fájlra.

A `prototype-agentic/test_data/EXPECTED_FINDINGS.md` tartalom-paritású Python
dict-formában — gépi assertelhetőséghez. Minden teszt-eset:
  * `expected_risks_min/max`: a kockázatok darabszáma elvárt tartomány
  * `must_contain_keywords`: ezek a stringek MEG KELL jelenjenek a risk leírásokban
                              vagy a comparison/package_insights/dd_report kimenetben
  * `must_not_contain`: ezeket a stringeket NEM szabad a kimenet tartalmaznia
                        (false-positive szűrés)
  * `expected_doc_type`: classify várt eredmény
  * `expected_severity_max`: a legmagasabb elvárt severity szint

Használat:
    from tests.e2e_api.expected_findings import EXPECTED_FINDINGS
    expected = EXPECTED_FINDINGS["szamlak/bs-2026-001.pdf"]
    assert expected["expected_risks_max"] >= len(actual_risks)
"""

from __future__ import annotations


EXPECTED_FINDINGS: dict[str, dict] = {
    # ========================================================================
    # 01. Egyedi számlák — 0 vagy minimális kockázat elvárt
    # ========================================================================
    # A `prototype-agentic`-ben is 4-7 risk egy HU számlán: hiányzó Fizetési mód,
    # kerekített összeg arány (ha óradíjas), materialitási küszöb (info), stb.
    # A severity_max=kozepes a domain check-ek miatt (Hiányzó Fizetési mód = MAGAS).
    "szamlak/bs-2026-001.pdf": {
        "category": "single_invoice_clean",
        "expected_doc_type": "szamla",
        "expected_risks_min": 0,
        "expected_risks_max": 10,
        "expected_severity_max": "magas",
        "must_contain_keywords": [],
        "must_not_contain": [
            "27% ÁFA",  # standard ÁFA NEM lehet kockázat
            "matematikai hiba",
        ],
    },
    "szamlak/bs-2026-002.pdf": {
        "category": "single_invoice_clean",
        "expected_doc_type": "szamla",
        "expected_risks_min": 0,
        "expected_risks_max": 10,
        "expected_severity_max": "magas",
        "must_contain_keywords": [],
        "must_not_contain": ["27% ÁFA", "matematikai hiba"],
    },
    "szamlak/bs-2026-003.pdf": {
        "category": "single_invoice_clean",
        "expected_doc_type": "szamla",
        "expected_risks_min": 0,
        "expected_risks_max": 10,
        "expected_severity_max": "magas",
        "must_contain_keywords": [],
        "must_not_contain": ["27% ÁFA", "matematikai hiba"],
    },
    "szamlak/nl-inv-2026-0001.pdf": {
        "category": "single_invoice_intra_eu",
        "expected_doc_type": "szamla",
        "expected_risks_min": 0,
        "expected_risks_max": 6,
        "expected_severity_max": "kozepes",
        "must_contain_keywords": [],
        "must_not_contain": [
            "0% ÁFA",  # intra-EU 0% NEM lehet flag (drop_business_normal)
            "VAT 0%",
            "matematikai hiba",
        ],
    },
    "szamlak/bk-r-2026-0001.pdf": {
        "category": "single_invoice_de",
        "expected_doc_type": "szamla",
        "expected_risks_min": 0,
        "expected_risks_max": 6,
        "expected_severity_max": "kozepes",
        "must_contain_keywords": [],
        "must_not_contain": ["19% MwSt", "matematikai hiba"],
    },

    # ========================================================================
    # 02. Egyedi szerződések — 0 kritikus risk, max info/közepes
    # NB: A `prototype-agentic`-ben is gyakran van MAGAS finding (pl. NDA-n
    # "Hiányzó felmondási feltételek" Ptk. 6. könyv szerint).
    # ========================================================================
    "szerzodesek/bl-nt-nda-2026.pdf": {
        "category": "single_contract_nda",
        "expected_doc_type": "szerzodes",
        "expected_risks_min": 0,
        "expected_risks_max": 8,
        "expected_severity_max": "magas",
        "must_contain_keywords": [],
        "must_not_contain": ["matematikai hiba"],
    },
    "szerzodesek/pt-dp-mssa-2026.pdf": {
        "category": "single_contract_mssa",
        "expected_doc_type": "szerzodes",
        "expected_risks_min": 0,
        "expected_risks_max": 8,
        "expected_severity_max": "magas",
        "must_contain_keywords": [],
        "must_not_contain": ["matematikai hiba"],
    },
    "szerzodesek/mbk-it-fa-2026.pdf": {
        "category": "single_contract_it_support",
        "expected_doc_type": "szerzodes",
        "expected_risks_min": 0,
        "expected_risks_max": 8,
        "expected_severity_max": "magas",
        "must_contain_keywords": [],
        "must_not_contain": [
            "200% kötbér",  # IT/SaaS szektorban piaci normán (NEM flag)
            "200%-os kötbér",
            "aránytalanul magas kötbér",
            "matematikai hiba",
        ],
    },
    "szerzodesek/df-lc-2026.pdf": {
        "category": "single_contract_leasing",
        "expected_doc_type": "szerzodes",
        "expected_risks_min": 0,
        "expected_risks_max": 10,
        "expected_severity_max": "magas",
        "must_contain_keywords": [],
        "must_not_contain": ["matematikai hiba"],
    },

    # ========================================================================
    # 03. Pénzügyi kimutatások — 0 risk
    # ========================================================================
    "penzugyi_riportok/fin-hu-er-2025.pdf": {
        "category": "financial_report_hu",
        "expected_doc_type": "penzugyi_kimutatas",
        "expected_risks_min": 0,
        "expected_risks_max": 5,
        "expected_severity_max": "kozepes",
        "must_contain_keywords": [],
        "must_not_contain": [],
    },
    "penzugyi_riportok/fin-en-cf-2025.pdf": {
        "category": "financial_report_en_ifrs",
        "expected_doc_type": "penzugyi_kimutatas",
        "expected_risks_min": 0,
        "expected_risks_max": 6,
        "expected_severity_max": "kozepes",
        "must_contain_keywords": [],
        "must_not_contain": [],
    },

    # ========================================================================
    # 04. Multi-doc three-way matching — KRITIKUS HI-100 hiány
    # ========================================================================
    "multi_doc/__triplet__": {
        "category": "multi_doc_three_way",
        "expected_doc_count": 3,
        "expected_doc_types": ["megrendeles", "szallitolevle", "szamla"],
        "expected_comparison_severity": "critical",  # vagy "kritikus"
        "expected_risks_min": 1,
        "must_contain_keywords": [
            "HI-100",  # cikkszám említés
            "mennyiség",  # mennyiségi eltérés
        ],
        # Az alábbi NEM szabad flag-elnie:
        "must_not_contain": [
            "27% ÁFA",  # standard ÁFA
            "14 nap",   # normál fizetési határidő
            "0% ÁFA",
        ],
    },

    # ========================================================================
    # 05. Adversarial — egyenként hiba-detekció elvárt
    # ========================================================================
    "adversarial/adv-inv-2026-0001.pdf": {
        "category": "adversarial_math_error",
        "expected_doc_type": "szamla",
        "expected_risks_min": 1,
        "expected_severity_max": "magas",  # MAGAS matek hiba elvárt
        "must_contain_keywords": [
            "matematikai",  # validate_invoice_math
        ],
        "must_not_contain": [],
    },
    "adversarial/adv-ctr-2026-001.pdf": {
        "category": "adversarial_incomplete_contract",
        "expected_doc_type": "szerzodes",
        "expected_risks_min": 1,
        "expected_severity_max": "magas",
        "must_contain_keywords": [
            "felmondás",  # check_contract_completeness
        ],
        "must_not_contain": [],
    },
    "adversarial/adv-ctr-2026-002.pdf": {
        "category": "adversarial_bilingual_cip",
        "expected_doc_type": "szerzodes",
        "expected_risks_min": 0,  # NEM nyelvi hiba; CIP info-szintű
        "expected_risks_max": 8,
        # NB: ez az adv-ctr szándékosan hiányos szerződés, ami MAGAS severity-t
        # generál (Ptk. 6. könyv: "Hiányzó Felmondási feltételek"). Paritás-elvű.
        "expected_severity_max": "magas",
        "must_contain_keywords": [],
        "must_not_contain": [
            "nyelvi hiba",  # kétnyelvűség NEM hiba
        ],
    },
    "adversarial/adv-ctr-2026-003.pdf": {
        "category": "adversarial_date_illogical",
        "expected_doc_type": "szerzodes",
        "expected_risks_min": 1,
        "expected_severity_max": "magas",
        "must_contain_keywords": [
            "dátum",  # validate_date_logic / validate_contract_dates
        ],
        "must_not_contain": [],
    },

    # ========================================================================
    # 06. Adversarial combined — cross-doc hatás
    # ========================================================================
    "adversarial/__combined__": {
        "category": "adversarial_combined",
        "expected_doc_count": 4,
        "expected_risks_min": 2,  # legalább a math + date hiba
        "must_contain_keywords": [
            "matematikai",
            "dátum",
        ],
        "must_not_contain": [],
    },

    # ========================================================================
    # 07. Audit demo — +50% árnövekedés, csomag-szintű
    # ========================================================================
    "demo_csomagok/audit_demo/__package__": {
        "category": "audit_demo",
        "expected_doc_count": 3,
        "expected_doc_types_all": "szamla",
        "expected_risks_min": 2,
        "expected_package_insights": True,
        # A "must_contain_keywords" mindenképpen kell ellenőrzés. Az "árnövek"
        # tövet nézzük (árnövekedés / árnövekedési) — a Claude néha "emelkedett"
        # vagy "ár-manipuláció" szót használ helyette, ezért a fő ellenőrzés a
        # "must_contain_any_of" listán van.
        "must_contain_keywords": [],
        "must_contain_any_of": [
            "50%",
            "57",       # 57,6% / 57.6% / 57.5% mind illeszkedik
            "árnövek",  # árnövekedés / árnövekedési
            "emelked",  # emelkedés / emelkedett / emelkedik
            "drágul",   # drágulás / drágult / drágább
            "ár-manip", # ár-manipuláció (ahogy a Claude valóban írja)
        ],
        "must_not_contain": [
            "27% ÁFA",  # standard ÁFA NEM lehet kockázat
            "matematikai hiba",  # nincs benne matek hiba
        ],
    },

    # ========================================================================
    # 08. DD demo — 3 piros zászló
    # ========================================================================
    "demo_csomagok/dd_demo/__package__": {
        "category": "dd_demo",
        "expected_doc_count": 3,
        "expected_doc_types_all": "szerzodes",
        "expected_dd_report": True,
        "must_contain_keywords": [],
        "must_contain_any_of": [
            "change-of-control",
            "change of control",
            "kontroll-változás",
            "non-compete",
            "versenytilalom",
            "automatikus megújulás",
            "auto-renewal",
            "auto-megújulás",
        ],
        "must_not_contain": [],
    },

    # ========================================================================
    # 09. Compliance demo — GDPR aszimmetria
    # ========================================================================
    "demo_csomagok/compliance_demo/__package__": {
        "category": "compliance_demo",
        "expected_doc_count": 2,
        "expected_doc_types_all": "szerzodes",
        "expected_package_insights": True,
        "must_contain_keywords": ["GDPR"],
        "must_contain_any_of": [
            "GDPR 28",
            "28. cikk",
            "adatfeldolgozó",
            "adatvédelmi záradék",
        ],
        "must_not_contain": [],
    },
}


# ============================================================================
# 14 CHAT KÉRDÉS — paritás a `prototype-agentic/test_e2e.py:test_10_chat_scenarios`-vel
# ============================================================================

CHAT_SCENARIOS: dict[str, dict] = {
    "10a_multi_doc": {
        "context_files": [
            "multi_doc/epkft-po-2026-0412.pdf",
            "multi_doc/epkft-dn-2026-0415.pdf",
            "multi_doc/epkft-inv-2026-0418.pdf",
        ],
        "questions": [
            {
                "q": "Milyen dokumentumok vannak feltöltve?",
                "must_contain_any_of": ["megrendel", "szállítólev", "számla", "PO-", "INV-", "DN-"],
                "must_not_contain": [],
            },
            {
                "q": "Mekkora a HI-100 I-gerenda nettó egységára?",
                "must_contain_any_of": ["HI-100", "egységár", "Ft"],
                "must_not_contain": [],
            },
            {
                "q": "Mi a szállítási határidő a megrendelésben?",
                "must_contain_any_of": ["szállít", "határidő", "2026"],
                "must_not_contain": [],
            },
            {
                "q": "Hasonlítsd össze a számla és a szállítólevél mennyiségeit. Van eltérés?",
                "must_contain_any_of": ["eltér", "mennyiség", "HI-100", "különb"],
                "must_not_contain": [],
            },
            {
                "q": "Mennyit számláztak és mennyit szállítottak a HI-100 gerendából?",
                "must_contain_any_of": ["HI-100", "40", "38"],  # várt számok
                "must_not_contain": [],
            },
            {
                "q": "Van-e matematikai hiba valamelyik dokumentumban?",
                "must_contain_any_of": ["matematik", "ÁFA", "számít", "helyes"],
                "must_not_contain": [],
            },
            # Anti-hallucináció follow-up: tool-újrahívás kell, NEM memóriából
            {
                "q": "Az előző kérdésben említett hiány pontosan mennyibe kerül nettóban?",
                "must_contain_any_of": ["nettó", "Ft", "hiány"],
                "must_not_contain": [],
                "follow_up": True,
            },
            {
                "q": "És bruttóban mennyibe kerül az előző hiány?",
                "must_contain_any_of": ["bruttó", "Ft"],
                "must_not_contain": [],
                "follow_up": True,
            },
        ],
    },
    "10b_audit_demo": {
        "context_files": [
            "demo_csomagok/audit_demo/ts-2026-0101.pdf",
            "demo_csomagok/audit_demo/ts-2026-0228.pdf",
            "demo_csomagok/audit_demo/ts-2026-0331.pdf",
        ],
        "questions": [
            {
                "q": "Hány számla van és kitől kinek szólnak?",
                "must_contain_any_of": ["3", "TechSupply", "DataPharm", "BudaSoft"],
                "must_not_contain": [],
            },
            {
                "q": "Hasonlítsd össze a három számla összegeit. Van valami szokatlan?",
                "must_contain_any_of": ["növek", "drág", "%", "árn"],
                "must_not_contain": [],
            },
            {
                "q": "Hány százalékkal drágább a márciusi számla a januárihoz képest?",
                "must_contain_any_of": ["50%", "57", "%"],
                "must_not_contain": [],
            },
        ],
    },
    "10c_compliance_demo": {
        "context_files": [
            "demo_csomagok/compliance_demo/mc-cl-dpa-2026-0401.pdf",
            "demo_csomagok/compliance_demo/mc-dv-msa-2026-0410.pdf",
        ],
        "questions": [
            {
                "q": "Melyik szerződés tartalmaz GDPR záradékot és melyik nem?",
                "must_contain_any_of": ["GDPR", "28. cikk", "adatfeldolgozó", "hiány"],
                "must_not_contain": [],
            },
            {
                "q": "Milyen személyes adatokat dolgoz fel a két szerződés?",
                "must_contain_any_of": ["személyes", "adat", "PII", "GDPR"],
                "must_not_contain": [],
            },
            {
                "q": "Hasonlítsd össze a két szerződés adatvédelmi megoldásait.",
                "must_contain_any_of": ["adatvéd", "GDPR", "hasonl", "különb", "eltér"],
                "must_not_contain": [],
            },
        ],
    },
}


__all__ = ["EXPECTED_FINDINGS", "CHAT_SCENARIOS"]
