"""vCard 3.0 generation and import (UTF-8, mobile-friendly)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


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
    if phone_internal:
        work = phone_internal.strip()
        if phone_extension and str(phone_extension).strip():
            work = f"{work} ext {str(phone_extension).strip()}"
        lines.append(f"TEL;TYPE=WORK,VOICE:{work}")
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


def _parse_property_block(block: str) -> ParsedVCard | None:
    props: dict[str, list[tuple[str, str]]] = {}
    raw_lines = re.split(r"\r?\n", block.strip())
    merged: list[str] = []
    for line in raw_lines:
        if not line:
            continue
        if line.startswith((" ", "\t")) and merged:
            merged[-1] += line[1:]
        else:
            merged.append(line)

    for line in merged:
        if line.upper().startswith("BEGIN:") or line.upper().startswith("END:"):
            continue
        key_part, _, value = line.partition(":")
        key_upper = key_part.split(";", 1)[0].upper()
        props.setdefault(key_upper, []).append((key_part, _unescape_v3(value)))

    fn = ""
    if "FN" in props and props["FN"]:
        fn = props["FN"][0][1]
    elif "N" in props and props["N"]:
        n_val = props["N"][0][1]
        segs = n_val.split(";")
        family = segs[0] if segs else ""
        given = segs[1] if len(segs) > 1 else ""
        fn = f"{family} {given}".strip()
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
    phone_mobile = None
    for key_part, tel in props.get("TEL", []):
        kp = key_part.upper()
        if "CELL" in kp or "MOBILE" in kp:
            phone_mobile = phone_mobile or tel
        else:
            phone_internal = phone_internal or tel

    email = None
    if "EMAIL" in props and props["EMAIL"]:
        email = props["EMAIL"][0][1] or None

    return ParsedVCard(
        full_name=fn,
        position=position or None,
        organization=organization,
        department=department,
        phone_internal=phone_internal,
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
