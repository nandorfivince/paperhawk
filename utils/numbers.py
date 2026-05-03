"""Tolerant number normalization (HU/EU/US/FR formats + 8+ currencies + null aliases).

Examples:
  * "1 234 567" (HU) → 1234567
  * "1.234,56"  (EU) → 1234.56
  * "1,234.56"  (US) → 1234.56
  * "190 500 Ft" → 190500
  * "$1,234"   → 1234
  * "null", "n/a", "none", "-", "—" → None (LLM "missing" indicator)

Every numeric value at the input of a domain check passes through ``coerce_number``.
"""

from __future__ import annotations

import re

# Null aliases — strings the LLM uses to signal "no data"
_NULL_ALIASES = {
    "null", "none", "n/a", "na", "missing",
    "-", "—", "–", "?", "",
    # Multilingual
    "nincs",
    "keine",
}

# Currency suffix patterns (case-insensitive)
_CURRENCY_PATTERN = re.compile(
    r"\s*(USD|EUR|HUF|GBP|CHF|CZK|PLN|RON|JPY|Ft|€|\$|£)\s*$",
    re.I,
)


def is_null_alias(value: str | None) -> bool:
    """True if the value is the LLM's null indicator (no data)."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return value.strip().lower() in _NULL_ALIASES


def coerce_number(value) -> float | None:
    """Tolerant numeric coercion from any-format string, int, or float.

    Returns None if:
      * value is None or a null-alias string
      * value cannot be parsed as a number
    """
    if value is None:
        return None

    if isinstance(value, bool):
        # bool is an int subclass — guard so True != 1, False != 0
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if not isinstance(value, str):
        return None

    s = value.strip()
    if not s or is_null_alias(s):
        return None

    # Strip currency suffix
    s = _CURRENCY_PATTERN.sub("", s).strip()
    # Strip currency prefix (e.g. "$1234")
    s = re.sub(r"^\s*([€$£]|USD|EUR|HUF|GBP|CHF|CZK|PLN|RON|JPY|Ft)\s*", "", s, flags=re.I).strip()

    # Negative parentheses: "(1234)" → "-1234"
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]

    # Strip whitespace (HU thousands separator: "1 234 567")
    s = s.replace(" ", "").replace(" ", "").replace(" ", "")

    if not s or s in {"-", "+"}:
        return None

    # By now we have only digits, ., , and an optional leading +/-
    # Heuristic for separators:
    #   - if both . and , are present, the last one is the decimal,
    #     the others are thousands separators
    #   - if only , is present and ≤ 2 digits follow the last comma → decimal
    #     (otherwise comma is a thousands separator)
    #   - if only . is present and there are multiple . → last is decimal,
    #     the others are thousands

    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_dot > last_comma:
            # 1,234.56 → US: comma=thousands, dot=decimal
            s = s.replace(",", "")
        else:
            # 1.234,56 → EU: dot=thousands, comma=decimal
            s = s.replace(".", "").replace(",", ".")
    elif has_comma:
        last_comma = s.rfind(",")
        if len(s) - last_comma - 1 in {1, 2}:
            s = s[:last_comma].replace(",", "") + "." + s[last_comma + 1 :]
        else:
            s = s.replace(",", "")
    elif has_dot:
        n_dots = s.count(".")
        if n_dots > 1:
            last_dot = s.rfind(".")
            s = s[:last_dot].replace(".", "") + "." + s[last_dot + 1 :]

    try:
        return float(s)
    except ValueError:
        return None
