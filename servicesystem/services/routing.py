"""Ticket routing: assign auditor by object category."""
from servicesystem.models import ObjectCategoryRouting, User


def resolve_auditor(object_category_id: int) -> User | None:
    route = ObjectCategoryRouting.query.filter_by(object_category_id=object_category_id).first()
    if route and route.auditor and route.auditor.is_active:
        return route.auditor
    return User.query.filter_by(role="auditor", is_active=True).order_by(User.id).first()


def resolve_default_executor(object_category_id: int) -> User | None:
    route = ObjectCategoryRouting.query.filter_by(object_category_id=object_category_id).first()
    if route and route.default_executor and route.default_executor.is_active:
        return route.default_executor
    return None
