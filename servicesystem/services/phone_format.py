"""Work phone + extension as one display string; split on import/save."""
from __future__ import annotations

import re

_DIGITS = re.compile(r"\D")

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


def normalize_mobile_phone_key(phone: str | None) -> str | None:
    """Digits-only key for duplicate checks (BY/RU mobiles, different formatting).

    Strips country/trunk prefixes so +375 29 …, 8029… and 29 … match; +7 …, 8 … and 9… (10 digits) match.
    """
    if not phone or not str(phone).strip():
        return None
    raw = str(phone).strip()
    if raw in ("—", "-", "–"):
        return None
    digits = _DIGITS.sub("", raw)
    if not digits:
        return None
    if digits.startswith("375") and len(digits) >= 12:
        return digits[3:12]
    if len(digits) == 11 and digits.startswith("80"):
        return digits[2:]
    if len(digits) == 11 and digits[0] in "78":
        return digits[1:]
    return digits


def mobile_keys_match(a: str | None, b: str | None) -> bool:
    ka, kb = normalize_mobile_phone_key(a), normalize_mobile_phone_key(b)
    if not ka or not kb:
        return False
    if len(ka) < 9 or len(kb) < 9:
        return False
    return ka == kb
