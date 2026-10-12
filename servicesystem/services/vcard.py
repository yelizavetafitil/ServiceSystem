"""vCard 3.0 generation and import (UTF-8, mobile-friendly)."""
from __future__ import annotations

import base64
import quopri
import re
from dataclasses import dataclass
from typing import Iterable

from servicesystem.services.phone_format import format_work_phone, split_work_phone


def _escape_v3(value: str) -> str:
    if not value:
        return ""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold_line(line: str, limit: int = 75) -> list[str]:
    if len(line.encode("utf-8")) <= limit:
        return [line]
    out: list[str] = []
    cur = line
    while cur:
        chunk = cur[:limit]
        if len(chunk.encode("utf-8")) > limit:
            while chunk and len(chunk.encode("utf-8")) > limit:
                chunk = chunk[:-1]
        out.append(chunk)
        cur = cur[len(chunk) :]
        if cur:
            cur = " " + cur
    return out


def build_vcard(
    *,
    full_name: str,
    position: str | None = None,
    organization: str | None = None,
    department: str | None = None,
    phone_internal: str | None = None,
    phone_extension: str | None = None,
    phone_mobile: str | None = None,
    email: str | None = None,
) -> str:
    """Build vCard 3.0 text (UTF-8) for QR codes and .vcf download."""
    fn = (full_name or "").strip()
    if not fn:
        raise ValueError("full_name required")

    parts = fn.split()
    if len(parts) >= 2:
        family = parts[0]
        given = " ".join(parts[1:])
    else:
        family = fn
        given = ""

    org_bits = []
    if organization:
        org_bits.append(_escape_v3(organization.strip()))
    if department:
        org_bits.append(_escape_v3(department.strip()))
    org_line = ";".join(org_bits) if org_bits else ""

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{_escape_v3(fn)}",
        f"N:{_escape_v3(family)};{_escape_v3(given)};;;",
    ]
    if position:
        lines.append(f"TITLE:{_escape_v3(position.strip())}")
    if org_line:
        lines.append(f"ORG:{org_line}")
    work = format_work_phone(phone_internal, phone_extension)
    if work:
        lines.append(f"TEL;TYPE=WORK,VOICE:{work.replace(' доб. ', ' ext ')}")
    if phone_mobile:
        lines.append(f"TEL;TYPE=CELL:{phone_mobile.strip()}")
    if email:
        lines.append(f"EMAIL;TYPE=INTERNET:{email.strip().lower()}")
    lines.append("END:VCARD")

    folded: list[str] = []
    for line in lines:
        folded.extend(_fold_line(line))
    return "\r\n".join(folded) + "\r\n"


@dataclass
class ParsedVCard:
    full_name: str
    position: str | None = None
    organization: str | None = None
    department: str | None = None
    phone_internal: str | None = None
    phone_extension: str | None = None
    phone_mobile: str | None = None
    email: str | None = None


def _unescape_v3(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _property_params(key_part: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for piece in key_part.split(";")[1:]:
        if "=" not in piece:
            continue
        k, v = piece.split("=", 1)
        params[k.strip().upper()] = v.strip()
    return params


def _decode_property_value(value: str, params: dict[str, str]) -> str:
    enc = (params.get("ENCODING") or "").upper()
    charset = (params.get("CHARSET") or "utf-8").lower()
    if enc in ("QUOTED-PRINTABLE", "QP"):
        try:
            qp = re.sub(r"=\s*\r?\n", "", value)
            raw = quopri.decodestring(qp.encode("latin-1", errors="replace"))
            value = raw.decode(charset, errors="replace")
        except (ValueError, UnicodeDecodeError):
            pass
    elif enc in ("B", "BASE64"):
        try:
            value = base64.b64decode(value, validate=False).decode(charset, errors="replace")
        except (ValueError, UnicodeDecodeError):
            pass
    return _unescape_v3(value)


_PROPERTY_LINE = re.compile(r"^[A-Za-z][\w-]*(?:;[^:]*)?:")


def _is_property_line(line: str) -> bool:
    return bool(_PROPERTY_LINE.match(line))


def _merge_vcard_physical_lines(raw_lines: Iterable[str]) -> list[str]:
    """Unfold vCard 2.x/3.x lines (space prefix and QP soft breaks)."""
    merged: list[str] = []
    for line in raw_lines:
        if not line:
            continue
        if line.startswith((" ", "\t")) and merged:
            merged[-1] += line[1:]
            continue
        if merged and not _is_property_line(line):
            prev = merged[-1]
            if prev.endswith("="):
                merged[-1] = prev[:-1] + line
            else:
                merged[-1] = prev + line
            continue
        merged.append(line)
    return merged


def _format_name_from_n(n_val: str) -> str:
    segs = n_val.split(";")
    family = (segs[0] if segs else "").strip()
    given = (segs[1] if len(segs) > 1 else "").strip()
    if given and family:
        return f"{given} {family}"
    return (family or given).strip()


def directory_fio_from_n(n_val: str) -> str:
    """vCard N → «Фамилия Имя Отчество» for directory storage and sorting."""
    segs = n_val.split(";")
    parts = [(segs[i] if len(segs) > i else "").strip() for i in range(3)]
    return " ".join(p for p in parts if p).strip()


def repair_quoted_printable_text(text: str | None) -> str:
    """Decode mistaken raw quoted-printable stored in contact fields."""
    if not text or "=" not in text:
        return text or ""
    if re.search(r"[\u0400-\u04FF]", text):
        return text
    if not re.search(r"=(?:[0-9A-Fa-f]{2})+", text):
        return text
    try:
        qp = re.sub(r"=\s*\r?\n", "", text.strip())
        raw = quopri.decodestring(qp.encode("latin-1", errors="replace"))
        decoded = raw.decode("utf-8", errors="replace").strip()
        if decoded:
            return decoded
    except (ValueError, UnicodeDecodeError):
        pass
    return text


def _parse_property_block(block: str) -> ParsedVCard | None:
    props: dict[str, list[tuple[str, str]]] = {}
    raw_lines = re.split(r"\r?\n", block.strip())
    merged = _merge_vcard_physical_lines(raw_lines)

    for line in merged:
        if line.upper().startswith("BEGIN:") or line.upper().startswith("END:"):
            continue
        if not _is_property_line(line):
            continue
        key_part, _, value = line.partition(":")
        key_upper = key_part.split(";", 1)[0].upper()
        if key_upper in ("PHOTO", "LOGO", "SOUND"):
            continue
        params = _property_params(key_part)
        decoded = _decode_property_value(value, params)
        props.setdefault(key_upper, []).append((key_part, decoded))

    fn = ""
    if "N" in props and props["N"]:
        fn = directory_fio_from_n(props["N"][0][1])
    elif "FN" in props and props["FN"]:
        fn = props["FN"][0][1].strip()
    if not fn:
        return None

    position = props.get("TITLE", [[None, ""]])[0][1] or None
    org = props.get("ORG", [[None, ""]])[0][1] or None
    organization = None
    department = None
    if org:
        org_parts = org.split(";")
        organization = org_parts[0] or None
        if len(org_parts) > 1:
            department = org_parts[1] or None

    phone_internal = None
    phone_extension = None
    phone_mobile = None
    for key_part, tel in props.get("TEL", []):
        kp = key_part.upper()
        if "CELL" in kp or "MOBILE" in kp:
            phone_mobile = phone_mobile or tel
        else:
            if not phone_internal:
                phone_internal, phone_extension = split_work_phone(tel)

    email = None
    if "EMAIL" in props and props["EMAIL"]:
        email = props["EMAIL"][0][1] or None

    return ParsedVCard(
        full_name=fn,
        position=position or None,
        organization=organization,
        department=department,
        phone_internal=phone_internal,
        phone_extension=phone_extension,
        phone_mobile=phone_mobile,
        email=email,
    )


def parse_vcf_text(text: str) -> list[ParsedVCard]:
    """Parse one or more vCards from .vcf file contents."""
    if not text:
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"(?i)BEGIN:VCARD", normalized)
    out: list[ParsedVCard] = []
    for block in blocks:
        if "END:VCARD" not in block.upper():
            continue
        chunk = "BEGIN:VCARD" + block.split("END:VCARD", 1)[0] + "END:VCARD"
        parsed = _parse_property_block(chunk)
        if parsed:
            out.append(parsed)
    return out


def safe_vcf_filename(full_name: str, contact_id: int) -> str:
    base = re.sub(r"[^\w\s-]", "", full_name, flags=re.UNICODE).strip().replace(" ", "_")
    if not base:
        base = "contact"
    return f"{base}_{contact_id}.vcf"
