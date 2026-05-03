"""intent_classifier_node — fast regex-based intent recognition.

6 intents: list / extract / search / compare / validate / chat.
LLM-independent, < 1 ms.
"""

from __future__ import annotations

import re
import unicodedata

from graph.states.chat_state import ChatState


def _strip_accents(text: str) -> str:
    """ASCII normalization: strip diacritics (á→a, ő→o, etc.)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# English-first regexes with multilingual (HU) fallback — runs on
# ASCII-normalized text so "ellenőrizd" matches "ellenoriz".
_INTENT_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "compare",
        re.compile(
            r"\b(compar\w*|differ\w*|diff|versus|\bvs\b|cheap\w*|expensiv\w*|"
            r"hasonlit\w*|elter\w*|kulonbs\w*|szembe\w*|drag\w*|olcsobb\w*|mennyivel)\b",
            re.I,
        ),
    ),
    (
        "validate",
        re.compile(
            r"\b(math|error\w*|valid\w*|check|verify|cdv|tax\s*id|consist\w*|correct|"
            r"matek\w*|hib\w*|validal\w*|ellenoriz\w*|adoszam\w*|ervenyes\w*|helyes)\b",
            re.I,
        ),
    ),
    (
        "search",
        re.compile(
            r"\b(search|find|where|contain\w*|penalty|liquid\w*|clause\w*|"
            r"keres\w*|talald|hol|melyik|tartalmaz\w*|szallit\w*|kotber\w*|change|klauz\w*)\b",
            re.I,
        ),
    ),
    (
        "list",
        re.compile(
            r"\b("
            r"(?:what|which)\s+(?:documents?|files?|types?|kinds?|uploads?)|"
            r"how\s*many\s+(?:documents?|files?)|"
            r"list|listazd|listazz|"
            r"file\w*|document\w*|kind|"
            r"milyen|mely|hany|fajl\w*|dokumentum\w*|tipus\w*"
            r")\b",
            re.I,
        ),
    ),
    (
        "extract",
        re.compile(
            r"\b(gross|net|issu\w*|amount\w*|due|date\w*|quantity|total\w*|sum\w*|"
            r"price|cost|unit\s*price|payable|"
            r"brutto\w*|netto\w*|kiallit\w*|allit\w*|bocsat\w*|fizetesi|datum\w*|"
            r"menny\w*|osszeg\w*|vegosszeg\w*|ar\b|ara\b)\b",
            re.I,
        ),
    ),
]


async def intent_classifier_node(state: ChatState) -> dict:
    """Classify based on the last user message."""
    messages = state.get("messages") or []
    last_user_text = ""
    for m in reversed(messages):
        if hasattr(m, "type") and m.type == "human":
            last_user_text = m.content if isinstance(m.content, str) else str(m.content)
            break

    # ASCII normalization (strip accents) so the regexes can match
    # diacritic forms like "ellenőrizd" → "ellenorizd"
    normalized = _strip_accents(last_user_text)
    intent = "chat"
    for label, pattern in _INTENT_RULES:
        if pattern.search(normalized):
            intent = label
            break

    return {
        "intent": intent,
        "trace": [f"intent classifier: {intent}"],
    }
