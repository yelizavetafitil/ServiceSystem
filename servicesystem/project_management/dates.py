"""Разбор дат из форм и JSON."""
from __future__ import annotations

from datetime import date, datetime


def parse_optional_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    return date.fromisoformat(s[:10])
