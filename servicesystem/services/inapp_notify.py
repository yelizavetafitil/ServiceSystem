"""In-app уведомления (заявки / задачи) + всплывающие тосты."""
from __future__ import annotations

from flask import url_for

from servicesystem.extensions import db
from servicesystem.models import UserNotification


def push_notification(
    user_id: int | None,
    *,
    category: str,
    title: str,
    body: str = "",
    link_url: str | None = None,
    is_urgent: bool = False,
    entity_type: str | None = None,
    entity_id: int | None = None,
    exclude_user_id: int | None = None,
) -> UserNotification | None:
    if not user_id:
        return None
    if exclude_user_id and user_id == exclude_user_id:
        return None
    if category not in ("ticket", "task"):
        category = "ticket"
    n = UserNotification(
        user_id=user_id,
        category=category,
        title=(title or "")[:255],
        body=(body or "")[:512],
        link_url=(link_url or "")[:512] or None,
        is_urgent=bool(is_urgent),
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.session.add(n)
    return n


def notify_ticket_event(ticket, *, event: str, actor_id: int | None = None) -> None:
    """Создать in-app уведомления по событию заявки (без commit)."""
    number = ticket.number
    subject = ticket.subject or ""
    urgent = int(ticket.priority or 0) >= 3
    try:
        link = url_for("tickets.detail", tid=ticket.id)
    except RuntimeError:
        link = f"/tickets/{ticket.id}"

    if event == "created":
        push_notification(
            ticket.auditor_id,
            category="ticket",
            title=f"Новая заявка {number}",
            body=subject,
            link_url=link,
            is_urgent=urgent,
            entity_type="ticket",
            entity_id=ticket.id,
            exclude_user_id=actor_id,
        )
    elif event == "assigned":
        push_notification(
            ticket.executor_id,
            category="ticket",
            title=f"Вам назначена заявка {number}",
            body=subject,
            link_url=link,
            is_urgent=urgent,
            entity_type="ticket",
            entity_id=ticket.id,
            exclude_user_id=actor_id,
        )
    elif event == "review":
        push_notification(
            ticket.auditor_id,
            category="ticket",
            title=f"Заявка {number} на проверке",
            body=subject,
            link_url=link,
            is_urgent=True,
            entity_type="ticket",
            entity_id=ticket.id,
            exclude_user_id=actor_id,
        )
    elif event == "ready":
        # Исполнителю — ответ готов к выдаче (информативно).
        push_notification(
            ticket.executor_id,
            category="ticket",
            title=f"Заявка {number} готова к выдаче",
            body=subject,
            link_url=link,
            is_urgent=False,
            entity_type="ticket",
            entity_id=ticket.id,
            exclude_user_id=actor_id,
        )
    elif event == "resolved":
        push_notification(
            ticket.author_id,
            category="ticket",
            title=f"Ответ по заявке {number}",
            body="Опубликован официальный ответ. Откройте заявку в личном кабинете.",
            link_url=link,
            is_urgent=False,
            entity_type="ticket",
            entity_id=ticket.id,
            exclude_user_id=actor_id,
        )
    elif event == "rejected":
        push_notification(
            ticket.author_id,
            category="ticket",
            title=f"Заявка {number} отклонена",
            body=subject,
            link_url=link,
            is_urgent=True,
            entity_type="ticket",
            entity_id=ticket.id,
            exclude_user_id=actor_id,
        )


def task_notification_link(task) -> str:
    """Куда вести из уведомления: зеркало заявки → карточка заявки, иначе задача."""
    try:
        if getattr(task, "ticket_id", None):
            return url_for("tickets.detail", tid=task.ticket_id)
        return url_for("projects.task_detail", tid=task.id)
    except RuntimeError:
        if getattr(task, "ticket_id", None):
            return f"/tickets/{task.ticket_id}"
        return f"/projects/tasks/{task.id}"


def notify_task_assignee(task, *, actor_id: int | None = None, reason: str = "assigned") -> None:
    """Уведомление исполнителю задачи; тост — для срочных (priority ≥ 3)."""
    if not task or not task.assignee_id:
        return
    priority = int(task.priority or 0)
    urgent = priority >= 3
    # Обычные назначения без срочности — только в ленту, без агрессивного тоста.
    link = task_notification_link(task)

    if reason == "rework":
        title = f"Срочная доработка: {task.title}"
        body = "Задача возвращена в работу как срочная."
        urgent = True
    elif reason == "assigned":
        title = f"Вам назначена задача: {task.title}"
        body = "Откройте карточку задачи в АРМ проектов."
    else:
        title = f"Задача: {task.title}"
        body = reason

    push_notification(
        task.assignee_id,
        category="task",
        title=title[:255],
        body=body,
        link_url=link,
        is_urgent=urgent,
        entity_type="task",
        entity_id=task.id,
        exclude_user_id=actor_id,
    )


def resolve_notification_link(n: UserNotification) -> str | None:
    """Актуальная ссылка: для task с ticket_id всегда ведём в заявку."""
    link = n.link_url
    if n.category == "task" and n.entity_type == "task" and n.entity_id:
        try:
            from servicesystem.project_management.models import ProjectTask

            task = ProjectTask.query.get(n.entity_id)
            if task:
                return task_notification_link(task)
        except Exception:
            pass
    if link and link.startswith("/projects/tasks/"):
        try:
            tid = int(link.rstrip("/").split("/")[-1])
            from servicesystem.project_management.models import ProjectTask

            task = ProjectTask.query.get(tid)
            if task and task.ticket_id:
                return f"/tickets/{task.ticket_id}"
        except Exception:
            pass
    return link


def notification_to_dict(n: UserNotification) -> dict:
    return {
        "id": n.id,
        "category": n.category,
        "title": n.title,
        "body": n.body or "",
        "link_url": resolve_notification_link(n),
        "is_urgent": bool(n.is_urgent),
        "is_read": bool(n.is_read),
        "toast_shown": bool(n.toast_shown),
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }
