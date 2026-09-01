import os
import uuid

from flask import request

from servicesystem.extensions import db
from servicesystem.models import AuditLog, TicketHistory


def log_audit(user_id, action, resource_type=None, resource_id=None, details=None):
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=request.remote_addr if request else None,
    )
    db.session.add(entry)
    return entry


def log_ticket_history(ticket_id, user_id, action, old_value=None, new_value=None, details=None):
    entry = TicketHistory(
        ticket_id=ticket_id,
        user_id=user_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
        details=details,
    )
    db.session.add(entry)
    return entry


def ensure_upload_dir(base_path: str, *subdirs) -> str:
    path = os.path.join(base_path, *subdirs)
    os.makedirs(path, exist_ok=True)
    return path


def unique_filename(original: str) -> str:
    ext = os.path.splitext(original)[1].lower()
    return f"{uuid.uuid4().hex}{ext}"
