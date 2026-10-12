"""Work phone + extension as one display string; split on import/save."""
from __future__ import annotations

import re

_EXT_SUFFIX = re.compile(
    r"(.*?)(?:\s*[,;]?\s*(?:доб\.?|д\.|ext\.?|extension|x)\s*[:.]?\s*(\d+)\s*)$",
    re.IGNORECASE,
)
_EXT_ALREADY = re.compile(r"(?:доб\.?|ext\.?|extension)\s*[:.]?\s*\d+", re.IGNORECASE)


def split_work_phone(value: str | None) -> tuple[str | None, str | None]:
    if not value or not str(value).strip():
        return None, None
    s = str(value).strip()
    m = _EXT_SUFFIX.match(s)
    if m:
        main = (m.group(1) or "").strip().rstrip(",;")
        ext = (m.group(2) or "").strip() or None
        return main or None, ext
    return s, None


def format_work_phone(
    phone_internal: str | None,
    phone_extension: str | None = None,
) -> str:
    internal = (phone_internal or "").strip()
    ext = (phone_extension or "").strip()
    if internal and _EXT_ALREADY.search(internal):
        return internal
    if internal and ext:
        return f"{internal} доб. {ext}"
    if internal:
        return internal
    if ext:
        return f"доб. {ext}"
    return ""
