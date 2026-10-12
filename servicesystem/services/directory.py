"""Phone directory queries (staff-only internal module)."""
from __future__ import annotations

from sqlalchemy import case, func, or_

from servicesystem.models import Organization, PhoneDirectoryContact


def _surname_sort_key(column):
    """First token of full_name (Фамилия Имя …)."""
    return func.lower(func.trim(func.split_part(column, " ", 1)))


def staff_directory_query(
    *,
    org_id: int | None = None,
    q: str | None = None,
    archived: bool = False,
):
    qry = PhoneDirectoryContact.query.filter_by(is_active=not archived)
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
    manual_rank = case(
        (PhoneDirectoryContact.sort_order > 0, PhoneDirectoryContact.sort_order),
        else_=1_000_000,
    )
    return qry.order_by(
        PhoneDirectoryContact.organization_id,
        manual_rank,
        _surname_sort_key(PhoneDirectoryContact.full_name),
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
