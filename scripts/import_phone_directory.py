#!/usr/bin/env python3
"""Import phone directory from CSV into the database (CLI).

Usage:
  python scripts/import_phone_directory.py path/to/contacts.csv
  python scripts/import_phone_directory.py contacts.csv --org-id 2 --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from servicesystem.app_factory import create_app
from servicesystem.extensions import db
from servicesystem.models import Organization, PhoneDirectoryContact
from servicesystem.services.directory_import import parse_directory_csv


def _resolve_org_id(row_org: str | None, default_org_id: int) -> int:
    if not row_org:
        return default_org_id
    org = Organization.query.filter(Organization.name.ilike(row_org.strip())).first()
    if org:
        return org.id
    short = row_org.strip().lower()
    org = Organization.query.filter(Organization.short_name.ilike(short)).first()
    if org:
        return org.id
    return default_org_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Import phone directory CSV")
    parser.add_argument("csv_path", type=Path, help="UTF-8 CSV with ; or , delimiter")
    parser.add_argument("--org-id", type=int, default=None, help="Default organization id")
    parser.add_argument("--department", default="Импорт", help="Default department if empty")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no DB writes")
    parser.add_argument("--unpublished", action="store_true", help="Import as drafts")
    args = parser.parse_args()

    raw = args.csv_path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            text = None
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    rows = parse_directory_csv(text, default_department=args.department)
    if not rows:
        print("No rows parsed.", file=sys.stderr)
        return 1

    app = create_app()
    with app.app_context():
        default_org = args.org_id
        if default_org is None:
            inst = Organization.query.filter_by(short_name="belnipi").first()
            default_org = inst.id if inst else Organization.query.order_by(Organization.id).first().id

        print(f"Parsed {len(rows)} rows; default org_id={default_org}")
        if args.dry_run:
            for r in rows[:5]:
                print(f"  - {r.full_name} | {r.department} | {r.organization_name or '(default org)'}")
            if len(rows) > 5:
                print(f"  … and {len(rows) - 5} more")
            return 0

        created = 0
        for r in rows:
            org_id = _resolve_org_id(r.organization_name, default_org)
            db.session.add(
                PhoneDirectoryContact(
                    organization_id=org_id,
                    department=r.department,
                    full_name=r.full_name,
                    position=r.position,
                    phone_internal=r.phone_internal,
                    phone_mobile=r.phone_mobile,
                    email=r.email,
                    is_published=not args.unpublished,
                )
            )
            created += 1
        db.session.commit()
        print(f"Imported {created} contacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
