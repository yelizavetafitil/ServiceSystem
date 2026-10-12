"""Phone directory queries (staff-only internal module)."""
from __future__ import annotations

from sqlalchemy import or_

from servicesystem.models import Organization, PhoneDirectoryContact


def staff_directory_query(*, org_id: int | None = None, q: str | None = None, active_only: bool = True):
    qry = PhoneDirectoryContact.query
    if active_only:
        qry = qry.filter_by(is_active=True)
    if org_id:
        qry = qry.filter(PhoneDirectoryContact.organization_id == org_id)
    if q:
        term = f"%{q.strip()}%"
        qry = qry.filter(
            or_(
                PhoneDirectoryContact.full_name.ilike(term),
                PhoneDirectoryContact.position.ilike(term),
                PhoneDirectoryContact.department.ilike(term),
                PhoneDirectoryContact.email.ilike(term),
                PhoneDirectoryContact.phone_internal.ilike(term),
                PhoneDirectoryContact.phone_mobile.ilike(term),
            )
        )
    return qry.order_by(
        PhoneDirectoryContact.organization_id,
        PhoneDirectoryContact.sort_order,
        PhoneDirectoryContact.full_name,
    )


def customer_organizations_for_filter():
    return (
        Organization.query.join(PhoneDirectoryContact, PhoneDirectoryContact.organization_id == Organization.id)
        .filter(PhoneDirectoryContact.is_active.is_(True))
        .distinct()
        .order_by(Organization.name)
        .all()
    )
