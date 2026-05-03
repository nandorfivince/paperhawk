"""08: GDPR Article 28 — required elements of a data-processing agreement.

10 required elements (GDPR Article 28(3)):
  4 critical: subject and purpose, types of personal data, categories of data
              subjects, sub-processor rules, incident notification
  6 high:     instruction-bound processing, confidentiality, security measures
              (Article 32), deletion/return, audit and inspection rights

The check only runs if the contract text contains a PII indicator.
Schedule/annex escape: if the contract refers to a separate DPA, severity is
reduced.

The 10 elements are aggregated: one risk per severity group, listing the
missing elements.
"""

from __future__ import annotations

from domain_checks.base import make_risk
from graph.states.pipeline_state import Risk


_REGULATION = "GDPR Article 28"


# Required elements with their keyword patterns (multilingual EN/HU/DE)
_GDPR_28_ELEMENTS = [
    ("Subject and purpose of processing", "critical",
     ["subject of processing", "purpose of processing", "processing purpose",
      "adatkezelés tárgya", "adatkezelés célja", "feldolgozás célja",
      "Verarbeitungszweck"]),
    ("Type of personal data", "critical",
     ["type of personal data", "categories of data", "personal data categories",
      "személyes adatok típus", "adatkategória",
      "Art personenbezogener Daten"]),
    ("Categories of data subjects", "critical",
     ["categories of data subjects", "data subject categories",
      "érintettek kategóriái", "érintetti kör",
      "Kategorien der Betroffenen"]),
    ("Instruction-bound processing", "high",
     ["documented instructions", "written instructions", "controller instructions",
      "utasítás alapján", "írásbeli utasítás", "kizárólag az adatkezelő utasítása",
      "auf weisung des verantwortlichen"]),
    ("Confidentiality obligation", "high",
     ["confidentiality", "confidential treatment",
      "titoktartás", "bizalmas kezelés",
      "Vertraulichkeit"]),
    ("Security measures (Article 32)", "high",
     ["security measures", "technical measures", "organizational measures",
      "Article 32", "encryption", "AES",
      "technikai intézkedés", "szervezeti intézkedés", "32. cikk", "titkosítás",
      "technische Maßnahmen", "organisatorische Maßnahmen"]),
    ("Sub-processor rules", "critical",
     ["sub-processor", "subprocessor", "additional processor",
      "al-adatfeldolgozó", "további adatfeldolgozó", "alvállalkozó",
      "Unterauftragsverarbeiter"]),
    ("Deletion / return of data", "high",
     ["deletion", "return of data", "data destruction", "erase",
      "törlés", "visszaszolgáltat", "adatok megsemmisítése",
      "Löschung", "Rückgabe"]),
    ("Audit and inspection rights", "high",
     ["audit right", "inspection right", "audit", "inspection",
      "ellenőrzés", "audit jog", "inspekció", "vizsgálat joga", "felülvizsgálat",
      "Prüfungsrecht"]),
    ("Incident notification", "critical",
     ["breach notification", "data breach", "incident notification", "72 hours",
      "incidens", "adatvédelmi esemény", "72 óra", "bejelentés",
      "Datenschutzverletzung"]),
]

# Personal-data keyword indicators
_PII_INDICATORS = [
    "personal data", "PII", "data subject", "GDPR", "data protection",
    "name", "address", "email", "phone", "income",
    "customer data", "data process",
    "személyes adat", "név", "cím", "telefonszám", "jövedelem",
    "ügyfél adat", "adatfeldolgoz", "adatvédel",
    "personenbezogene Daten", "Datenschutz",
]

# Schedule / annex / separate-DPA references
_SCHEDULE_REFS = [
    "schedule", "annex", "appendix", "DPA", "addendum",
    "data processing addendum", "data processing agreement",
    "melléklet", "függelék", "adatfeldolgozási megállapodás", "adatkezelési melléklet",
    "Anlage", "Anhang",
]


def _text_contains_any(text: str, keywords: list[str]) -> bool:
    """Case-insensitive keyword search."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _get_full_text(extracted: dict) -> str:
    """Concatenate all text content from the extracted dict (for keyword search)."""
    parts: list[str] = []
    # Quotes (the richest text source)
    for q in (extracted.get("_quotes") or extracted.get("quotes") or []):
        if isinstance(q, str):
            parts.append(q)
    # Key clauses
    for kc in (extracted.get("key_clauses") or []):
        if isinstance(kc, dict):
            parts.append(kc.get("name", ""))
            parts.append(kc.get("content", ""))
    # Risk elements
    for re in (extracted.get("risk_elements") or []):
        if isinstance(re, str):
            parts.append(re)
    # Contract type
    parts.append(str(extracted.get("contract_type", "")))
    return " ".join(parts)


class GDPR28Check:
    check_id = "check_08_gdpr_28"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to = {"contract"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []

        full_text = _get_full_text(extracted)

        # First: is there any PII indicator?
        has_pii = _text_contains_any(full_text, _PII_INDICATORS)
        if not has_pii:
            return risks  # Not a data-processing context, not relevant

        # PII detected — check the 10 GDPR Article 28 elements
        missing: list[tuple[str, str]] = []
        for element_name, severity, keywords in _GDPR_28_ELEMENTS:
            if not _text_contains_any(full_text, keywords):
                missing.append((element_name, severity))

        if not missing:
            return risks  # All elements present

        # Schedule/annex escape: severity reduction
        has_schedule_ref = _text_contains_any(full_text, _SCHEDULE_REFS)

        # Group by severity
        critical = [m for m in missing if m[1] == "critical"]
        high = [m for m in missing if m[1] == "high"]

        if has_schedule_ref:
            # Schedule reference present → reduced severity (single combined risk)
            if critical or high:
                all_missing = ", ".join(m[0] for m in missing)
                risks.append(make_risk(
                    description=(
                        f"GDPR Article 28: {len(missing)} element(s) not found in the main "
                        f"text (separate-schedule reference detected)"
                    ),
                    severity="medium",
                    rationale=(
                        f"The contract processes personal data and references a separate "
                        f"schedule/DPA document. The following are not found in the main text: "
                        f"{all_missing}. To be verified in the schedule."
                    ),
                    regulation=_REGULATION,
                    source_check_id=self.check_id,
                ))
        else:
            # No schedule reference → full severity, grouped
            if critical:
                names = ", ".join(m[0] for m in critical)
                risks.append(make_risk(
                    description=(
                        f"GDPR Article 28: {len(critical)} critical element(s) missing "
                        f"from the data-processing agreement"
                    ),
                    severity="high",
                    rationale=(
                        f"The contract involves processing of personal data, but the "
                        f"following GDPR Article 28(3) mandatory elements are missing: "
                        f"{names}."
                    ),
                    regulation=_REGULATION,
                    source_check_id=self.check_id,
                ))

            if high:
                names = ", ".join(m[0] for m in high)
                risks.append(make_risk(
                    description=(
                        f"GDPR Article 28: {len(high)} important element(s) missing "
                        f"from the data-processing agreement"
                    ),
                    severity="medium",
                    rationale=(
                        f"The following GDPR Article 28 elements are not found in the "
                        f"contract: {names}."
                    ),
                    regulation=_REGULATION,
                    source_check_id=self.check_id,
                ))

        return risks
