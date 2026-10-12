"""Customer phone directory ↔ user account sync and field-level audit."""
from __future__ import annotations

from servicesystem.extensions import db
from servicesystem.models import PhoneDirectoryContact, User
from servicesystem.services.audit import log_audit

DIRECTORY_FIELDS = (
    "organization_id",
    "full_name",
    "position",
    "phone_internal",
    "phone_extension",
    "phone_mobile",
    "email",
    "department",
)


def contact_for_user(user: User) -> PhoneDirectoryContact | None:
    if not user or not user.id:
        return None
    return PhoneDirectoryContact.query.filter_by(user_id=user.id, is_active=True).first()


def create_contact_from_user(user: User, *, author_id: int | None = None) -> PhoneDirectoryContact:
    org_id = user.organization_id or (user.contract.organization_id if user.contract else None)
    if not org_id:
        raise ValueError("organization required")
    existing = contact_for_user(user)
    if existing:
        return existing
    contact = PhoneDirectoryContact(
        user_id=user.id,
        organization_id=org_id,
        department="",
        full_name=user.full_name,
        position=user.position,
        phone_internal=getattr(user, "phone_work", None) or None,
        phone_extension=getattr(user, "phone_extension", None) or None,
        phone_mobile=user.phone or "",
        email=user.email,
        is_published=True,
        author_id=author_id or user.id,
    )
    db.session.add(contact)
    db.session.flush()
    log_audit(
        author_id or user.id,
        "directory_create",
        "phone_contact",
        contact.id,
        f"auto_register user_id={user.id}; {contact.full_name}",
    )
    return contact


def sync_user_to_contact(user: User) -> PhoneDirectoryContact:
    contact = contact_for_user(user)
    if not contact:
        return create_contact_from_user(user)
    old = {f: getattr(contact, f) for f in DIRECTORY_FIELDS}
    org_id = user.organization_id or (user.contract.organization_id if user.contract else contact.organization_id)
    contact.organization_id = org_id
    contact.full_name = user.full_name
    contact.position = user.position
    contact.phone_internal = getattr(user, "phone_work", None) or None
    contact.phone_extension = getattr(user, "phone_extension", None) or None
    contact.phone_mobile = user.phone or contact.phone_mobile
    contact.email = user.email
    new = {f: getattr(contact, f) for f in DIRECTORY_FIELDS}
    log_directory_field_changes(user.id, contact.id, old, new)
    return contact


def sync_contact_to_user(contact: PhoneDirectoryContact) -> None:
    if not contact.user_id:
        return
    user = db.session.get(User, contact.user_id)
    if not user:
        return
    user.full_name = contact.full_name
    user.position = contact.position or user.position
    user.phone = contact.phone_mobile or user.phone
    if hasattr(user, "phone_work"):
        user.phone_work = contact.phone_internal
    if hasattr(user, "phone_extension"):
        user.phone_extension = contact.phone_extension
    user.email = contact.email


def log_directory_field_changes(user_id: int, contact_id: int, old: dict, new: dict) -> None:
    labels = {
        "organization_id": "организация",
        "full_name": "ФИО",
        "position": "должность",
        "phone_internal": "рабочий телефон",
        "phone_extension": "добавочный",
        "phone_mobile": "мобильный",
        "email": "email",
        "department": "подразделение",
    }
    for key in DIRECTORY_FIELDS:
        ov, nv = old.get(key), new.get(key)
        if str(ov or "") == str(nv or ""):
            continue
        log_audit(
            user_id,
            "directory_update",
            "phone_contact",
            contact_id,
            f"{labels.get(key, key)}: «{ov}» → «{nv}»",
        )


def snapshot_contact(contact: PhoneDirectoryContact) -> dict:
    return {f: getattr(contact, f) for f in DIRECTORY_FIELDS}
