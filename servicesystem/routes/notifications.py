"""API ленты in-app уведомлений (заявки / задачи) и тостов."""
from flask import Blueprint, jsonify, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from servicesystem.extensions import db
from servicesystem.models import Contract, UserNotification
from servicesystem.services.inapp_notify import notification_to_dict

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@bp.route("/feed")
@login_required
def feed():
    """Сводка + новые тосты + последние непрочитанные по категориям."""
    q = UserNotification.query.filter_by(user_id=current_user.id)
    unread_ticket = q.filter_by(category="ticket", is_read=False).count()
    unread_task = (
        UserNotification.query.filter_by(user_id=current_user.id, category="task", is_read=False).count()
    )

    # Тосты: заявки + срочные задачи; свежие сверху, не больше 12 за раз.
    toast_rows = []
    for n in (
        UserNotification.query.filter_by(user_id=current_user.id, toast_shown=False)
        .order_by(UserNotification.id.desc())
        .limit(40)
        .all()
    ):
        if n.category == "ticket" or n.is_urgent:
            toast_rows.append(n)
        if len(toast_rows) >= 12:
            break
    toast_rows.reverse()

    notices = _contract_notices()
    recent_ticket = (
        UserNotification.query.filter_by(user_id=current_user.id, category="ticket")
        .order_by(UserNotification.id.desc())
        .limit(40)
        .all()
    )
    recent_task = (
        UserNotification.query.filter_by(user_id=current_user.id, category="task")
        .order_by(UserNotification.id.desc())
        .limit(40)
        .all()
    )

    max_id = (
        db.session.query(func.max(UserNotification.id))
        .filter(UserNotification.user_id == current_user.id)
        .scalar()
        or 0
    )
    return jsonify(
        {
            "max_id": max_id,
            "unread": {"ticket": unread_ticket + len(notices), "task": unread_task},
            "toasts": [notification_to_dict(n) for n in toast_rows],
            "recent": {
                "ticket": notices + [notification_to_dict(n) for n in recent_ticket],
                "task": [notification_to_dict(n) for n in recent_task],
            },
        }
    )


@bp.route("/ack-toast", methods=["POST"])
@login_required
def ack_toast():
    ids = _parse_ids(request)
    if ids:
        UserNotification.query.filter(
            UserNotification.user_id == current_user.id,
            UserNotification.id.in_(ids),
        ).update({"toast_shown": True}, synchronize_session=False)
        db.session.commit()
    return jsonify({"ok": True})


@bp.route("/mark-read", methods=["POST"])
@login_required
def mark_read():
    data = request.get_json(silent=True) or {}
    category = data.get("category")
    ids = _parse_ids(request)
    q = UserNotification.query.filter_by(user_id=current_user.id, is_read=False)
    if ids:
        q = q.filter(UserNotification.id.in_(ids))
    elif category in ("ticket", "task"):
        q = q.filter_by(category=category)
    else:
        return jsonify({"ok": False, "error": "nothing"}), 400
    q.update({"is_read": True, "toast_shown": True}, synchronize_session=False)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/delete", methods=["POST"])
@login_required
def delete_notifications():
    """Удалить уведомления из ленты (по id или всю категорию)."""
    data = request.get_json(silent=True) or {}
    category = data.get("category")
    ids = _parse_ids(request)
    q = UserNotification.query.filter_by(user_id=current_user.id)
    if ids:
        q = q.filter(UserNotification.id.in_(ids))
    elif category in ("ticket", "task"):
        q = q.filter_by(category=category)
    else:
        return jsonify({"ok": False, "error": "nothing"}), 400
    deleted = q.delete(synchronize_session=False)
    db.session.commit()
    return jsonify({"ok": True, "deleted": deleted})


def _contract_notices() -> list[dict]:
    """Сроки договоров — только в колокольчике, без полосы под шапкой и без тоста."""
    items: list[dict] = []
    user = current_user
    if user.is_customer and user.contract:
        contract = user.contract
        days = contract.days_until_expiry
        end = contract.service_end_date
        if days is not None and end is not None and days <= 30:
            items.append(
                {
                    "id": f"pin-contract-{contract.id}",
                    "category": "ticket",
                    "title": f"Договор {contract.number}",
                    "body": (
                        f"Срок обслуживания истекает {end.strftime('%d.%m.%Y')}. "
                        f"Осталось {days} дн. Для сохранения доступа нужно продление."
                    ),
                    "link_url": url_for("cabinet.dashboard"),
                    "is_urgent": days <= 7,
                    "is_read": False,
                    "pinned": True,
                }
            )
    if user.is_auditor:
        expiring = Contract.query.filter(
            Contract.service_end_date.isnot(None),
            Contract.status.in_(["active_warranty", "active_post_warranty"]),
        ).all()
        for contract in expiring:
            days = contract.days_until_expiry
            if days is None or days > 60:
                continue
            org = contract.organization.name if contract.organization else ""
            items.append(
                {
                    "id": f"pin-contract-{contract.id}",
                    "category": "ticket",
                    "title": f"Договор {contract.number}",
                    "body": (
                        f"{org} — осталось {days} дн. "
                        "Рекомендуется инициировать переговоры о пролонгации техподдержки."
                    ),
                    "link_url": url_for("admin.contract_edit", cid=contract.id)
                    if user.is_admin
                    else url_for("tickets.staff_queue"),
                    "is_urgent": days <= 14,
                    "is_read": False,
                    "pinned": True,
                }
            )
    return items


def _parse_ids(req):
    data = req.get_json(silent=True) or {}
    raw = data.get("ids") or req.form.getlist("ids")
    ids = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    return ids
