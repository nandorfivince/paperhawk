"""Date parser and period helpers.

Multi-format support: YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD, DD.MM.YYYY, DD/MM/YYYY.
"""

from __future__ import annotations

from datetime import datetime

from utils.numbers import is_null_alias


_FORMATS = (
    "%Y-%m-%d",
    "%Y.%m.%d",
    "%Y.%m.%d.",
    "%Y/%m/%d",
    "%d.%m.%Y",
    "%d.%m.%Y.",
    "%d/%m/%Y",
)


def parse_date_safe(value) -> datetime | None:
    """Parse a date string in multiple formats. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or is_null_alias(s):
        return None
    # Take the first 10 chars (YYYY-MM-DD-like prefix, possibly trailing .)
    s = s[:10] if len(s) >= 10 else s
    for fmt in _FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def is_expiring_soon(end_date_str: str | None, months: int = 12) -> bool:
    """Check whether the given date expires within the next ``months`` months."""
    end = parse_date_safe(end_date_str)
    if not end:
        return False
    now = datetime.now()
    months_remaining = (end.year - now.year) * 12 + (end.month - now.month)
    return 0 <= months_remaining <= months
