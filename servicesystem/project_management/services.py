"""Бизнес-логика проектов и задач (ТЗ 1–4)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_

from servicesystem.extensions import db
from servicesystem.models import Contract, Ticket, User
import uuid

from flask import current_app

from servicesystem.project_management.models import (
    Project,
    ProjectCalendarEvent,
    ProjectMember,
    ProjectStage,
    ProjectTask,
    ProjectTaskAttachment,
    ProjectTaskCollaborator,
    ProjectTaskLink,
    TASK_KANBAN_COLUMNS,
)
from servicesystem.services.storage import get_storage

PROJECT_FILE_MAX_BYTES = 100 * 1024 * 1024


def ensure_support_project(contract: Contract) -> Project:
    """ТЗ 1.9: проект техподдержки = договор."""
    proj = Project.query.filter_by(contract_id=contract.id, is_support_project=True).first()
    if proj:
        return proj
    proj = Project(
        contract_id=contract.id,
        name=f"Техподдержка — {contract.number}",
        is_support_project=True,
        planned_start=contract.signed_at,
        deadline=contract.service_end_date,
    )
    db.session.add(proj)
    db.session.flush()
    return proj


def sync_task_from_ticket(ticket: Ticket, *, kanban_status: str | None = None) -> ProjectTask:
    """ТЗ 3.1–3.2: тикет → задача на Kanban."""
    if ticket.project_task:
        task = ticket.project_task
    else:
        proj = ensure_support_project(ticket.contract)
        priority = ticket.priority
        if priority >= 3:
            priority = max(priority, 3)
        task = ProjectTask(
            project_id=proj.id,
            ticket_id=ticket.id,
            title=f"Заявка {ticket.number}: {ticket.subject}",
            description=ticket.description_md,
            priority=priority,
            kanban_status="todo",
            assignee_id=ticket.executor_id,
            due_date=ticket.resolution_deadline.date() if ticket.resolution_deadline else None,
            created_by_id=ticket.auditor_id or ticket.author_id,
        )
        db.session.add(task)
        db.session.flush()
    if kanban_status:
        task.kanban_status = kanban_status
    elif ticket.status == "new":
        task.kanban_status = "todo"
    elif ticket.status == "in_progress":
        task.kanban_status = "in_progress"
    elif ticket.status in ("on_review", "ready"):
        task.kanban_status = "review"
    elif ticket.status in ("resolved", "rejected"):
        task.kanban_status = "done"
    if ticket.executor_id:
        task.assignee_id = ticket.executor_id
    if ticket.priority >= 3:
        task.is_critical_path = True
    return task


def on_ticket_created_hook(ticket: Ticket) -> None:
    sync_task_from_ticket(ticket, kanban_status="todo")


def on_ticket_assign_hook(ticket: Ticket) -> None:
    task = sync_task_from_ticket(ticket, kanban_status="in_progress")
    sync_calendar_events_for_task(task)


def on_ticket_sync_hook(ticket: Ticket) -> None:
    """Синхронизация Kanban при любом изменении статуса тикета (ТЗ 3.1)."""
    task = sync_task_from_ticket(ticket)
    if ticket.priority >= 3:
        task.is_critical_path = True
        task.priority = max(task.priority, ticket.priority)
    if ticket.resolution_deadline:
        task.due_date = ticket.resolution_deadline.date()
    sync_calendar_events_for_task(task)


def update_customer_curator_window(project: Project) -> None:
    """ТЗ 1.3: активность куратора-заказчика = срок проекта + гарантия по договору."""
    end = project.deadline
    if project.contract and project.contract.service_end_date:
        if not end or project.contract.service_end_date > end:
            end = project.contract.service_end_date
    project.customer_curator_active_until = end


def sync_calendar_events_for_task(task: ProjectTask) -> None:
    """ТЗ 3.2: события в календарях ответственного и соисполнителей."""
    user_ids = set()
    if task.assignee_id:
        user_ids.add(task.assignee_id)
    for c in task.collaborators:
        user_ids.add(c.user_id)
    if not user_ids:
        return
    start = task.start_date or date.today()
    end_d = task.due_date or start
    starts_at = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    ends_at = datetime.combine(end_d, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)
    title = task.title[:255]
    for uid in user_ids:
        ev = ProjectCalendarEvent.query.filter_by(task_id=task.id, user_id=uid).first()
        if not ev:
            ev = ProjectCalendarEvent(task_id=task.id, user_id=uid, title=title)
            db.session.add(ev)
        ev.title = title
        ev.starts_at = starts_at
        ev.ends_at = ends_at


def task_is_completion_blocked(task: ProjectTask) -> bool:
    """ТЗ 1.7: блокирующие связи."""
    for link in ProjectTaskLink.query.filter_by(to_task_id=task.id, link_type="blocks"):
        src = db.session.get(ProjectTask, link.from_task_id)
        if src and src.kanban_status != "done":
            return True
    for link in ProjectTaskLink.query.filter_by(from_task_id=task.id, link_type="blocked_by"):
        src = db.session.get(ProjectTask, link.to_task_id)
        if src and src.kanban_status != "done":
            return True
    return False


def kanban_sort_key(task: ProjectTask) -> tuple:
    return (-(task.priority or 0), -(1 if task.is_critical_path else 0), task.kanban_sort, task.id)


def timer_start(task: ProjectTask, user_id: int) -> None:
    if task.timer_running_since:
        return
    task.timer_running_since = datetime.now(timezone.utc)


def timer_stop(task: ProjectTask, user_id: int) -> int:
    if not task.timer_running_since:
        return 0
    now = datetime.now(timezone.utc)
    delta = int((now - task.timer_running_since).total_seconds())
    task.timer_running_since = None
    task.time_spent_seconds = (task.time_spent_seconds or 0) + delta
    from servicesystem.project_management.models import ProjectTimeLog

    db.session.add(ProjectTimeLog(task_id=task.id, user_id=user_id, seconds=delta))
    return delta


def add_manual_time(task: ProjectTask, user_id: int, hours: float, note: str | None = None) -> None:
    from servicesystem.project_management.models import ProjectTimeLog

    sec = int(hours * 3600)
    if sec <= 0:
        return
    task.time_spent_seconds = (task.time_spent_seconds or 0) + sec
    db.session.add(ProjectTimeLog(task_id=task.id, user_id=user_id, seconds=sec, note=note))


def save_task_attachment(task: ProjectTask, file_obj, uploaded_by_id: int) -> ProjectTaskAttachment:
    storage = get_storage()
    storage.ensure_dir("project_tasks", str(task.id))
    orig = file_obj.filename or "file"
    stored = f"{uuid.uuid4().hex}_{orig}"
    rel = f"project_tasks/{task.id}/{stored}"
    size = storage.save_file(rel, file_obj)
    if size > PROJECT_FILE_MAX_BYTES:
        raise ValueError("file_too_large")
    return ProjectTaskAttachment(
        task_id=task.id,
        original_name=orig[:512],
        stored_name=stored,
        mime_type=getattr(file_obj, "mimetype", None),
        size_bytes=size,
        uploaded_by_id=uploaded_by_id,
    )


def save_stage_attachment(stage: ProjectStage, file_obj, uploaded_by_id: int):
    from servicesystem.project_management.models import ProjectStageAttachment

    storage = get_storage()
    storage.ensure_dir("project_stages", str(stage.id))
    orig = file_obj.filename or "file"
    stored = f"{uuid.uuid4().hex}_{orig}"
    rel = f"project_stages/{stage.id}/{stored}"
    size = storage.save_file(rel, file_obj)
    if size > PROJECT_FILE_MAX_BYTES:
        raise ValueError("file_too_large")
    return ProjectStageAttachment(
        stage_id=stage.id,
        original_name=orig[:512],
        stored_name=stored,
        mime_type=getattr(file_obj, "mimetype", None),
        size_bytes=size,
        uploaded_by_id=uploaded_by_id,
    )


def task_attachment_path(att: ProjectTaskAttachment) -> str:
    return f"project_tasks/{att.task_id}/{att.stored_name}"


def delete_task_attachment(att: ProjectTaskAttachment) -> None:
    rel = task_attachment_path(att)
    try:
        get_storage().delete(rel)
    except Exception:
        pass
    db.session.delete(att)


def list_task_attachments(task_id: int) -> list[ProjectTaskAttachment]:
    return (
        ProjectTaskAttachment.query.filter_by(task_id=task_id)
        .order_by(ProjectTaskAttachment.id.desc())
        .all()
    )


def user_can_delete_task_attachment(user: User, task: ProjectTask, att: ProjectTaskAttachment) -> bool:
    if not user_can_view_task(user, task):
        return False
    if user.is_admin or user.is_auditor:
        return True
    if att.verified_at:
        return False
    if att.uploaded_by_id == user.id:
        return True
    return user_can_edit_task(user, task)


def stage_attachment_path(att) -> str:
    return f"project_stages/{att.stage_id}/{att.stored_name}"


def user_can_create_task(user: User, *, parent_id: int | None) -> bool:
    """ТЗ 1.5–1.6: верхний уровень — только аудитор; исполнитель — подзадачи."""
    if not parent_id:
        return user.is_admin or user.is_auditor
    parent = db.session.get(ProjectTask, parent_id)
    if not parent:
        return False
    return user_can_edit_task(user, parent)


def user_can_view_custom_field(user: User, field) -> bool:
    vis = field.visibility or "all"
    if vis == "all":
        return True
    if vis == "auditor":
        return user.is_admin or user.is_auditor
    if vis == "staff":
        return user.is_staff
    return False


def gantt_sla_breach(task: ProjectTask, project: Project | None) -> bool:
    if not project or not project.deadline or not task.due_date:
        return False
    return task.due_date > project.deadline


def build_ics_for_user(user: User) -> str:
    """Экспорт ICS (CalDAV-совместимый фид, ТЗ 3.3)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ServiceSystem//Projects//RU"]
    events = ProjectCalendarEvent.query.filter_by(user_id=user.id).all()
    for ev in events:
        if not ev.starts_at or not ev.ends_at:
            continue
        def _fmt(dt):
            return dt.strftime("%Y%m%dT%H%M%SZ")

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:project-task-{ev.task_id}-{ev.user_id}@servicesystem",
                f"DTSTART:{_fmt(ev.starts_at)}",
                f"DTEND:{_fmt(ev.ends_at)}",
                f"SUMMARY:{ev.title}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def maybe_email_task_reminder(user: User, task: ProjectTask, minutes: int) -> None:
    """Дублирование напоминаний на почту (ТЗ 3.3) — при наличии SMTP."""
    if not current_app.config.get("MAIL_ENABLED"):
        return
    try:
        from servicesystem.services.notify import send_email

        send_email(
            user.email,
            f"Напоминание: {task.title}",
            f"Дедлайн задачи: {task.due_date or '—'}",
        )
    except Exception:
        pass


def tasks_for_user_query(user: User, *, project_id: int | None = None, include_completed: bool = False):
    q = ProjectTask.query
    if not include_completed:
        q = q.filter(ProjectTask.kanban_status != "done")
    if project_id:
        q = q.filter(ProjectTask.project_id == project_id)
    if user.is_auditor or user.is_admin:
        return q
    if user.is_executor:
        collab = db.session.query(ProjectTaskCollaborator.task_id).filter_by(user_id=user.id)
        return q.filter(
            or_(
                ProjectTask.assignee_id == user.id,
                ProjectTask.id.in_(collab),
                ProjectTask.created_by_id == user.id,
            )
        )
    if user.role == "customer_curator":
        proj_ids = db.session.query(Project.id).filter_by(customer_curator_id=user.id)
        return q.filter(ProjectTask.project_id.in_(proj_ids))
    return q.filter(ProjectTask.id == -1)


def move_task_kanban(task: ProjectTask, new_status: str, sort: int = 0) -> None:
    if new_status not in TASK_KANBAN_COLUMNS:
        raise ValueError("invalid status")
    if new_status == "done" and task_is_completion_blocked(task):
        raise ValueError("blocked")
    task.kanban_status = new_status
    task.kanban_sort = sort
    if new_status == "done":
        task.completed_at = datetime.now(timezone.utc)
    else:
        task.completed_at = None


def rollover_overdue_tasks(*, today: date | None = None) -> int:
    """ТЗ 4.1: перенос просроченных на следующий день + счётчик."""
    today = today or date.today()
    moved = 0
    q = ProjectTask.query.filter(
        ProjectTask.due_date.isnot(None),
        ProjectTask.due_date < today,
        ProjectTask.kanban_status.in_(("todo", "in_progress", "review")),
    )
    for task in q:
        task.overdue_days = (task.overdue_days or 0) + 1
        task.due_date = today + timedelta(days=1)
        moved += 1
    return moved


def duplicate_task(
    source: ProjectTask,
    *,
    copy_subtasks: bool = True,
    copy_links: bool = False,
    created_by_id: int,
) -> ProjectTask:
    """ТЗ 4.2."""
    clone = ProjectTask(
        project_id=source.project_id,
        stage_id=source.stage_id,
        title=f"{source.title} (копия)",
        description=source.description,
        priority=source.priority,
        kanban_status="todo",
        assignee_id=source.assignee_id,
        start_date=source.start_date,
        due_date=source.due_date,
        created_by_id=created_by_id,
    )
    db.session.add(clone)
    db.session.flush()
    for c in source.collaborators:
        db.session.add(ProjectTaskCollaborator(task_id=clone.id, user_id=c.user_id))
    if copy_subtasks:
        for sub in ProjectTask.query.filter_by(parent_id=source.id):
            child = duplicate_task(sub, copy_subtasks=False, copy_links=False, created_by_id=created_by_id)
            child.parent_id = clone.id
            child.title = sub.title
    if copy_links:
        for link in source.links_out:
            db.session.add(
                ProjectTaskLink(
                    from_task_id=clone.id,
                    to_task_id=link.to_task_id,
                    link_type=link.link_type,
                )
            )
    return clone


def project_from_template(
    template: Project,
    *,
    name: str,
    contract_id: int | None,
    curator_id: int,
    customer_curator_id: int | None = None,
    planned_start=None,
    deadline=None,
    member_ids: list[int] | None = None,
) -> Project:
    """ТЗ 4.3: этапы, поля, задачи (дерево) и связи между задачами."""
    from servicesystem.project_management.models import ProjectCustomField, ProjectTaskLink

    proj = Project(
        contract_id=contract_id,
        name=name,
        description=template.description,
        planned_start=planned_start or template.planned_start,
        deadline=deadline or template.deadline,
        curator_auditor_id=curator_id,
        customer_curator_id=customer_curator_id,
        template_source_id=template.id,
        is_template=False,
    )
    db.session.add(proj)
    db.session.flush()
    stage_map: dict[int, int] = {}
    for st in template.stages.order_by(ProjectStage.sort_order):
        ns = ProjectStage(
            project_id=proj.id,
            title=st.title,
            deadline=st.deadline,
            responsible_id=st.responsible_id,
            sort_order=st.sort_order,
        )
        db.session.add(ns)
        db.session.flush()
        stage_map[st.id] = ns.id
    for cf in template.custom_fields.order_by(ProjectCustomField.sort_order):
        db.session.add(
            ProjectCustomField(
                project_id=proj.id,
                name=cf.name,
                field_type=cf.field_type,
                visibility=cf.visibility,
                sort_order=cf.sort_order,
            )
        )
    member_ids_set = set(member_ids or [])
    for m in template.members:
        member_ids_set.add(m.user_id)
    for uid in member_ids_set:
        db.session.add(ProjectMember(project_id=proj.id, user_id=uid, role="executor"))
    task_map: dict[int, int] = {}
    for t in ProjectTask.query.filter_by(project_id=template.id, parent_id=None):
        _clone_task_tree(t, proj.id, stage_map, curator_id, task_map)
    template_task_ids = set(task_map.keys())
    if template_task_ids:
        for link in ProjectTaskLink.query.filter(
            ProjectTaskLink.from_task_id.in_(template_task_ids),
            ProjectTaskLink.to_task_id.in_(template_task_ids),
        ):
            nf, nt = task_map.get(link.from_task_id), task_map.get(link.to_task_id)
            if nf and nt:
                db.session.add(
                    ProjectTaskLink(from_task_id=nf, to_task_id=nt, link_type=link.link_type)
                )
    return proj


def _clone_task_tree(
    task: ProjectTask,
    project_id: int,
    stage_map: dict[int, int],
    creator_id: int,
    task_map: dict[int, int],
) -> ProjectTask:
    nt = ProjectTask(
        project_id=project_id,
        stage_id=stage_map.get(task.stage_id) if task.stage_id else None,
        title=task.title,
        description=task.description,
        priority=task.priority,
        kanban_status="todo",
        assignee_id=task.assignee_id,
        start_date=task.start_date,
        due_date=task.due_date,
        created_by_id=creator_id,
    )
    db.session.add(nt)
    db.session.flush()
    task_map[task.id] = nt.id
    for sub in ProjectTask.query.filter_by(parent_id=task.id):
        child = _clone_task_tree(sub, project_id, stage_map, creator_id, task_map)
        child.parent_id = nt.id
    return nt


def user_can_manage_project(user: User, project: Project) -> bool:
    if user.is_admin:
        return True
    if user.is_auditor and project.curator_auditor_id == user.id:
        return True
    return False


def user_can_edit_task(user: User, task: ProjectTask) -> bool:
    if user.is_admin or user.is_auditor:
        return True
    if task.assignee_id == user.id:
        return True
    if task.created_by_id == user.id:
        return True
    return task.collaborators.filter_by(user_id=user.id).first() is not None


def user_can_view_task(user: User, task: ProjectTask) -> bool:
    if user_can_edit_task(user, task):
        return True
    if user.role == "customer_curator" and task.project and task.project.customer_curator_id == user.id:
        return True
    if user.is_auditor:
        return True
    return False
