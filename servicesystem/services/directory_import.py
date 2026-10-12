"""Bulk import phone directory rows from CSV (legacy Excel exports)."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass


@dataclass
class DirectoryImportRow:
    full_name: str
    department: str
    position: str | None = None
    phone_internal: str | None = None
    phone_mobile: str | None = None
    email: str | None = None
    organization_name: str | None = None


_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "full_name": ("full_name", "fio", "фио", "имя", "контакт", "сотрудник"),
    "department": ("department", "подразделение", "отдел", "служба", "управление"),
    "position": ("position", "должность", "должн"),
    "phone_internal": (
        "phone_internal",
        "internal",
        "tel",
        "phone",
        "телефон",
        "внутренний",
        "рабочий",
        "городской",
        "тел",
    ),
    "phone_mobile": ("phone_mobile", "mobile", "мобильный", "сот", "моб"),
    "email": ("email", "e-mail", "e_mail", "почта", "mail"),
    "organization_name": ("organization", "org", "организация", "предприятие", "руп", "гпо"),
}


def _norm_header(value: str) -> str:
    key = (value or "").strip().lower().replace("\ufeff", "")
    key = re.sub(r"\s+", " ", key)
    return key


def _map_headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        return {}
    mapping: dict[str, str] = {}
    for raw in fieldnames:
        norm = _norm_header(raw)
        if not norm:
            continue
        for target, aliases in _HEADER_ALIASES.items():
            if norm in aliases or any(norm.startswith(a + " ") for a in aliases):
                mapping[target] = raw
                break
    return mapping


def _cell(row: dict[str, str | None], mapping: dict[str, str], key: str) -> str:
    col = mapping.get(key)
    if not col:
        return ""
    return (row.get(col) or "").strip()


def parse_directory_csv(
    text: str,
    *,
    default_department: str = "Импорт",
    delimiter: str | None = None,
) -> list[DirectoryImportRow]:
    """Parse CSV/TSV; first row must be headers (RU or EN)."""
    if not text or not text.strip():
        return []
    sample = text[:4096]
    if delimiter is None:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    mapping = _map_headers(reader.fieldnames)
    if "full_name" not in mapping:
        raise ValueError(
            "Не найдена колонка ФИО. Нужен заголовок вроде: full_name, ФИО, Имя."
        )

    out: list[DirectoryImportRow] = []
    for row in reader:
        if not row:
            continue
        name = _cell(row, mapping, "full_name")
        if not name or name.startswith("#"):
            continue
        dept = _cell(row, mapping, "department") or default_department
        email = _cell(row, mapping, "email").lower() or None
        if email and "@" not in email:
            email = None
        out.append(
            DirectoryImportRow(
                full_name=name,
                department=dept,
                position=_cell(row, mapping, "position") or None,
                phone_internal=_cell(row, mapping, "phone_internal") or None,
                phone_mobile=_cell(row, mapping, "phone_mobile") or None,
                email=email,
                organization_name=_cell(row, mapping, "organization_name") or None,
            )
        )
    return out
