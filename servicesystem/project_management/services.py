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
    from sqlalchemy.exc import IntegrityError

    # Ищем по ticket_id явно: backref может быть ещё не подхвачен после assign_hook в том же запросе
    task = ProjectTask.query.filter_by(ticket_id=ticket.id).first()
    if not task and ticket.project_task:
        task = ticket.project_task
    if not task:
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
            gantt_sort=next_gantt_sort(proj.id),
            assignee_id=ticket.executor_id,
            due_date=ticket.resolution_deadline.date() if ticket.resolution_deadline else None,
            created_by_id=ticket.auditor_id or ticket.author_id,
        )
        db.session.add(task)
        try:
            with db.session.begin_nested():
                db.session.flush()
        except IntegrityError:
            # Гонка/повторный sync: задача с этим ticket_id уже есть
            task = ProjectTask.query.filter_by(ticket_id=ticket.id).first()
            if not task:
                raise
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
    """Задача в канбане создаётся только после назначения исполнителя (не при создании заявки)."""
    return


def on_ticket_assign_hook(ticket: Ticket) -> None:
    if not ticket.executor_id:
        return
    task = sync_task_from_ticket(ticket, kanban_status="in_progress")
    sync_calendar_events_for_task(task)


def on_ticket_sync_hook(ticket: Ticket) -> None:
    """Синхронизация Kanban при изменении статуса — только если задача уже есть или есть исполнитель."""
    if not ticket.project_task and not ticket.executor_id:
        return
    task = sync_task_from_ticket(ticket)
    if ticket.priority >= 3:
        task.is_critical_path = True
        task.priority = max(task.priority, ticket.priority)
    if ticket.resolution_deadline:
        task.due_date = ticket.resolution_deadline.date()
    sync_calendar_events_for_task(task)


def task_opens_as_ticket(task: ProjectTask) -> bool:
    """Задача-зеркало заявки всегда открывается в форме тикета (Гант, карточка, ссылки)."""
    return bool(task.ticket_id and task.ticket)


def user_can_view_gantt(user: User) -> bool:
    """Диаграмма Ганта — только ГИП (auditor) и admin."""
    return bool(user and (user.is_admin or user.is_auditor))


def user_can_view_week_calendar(user: User) -> bool:
    """Просмотр недели и календаря — admin, auditor и executor (без прав на Гант)."""
    return bool(user and (user.is_admin or user.is_auditor or user.is_executor))


def user_can_reschedule_gantt(user: User, task: ProjectTask | None = None) -> bool:
    """Сроки на Ганте двигают только admin/auditor."""
    return user_can_view_gantt(user)


def update_customer_curator_window(project: Project) -> None:
    """ТЗ 1.3: окно активности куратора + доступ по договору.

    Назначение заказчика куратором проекта означает:
    - роль customer_curator (доступ в ЛК проектов);
    - статус «Подключён» (is_active);
    - договор активен и срок обслуживания не короче окна куратора.
    """
    end = project.deadline
    if project.contract and project.contract.service_end_date:
        if not end or project.contract.service_end_date > end:
            end = project.contract.service_end_date
    if not end and project.planned_start:
        end = project.planned_start
    project.customer_curator_active_until = end

    curator = None
    if project.customer_curator_id:
        curator = db.session.get(User, project.customer_curator_id)
    if not curator and getattr(project, "customer_curator", None):
        curator = project.customer_curator
    if not curator:
        return

    # Роль куратора-заказчика и доступ «Подключён»
    if curator.role in ("customer", "customer_curator"):
        curator.role = "customer_curator"
    curator.is_active = True

    contract = curator.contract or project.contract
    if not contract:
        return

    # Договор открыт для работы: активный статус + продление срока при необходимости
    if contract.status in ("suspended", "terminated") or (
        contract.is_expired and contract.status in ("active_warranty", "active_post_warranty")
    ):
        # Сохраняем постгарантию, если уже была; иначе гарантия
        if contract.status != "active_post_warranty":
            contract.status = "active_warranty"
    if end and (not contract.service_end_date or contract.service_end_date < end):
        contract.service_end_date = end
        if contract.master_key_expires_at and contract.master_key_expires_at < end:
            contract.master_key_expires_at = end
        elif not contract.master_key_expires_at:
            contract.master_key_expires_at = end


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


def _fs_predecessor_tasks(task: ProjectTask) -> list[ProjectTask]:
    preds: list[ProjectTask] = []
    for link in ProjectTaskLink.query.filter_by(to_task_id=task.id, link_type="blocks"):
        src = db.session.get(ProjectTask, link.from_task_id)
        if src:
            preds.append(src)
    for link in ProjectTaskLink.query.filter_by(from_task_id=task.id, link_type="blocked_by"):
        src = db.session.get(ProjectTask, link.to_task_id)
        if src:
            preds.append(src)
    return preds


def _fs_successor_tasks(task: ProjectTask) -> list[ProjectTask]:
    succs: list[ProjectTask] = []
    for link in ProjectTaskLink.query.filter_by(from_task_id=task.id, link_type="blocks"):
        dst = db.session.get(ProjectTask, link.to_task_id)
        if dst:
            succs.append(dst)
    for link in ProjectTaskLink.query.filter_by(to_task_id=task.id, link_type="blocked_by"):
        dst = db.session.get(ProjectTask, link.from_task_id)
        if dst:
            succs.append(dst)
    return succs


def enforce_task_fs_start(task: ProjectTask) -> bool:
    """FS: начало не раньше дня после предшественника; выходные/праздники пропускаются."""
    from servicesystem.project_management.work_calendar import (
        add_workday_steps,
        project_uses_work_calendar,
        snap_to_workday,
        workday_steps,
    )

    ends = [p.due_date for p in _fs_predecessor_tasks(task) if p.due_date]
    if not ends:
        return _snap_task_dates_to_workdays(task)
    project = task.project
    min_start = max(ends) + timedelta(days=1)
    if project_uses_work_calendar(project):
        min_start = snap_to_workday(min_start, project)
    cur_start = task.start_date or task.due_date
    if cur_start is None:
        task.start_date = min_start
        task.due_date = min_start
        return True
    if cur_start >= min_start:
        # Даже если FS уже соблюдён — сдвинуть с выходного/праздника
        if project_uses_work_calendar(project):
            return _snap_task_dates_to_workdays(task)
        return False
    if task.start_date and task.due_date:
        if project_uses_work_calendar(project):
            duration_days = workday_steps(task.start_date, task.due_date, project)
        else:
            duration_days = max(0, (task.due_date - task.start_date).days)
    else:
        duration_days = 0
    task.start_date = min_start
    if project_uses_work_calendar(project):
        task.due_date = add_workday_steps(min_start, duration_days, project)
    else:
        task.due_date = min_start + timedelta(days=duration_days)
    return True


def _snap_task_dates_to_workdays(task: ProjectTask) -> bool:
    """Если даты попали на выходной/праздник — сдвинуть вперёд на рабочий день."""
    from servicesystem.project_management.work_calendar import (
        add_workday_steps,
        project_uses_work_calendar,
        snap_to_workday,
        workday_steps,
    )

    project = task.project
    if not project_uses_work_calendar(project):
        return False
    changed = False
    old_start, old_due = task.start_date, task.due_date
    if task.start_date and task.due_date:
        steps = workday_steps(task.start_date, task.due_date, project)
        new_start = snap_to_workday(task.start_date, project)
        new_due = add_workday_steps(new_start, steps, project)
        new_due = snap_to_workday(new_due, project)
        if new_start != task.start_date or new_due != task.due_date:
            task.start_date = new_start
            task.due_date = new_due
            changed = True
    else:
        if task.start_date:
            ns = snap_to_workday(task.start_date, project)
            if ns != task.start_date:
                task.start_date = ns
                changed = True
        if task.due_date:
            nd = snap_to_workday(task.due_date, project)
            if nd != task.due_date:
                task.due_date = nd
                changed = True
    if task.start_date and task.due_date and task.due_date < task.start_date:
        task.due_date = task.start_date
        changed = True
    return changed or (old_start, old_due) != (task.start_date, task.due_date)


def _fs_move_task_with_subtree(task: ProjectTask) -> list[int]:
    """FS/snap задачи и сдвиг всех подзадач на тот же delta (как drag на Ганте)."""
    old_start = task.start_date or task.due_date
    if not (enforce_task_fs_start(task) or _snap_task_dates_to_workdays(task)):
        return []
    changed = [task.id]
    sync_calendar_events_for_task(task)
    new_start = task.start_date or task.due_date
    if old_start and new_start:
        delta = (new_start - old_start).days
        if delta:
            for cid in shift_task_subtree(task, delta):
                if cid not in changed:
                    changed.append(cid)
    return changed


def cascade_fs_schedule(root: ProjectTask) -> list[int]:
    """Применить FS к задаче и цепочке последователей. Возвращает id изменённых задач."""
    changed: list[int] = []
    visited: set[int] = set()
    queue: list[ProjectTask] = [root]
    while queue:
        task = queue.pop(0)
        if task.id in visited:
            continue
        visited.add(task.id)
        for tid in _fs_move_task_with_subtree(task):
            if tid not in changed:
                changed.append(tid)
        for pid in expand_ancestors_to_fit(task):
            if pid not in changed:
                changed.append(pid)
        for succ in _fs_successor_tasks(task):
            if succ.id not in visited:
                queue.append(succ)
    return changed


def cascade_fs_successors_only(task: ProjectTask) -> list[int]:
    """Сдвинуть только последователей FS (саму задачу не откатывать к предшественникам/выходным)."""
    changed: list[int] = []
    for succ in _fs_successor_tasks(task):
        changed.extend(cascade_fs_schedule(succ))
    return changed


def cascade_fs_from_task(task: ProjectTask) -> list[int]:
    """После сдвига сроков: подтянуть саму задачу к предшественникам и сдвинуть последователей."""
    changed = list(_fs_move_task_with_subtree(task))
    for succ in _fs_successor_tasks(task):
        for tid in cascade_fs_schedule(succ):
            if tid not in changed:
                changed.append(tid)
    # После FS снова уложить в окна родителя и старт проекта
    if clamp_task_dates(task):
        if task.id not in changed:
            changed.append(task.id)
        sync_calendar_events_for_task(task)
    for child in iter_task_descendants(task):
        if clamp_task_dates(child):
            if child.id not in changed:
                changed.append(child.id)
            sync_calendar_events_for_task(child)
    for pid in expand_ancestors_to_fit(task):
        if pid not in changed:
            changed.append(pid)
    return changed


def parent_date_window(parent: ProjectTask | None) -> tuple[date | None, date | None]:
    """Окно сроков родителя (min_start, max_due) или (None, None)."""
    if not parent:
        return None, None
    p_start = parent.start_date or parent.due_date
    p_due = parent.due_date or parent.start_date
    if not p_start or not p_due:
        return None, None
    if p_due < p_start:
        p_start, p_due = p_due, p_start
    return p_start, p_due


def dates_within_parent(
    start: date | None,
    due: date | None,
    parent: ProjectTask | None,
) -> bool:
    """True, если сроки пустые/без окна родителя или целиком внутри родителя."""
    p_start, p_due = parent_date_window(parent)
    if not p_start or not p_due:
        return True
    if start and (start < p_start or start > p_due):
        return False
    if due and (due < p_start or due > p_due):
        return False
    return True


def clamp_dates_to_parent(
    start: date | None,
    due: date | None,
    parent: ProjectTask | None,
    project: Project | None = None,
) -> tuple[date | None, date | None]:
    """Подрезать start/due под окно родителя (длительность по возможности сохранить)."""
    from servicesystem.project_management.work_calendar import (
        add_workday_steps,
        project_uses_work_calendar,
        sub_workday_steps,
        workday_steps,
    )

    p_start, p_due = parent_date_window(parent)
    if not p_start or not p_due:
        return start, due
    if start and due and due < start:
        start, due = due, start
    if start is None and due is None:
        return start, due
    if start is None:
        start = due
    if due is None:
        due = start
    assert start is not None and due is not None
    proj = project or (parent.project if parent else None)
    use_wc = project_uses_work_calendar(proj)
    if use_wc:
        span = workday_steps(start, due, proj)
        window = workday_steps(p_start, p_due, proj)
        if span > window:
            return p_start, p_due
        if start < p_start:
            start = p_start
            due = add_workday_steps(start, span, proj)
        if due > p_due:
            due = p_due
            start = sub_workday_steps(due, span, proj)
            if start < p_start:
                start = p_start
        return start, due
    span = max(0, (due - start).days)
    window = max(0, (p_due - p_start).days)
    if span > window:
        return p_start, p_due
    if start < p_start:
        start = p_start
        due = start + timedelta(days=span)
    if due > p_due:
        due = p_due
        start = due - timedelta(days=span)
        if start < p_start:
            start = p_start
    return start, due


def clamp_task_dates_to_parent(task: ProjectTask) -> bool:
    """Уложить сроки задачи в окно родителя. True если изменилось."""
    if not task.parent_id:
        return False
    parent = task.parent
    if parent is None and task.parent_id:
        parent = db.session.get(ProjectTask, task.parent_id)
    project = task.project
    if project is None and task.project_id:
        project = db.session.get(Project, task.project_id)
    old_s, old_d = task.start_date, task.due_date
    ns, nd = clamp_dates_to_parent(task.start_date, task.due_date, parent, project=project)
    if (ns, nd) == (old_s, old_d):
        return False
    task.start_date, task.due_date = ns, nd
    return True


def is_task_ancestor(ancestor: ProjectTask, descendant: ProjectTask) -> bool:
    """True, если ancestor выше descendant в иерархии parent_id."""
    if not ancestor or not descendant or ancestor.id == descendant.id:
        return False
    cur = descendant
    seen: set[int] = set()
    while cur and cur.parent_id:
        if cur.parent_id in seen:
            break
        seen.add(cur.parent_id)
        if cur.parent_id == ancestor.id:
            return True
        cur = cur.parent if cur.parent is not None else db.session.get(ProjectTask, cur.parent_id)
    return False


def tasks_hierarchically_related(a: ProjectTask | None, b: ProjectTask | None) -> bool:
    """Родитель ↔ подзадача (любой глубины): такие пары нельзя связывать FS."""
    if not a or not b or a.id == b.id:
        return False
    return is_task_ancestor(a, b) or is_task_ancestor(b, a)


def forecast_fs_dates_after_predecessor(
    succ: ProjectTask,
    pred: ProjectTask,
) -> tuple[date | None, date | None]:
    """start/due последователя после FS от pred (без записи в БД)."""
    from servicesystem.project_management.work_calendar import (
        add_workday_steps,
        project_uses_work_calendar,
        snap_to_workday,
        workday_steps,
    )

    pred_due = pred.due_date or pred.start_date
    if not pred_due:
        return succ.start_date, succ.due_date
    other_ends = [
        p.due_date
        for p in _fs_predecessor_tasks(succ)
        if p.due_date and p.id != pred.id
    ]
    min_start = max(other_ends + [pred_due]) + timedelta(days=1)
    project = succ.project
    if project_uses_work_calendar(project):
        min_start = snap_to_workday(min_start, project)
    cur_start = succ.start_date or succ.due_date
    if cur_start is None:
        return min_start, min_start
    if cur_start >= min_start:
        return succ.start_date, succ.due_date
    if succ.start_date and succ.due_date:
        if project_uses_work_calendar(project):
            duration_days = workday_steps(succ.start_date, succ.due_date, project)
        else:
            duration_days = max(0, (succ.due_date - succ.start_date).days)
    else:
        duration_days = 0
    new_start = min_start
    if project_uses_work_calendar(project):
        new_due = add_workday_steps(new_start, duration_days, project)
    else:
        new_due = new_start + timedelta(days=duration_days)
    return new_start, new_due


def expand_ancestors_to_fit(task: ProjectTask) -> list[int]:
    """Расширить сроки родителей (вверх по цепочке), чтобы покрыть задачу.

    Нужно после FS между подзадачами: родитель = совокупность подзадач.
    """
    changed: list[int] = []
    cur = task
    guard = 0
    while cur and cur.parent_id and guard < 40:
        guard += 1
        parent = cur.parent if cur.parent is not None else db.session.get(ProjectTask, cur.parent_id)
        if not parent:
            break
        t_start = cur.start_date or cur.due_date
        t_due = cur.due_date or cur.start_date
        if not t_start and not t_due:
            cur = parent
            continue
        dirty = False
        if t_start and (parent.start_date is None or parent.start_date > t_start):
            parent.start_date = t_start
            dirty = True
        if t_due and (parent.due_date is None or parent.due_date < t_due):
            parent.due_date = t_due
            dirty = True
        if parent.start_date and parent.due_date and parent.due_date < parent.start_date:
            parent.due_date = parent.start_date
            dirty = True
        if dirty:
            if parent.id not in changed:
                changed.append(parent.id)
            sync_calendar_events_for_task(parent)
        cur = parent
    return changed


def apply_fs_cascade_and_expand(succ: ProjectTask) -> list[int]:
    """FS-каскад по последователю + расширение родителей под новые сроки."""
    shifted = cascade_fs_schedule(succ)
    ids = list(shifted)
    if succ.id not in ids:
        ids.append(succ.id)
    out = list(shifted)
    for tid in ids:
        t = succ if tid == succ.id else db.session.get(ProjectTask, tid)
        if not t:
            continue
        for pid in expand_ancestors_to_fit(t):
            if pid not in out:
                out.append(pid)
    return out


def fs_link_parent_window_violation(
    pred: ProjectTask,
    succ: ProjectTask,
) -> str | None:
    """
    Перед FS-связью: нельзя выйти за окно проекта.
    Окно родителя не блокирует связь подзадач — после каскада родителя расширяем
    (родитель = совокупность подзадач).
    """
    new_start, new_due = forecast_fs_dates_after_predecessor(succ, pred)
    proj_msg = project_dates_violation_message(new_start, new_due, succ.project)
    if proj_msg:
        return proj_msg
    return None


def project_earliest_start(project: Project | None) -> date | None:
    """Старт проекта — нижняя граница сроков задач."""
    if not project:
        return None
    return getattr(project, "planned_start", None) or None


def project_latest_due(project: Project | None) -> date | None:
    """Крайний срок проекта — верхняя граница сроков задач."""
    if not project:
        return None
    return getattr(project, "deadline", None) or None


def dates_within_project(
    start: date | None,
    due: date | None,
    project: Project | None,
) -> bool:
    """True, если сроки внутри окна проекта (старт…дедлайн)."""
    floor = project_earliest_start(project)
    ceil = project_latest_due(project)
    if floor:
        if start and start < floor:
            return False
        if due and due < floor:
            return False
    if ceil:
        if start and start > ceil:
            return False
        if due and due > ceil:
            return False
    return True


def clamp_dates_to_project(
    start: date | None,
    due: date | None,
    project: Project | None,
) -> tuple[date | None, date | None]:
    """Уложить сроки в окно проекта (не раньше старта, не позже дедлайна)."""
    from servicesystem.project_management.work_calendar import (
        add_workday_steps,
        project_uses_work_calendar,
        sub_workday_steps,
        workday_steps,
    )

    floor = project_earliest_start(project)
    ceil = project_latest_due(project)
    if not floor and not ceil:
        return start, due
    if start and due and due < start:
        start, due = due, start
    if start is None and due is None:
        return start, due
    if start is None:
        start = due
    if due is None:
        due = start
    assert start is not None and due is not None
    use_wc = project_uses_work_calendar(project)
    if use_wc:
        span = workday_steps(start, due, project)
        if floor and start < floor:
            start = floor
            due = add_workday_steps(start, span, project)
        if ceil and due > ceil:
            due = ceil
            start = sub_workday_steps(due, span, project)
            if floor and start < floor:
                start = floor
                due = ceil if ceil >= floor else floor
        if floor and start < floor:
            start = floor
        if ceil and due > ceil:
            due = ceil
        if start > due:
            start = due
        return start, due
    span = max(0, (due - start).days)
    if floor and start < floor:
        start = floor
        due = start + timedelta(days=span)
    if ceil and due > ceil:
        due = ceil
        start = due - timedelta(days=span)
        if floor and start < floor:
            start = floor
            due = ceil if ceil >= floor else floor
        elif start > due:
            start = due
    if floor and start < floor:
        start = floor
    if ceil and due > ceil:
        due = ceil
    if start > due:
        start = due
    return start, due


def clamp_task_dates_to_project(task: ProjectTask) -> bool:
    """Внутри окна проекта. True если изменилось."""
    project = task.project
    if project is None and task.project_id:
        project = db.session.get(Project, task.project_id)
    old_s, old_d = task.start_date, task.due_date
    ns, nd = clamp_dates_to_project(task.start_date, task.due_date, project)
    if (ns, nd) == (old_s, old_d):
        return False
    task.start_date, task.due_date = ns, nd
    return True


def non_working_dates_message(
    start: date | None,
    due: date | None,
    project: Project | None,
) -> str | None:
    """Предупреждение, если начало/конец на выходном или празднике (без автосдвига)."""
    from servicesystem.project_management.work_calendar import (
        is_non_working_day,
        is_public_holiday,
        is_weekend,
        project_uses_work_calendar,
    )

    if not project_uses_work_calendar(project):
        return None

    def _label(d: date) -> str:
        parts = [d.strftime("%d.%m.%Y")]
        if getattr(project, "skip_weekends", False) and is_weekend(d):
            parts.append("сб" if d.weekday() == 5 else "вс")
        if getattr(project, "skip_public_holidays", False) and is_public_holiday(d):
            parts.append("праздник")
        return " · ".join(parts)

    if start and is_non_working_day(start, project):
        return (
            f"Начало попадает на нерабочий день ({_label(start)}). "
            "Укажите рабочий день — дата не сдвигается автоматически."
        )
    if due and is_non_working_day(due, project):
        return (
            f"Дедлайн попадает на нерабочий день ({_label(due)}). "
            "Укажите рабочий день — дата не сдвигается автоматически."
        )
    return None


def clamp_task_dates(task: ProjectTask, *, snap_workdays: bool = True) -> bool:
    """Родитель + окно проекта (+ рабочие дни, если snap_workdays)."""
    changed = False
    for _ in range(4):
        round_changed = False
        if clamp_task_dates_to_parent(task):
            round_changed = True
        if clamp_task_dates_to_project(task):
            round_changed = True
        if snap_workdays and _snap_task_dates_to_workdays(task):
            round_changed = True
        if round_changed:
            changed = True
        else:
            break
    return changed


def _task_depth(task: ProjectTask, cache: dict[int, int]) -> int:
    """Глубина в иерархии (корень = 0) для порядка snap/clamp."""
    tid = task.id
    if tid in cache:
        return cache[tid]
    depth = 0
    cur = task
    seen: set[int] = set()
    while cur and cur.parent_id and cur.parent_id not in seen:
        seen.add(cur.parent_id)
        depth += 1
        parent = cur.parent
        if parent is None:
            parent = db.session.get(ProjectTask, cur.parent_id)
        cur = parent
        if cur is None:
            break
    cache[tid] = depth
    return depth


def reschedule_project_tasks_to_workdays(project: Project) -> int:
    """
    После включения «не ставить на выходные/праздники» —
    сдвинуть сроки всех задач проекта с нерабочих дней (длительность в трудоднях).
    Родители раньше детей, затем clamp в окна и FS.
    """
    from servicesystem.project_management.work_calendar import project_uses_work_calendar

    if not project or not project_uses_work_calendar(project):
        return 0
    n = 0
    depth_cache: dict[int, int] = {}
    tasks = sorted(
        ProjectTask.query.filter_by(project_id=project.id).all(),
        key=lambda t: (_task_depth(t, depth_cache), gantt_sort_key(t)),
    )
    for task in tasks:
        if _snap_task_dates_to_workdays(task):
            sync_calendar_events_for_task(task)
            n += 1
    # Сначала укладываем в окна (родители уже на рабочих днях)
    for task in tasks:
        if clamp_task_dates(task):
            sync_calendar_events_for_task(task)
            n += 1
    # Подтянуть FS после сдвига с выходных
    for task in tasks:
        cascade_fs_from_task(task)
    return n


def effective_date_window(
    *,
    parent: ProjectTask | None = None,
    project: Project | None = None,
) -> tuple[date | None, date | None]:
    """min/max: max(старт проекта, старт родителя) … min(дедлайн проекта, due родителя)."""
    min_d: date | None = None
    max_d: date | None = None
    p_start, p_due = parent_date_window(parent)
    if p_start:
        min_d = p_start
    if p_due:
        max_d = p_due
    floor = project_earliest_start(project)
    ceil = project_latest_due(project)
    if floor:
        min_d = max(min_d, floor) if min_d else floor
    if ceil:
        max_d = min(max_d, ceil) if max_d else ceil
    if min_d and max_d and max_d < min_d:
        max_d = min_d
    return min_d, max_d


def project_dates_violation_message(
    start: date | None,
    due: date | None,
    project: Project | None,
) -> str | None:
    """Текст ошибки, если сроки вне окна проекта."""
    if dates_within_project(start, due, project):
        return None
    floor = project_earliest_start(project)
    ceil = project_latest_due(project)
    if floor and ((start and start < floor) or (due and due < floor)):
        return f"Нельзя начать задачу раньше старта проекта ({floor.strftime('%d.%m.%Y')})."
    if ceil and ((start and start > ceil) or (due and due > ceil)):
        return f"Нельзя закончить задачу позже крайнего срока проекта ({ceil.strftime('%d.%m.%Y')})."
    return "Сроки задачи должны быть внутри периода проекта."


def iter_task_descendants(task: ProjectTask):
    """Все потомки задачи (BFS)."""
    queue: list[ProjectTask] = list(getattr(task, "subtasks", None) or [])
    if not queue and task.id:
        queue = list(ProjectTask.query.filter_by(parent_id=task.id).all())
    seen: set[int] = set()
    while queue:
        child = queue.pop(0)
        if not child or child.id in seen:
            continue
        seen.add(child.id)
        yield child
        kids = list(getattr(child, "subtasks", None) or [])
        if not kids:
            kids = list(ProjectTask.query.filter_by(parent_id=child.id).all())
        queue.extend(kids)


def shift_task_dates(task: ProjectTask, delta_days: int) -> bool:
    """Сдвинуть start/due на delta календарных дней."""
    if not delta_days:
        return False
    changed = False
    if task.start_date:
        task.start_date = task.start_date + timedelta(days=delta_days)
        changed = True
    if task.due_date:
        task.due_date = task.due_date + timedelta(days=delta_days)
        changed = True
    if task.start_date and task.due_date and task.due_date < task.start_date:
        task.start_date, task.due_date = task.due_date, task.start_date
    return changed


def shift_task_subtree(task: ProjectTask, delta_days: int) -> list[int]:
    """Сдвинуть все подзадачи вместе с родителем (родитель уже сдвинут)."""
    if not delta_days:
        return []
    changed: list[int] = []
    for child in iter_task_descendants(task):
        if shift_task_dates(child, delta_days):
            clamp_task_dates(child)
            sync_calendar_events_for_task(child)
            changed.append(child.id)
    return changed


def default_dates_within_parent(
    parent: ProjectTask | None,
    today: date | None = None,
    *,
    project: Project | None = None,
) -> tuple[date, date]:
    """Дефолт для новой задачи — сегодня, не раньше проекта и внутри родителя."""
    d = today or date.today()
    min_d, max_d = effective_date_window(parent=parent, project=project or (parent.project if parent else None))
    if min_d and d < min_d:
        d = min_d
    if max_d and d > max_d:
        d = max_d
    return d, d


def kanban_sort_key(task: ProjectTask) -> tuple:
    return (-(task.priority or 0), -(1 if task.is_critical_path else 0), task.kanban_sort, task.id)


def gantt_sort_key(task: ProjectTask) -> tuple:
    """Порядок строк на Ганте: ручной gantt_sort, затем id (стабильно по созданию)."""
    return (task.gantt_sort or 0, task.id)


def next_gantt_sort(project_id: int | None) -> int:
    if not project_id:
        return 0
    from sqlalchemy import func

    mx = (
        db.session.query(func.coalesce(func.max(ProjectTask.gantt_sort), 0))
        .filter(ProjectTask.project_id == project_id)
        .scalar()
    )
    return int(mx or 0) + 1


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


def executors_for_project(project_id: int | None) -> list[User]:
    """Исполнители — участники проекта (project_members), не весь штат."""
    if not project_id:
        return []
    member_ids = db.session.query(ProjectMember.user_id).filter_by(project_id=project_id)
    return (
        User.query.filter(
            User.id.in_(member_ids),
            User.role == "executor",
            User.is_active.is_(True),
        )
        .order_by(User.full_name)
        .all()
    )


def is_project_member(project_id: int | None, user_id: int | None) -> bool:
    if not project_id or not user_id:
        return False
    return (
        ProjectMember.query.filter_by(project_id=project_id, user_id=user_id).first() is not None
    )


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
    from servicesystem.project_management.work_calendar import snap_to_workday

    today = today or date.today()
    moved = 0
    q = ProjectTask.query.filter(
        ProjectTask.due_date.isnot(None),
        ProjectTask.due_date < today,
        ProjectTask.kanban_status.in_(("todo", "in_progress", "review")),
    )
    for task in q:
        task.overdue_days = (task.overdue_days or 0) + 1
        nxt = today + timedelta(days=1)
        task.due_date = snap_to_workday(nxt, task.project)
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
        gantt_sort=next_gantt_sort(source.project_id),
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
        skip_weekends=bool(getattr(template, "skip_weekends", False)),
        skip_public_holidays=bool(getattr(template, "skip_public_holidays", False)),
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
            cost=st.cost,
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


def count_task_links(task: ProjectTask) -> int:
    """Число входящих и исходящих связей задачи."""
    tid = task.id
    return ProjectTaskLink.query.filter(
        or_(ProjectTaskLink.from_task_id == tid, ProjectTaskLink.to_task_id == tid)
    ).count()


def clear_all_task_links(task: ProjectTask) -> int:
    """Удалить все связи задачи. Возвращает число удалённых."""
    tid = task.id
    n = ProjectTaskLink.query.filter(
        or_(ProjectTaskLink.from_task_id == tid, ProjectTaskLink.to_task_id == tid)
    ).delete(synchronize_session=False)
    return int(n or 0)


def change_task_parent(
    task: ProjectTask,
    new_parent_id: int | None,
    *,
    break_links: bool = False,
) -> tuple[str | None, dict]:
    """
    Сменить родителя: None — отдельная задача верхнего уровня; иначе — подзадача.
    Возвращает (error_code|None, payload). error_code:
      has_links — нужны break_links;
      bad_parent / cycle / same — некорректный родитель.
    """
    extra: dict = {"link_count": count_task_links(task)}
    if new_parent_id is not None:
        try:
            new_parent_id = int(new_parent_id)
        except (TypeError, ValueError):
            return "bad_parent", extra
        if new_parent_id == task.id:
            return "same", extra
        parent = db.session.get(ProjectTask, new_parent_id)
        if not parent or parent.project_id != task.project_id:
            return "bad_parent", extra
        if is_task_ancestor(task, parent):
            return "cycle", {
                **extra,
                "message": "Нельзя сделать родителем свою подзадачу.",
            }
        # уже этот родитель
        if task.parent_id == new_parent_id:
            return None, {**extra, "unchanged": True}
    else:
        if not task.parent_id:
            return None, {**extra, "unchanged": True}

    link_n = int(extra["link_count"] or 0)
    if link_n and not break_links:
        return "has_links", {
            **extra,
            "link_count": link_n,
            "message": "У задачи есть связи. Разорвать?",
        }

    if break_links and link_n:
        cleared = clear_all_task_links(task)
        db.session.flush()
        extra["links_cleared"] = cleared
        extra["link_count"] = 0

    if new_parent_id is None:
        task.parent_id = None
    else:
        parent = db.session.get(ProjectTask, new_parent_id)
        assert parent is not None
        task.parent_id = parent.id
        if parent.stage_id and not task.stage_id:
            task.stage_id = parent.stage_id
        clamp_task_dates(task)
        sync_calendar_events_for_task(task)

    return None, extra


def delete_project_task(task: ProjectTask) -> None:
    """Удалить задачу вместе со связями, событиями календаря и отвязать подзадачи.

    Без явной очистки PostgreSQL/SQLAlchemy падают на NOT NULL у calendar_events
    и на FK входящих links (to_task_id).
    """
    tid = task.id
    ProjectTaskLink.query.filter(
        or_(ProjectTaskLink.from_task_id == tid, ProjectTaskLink.to_task_id == tid)
    ).delete(synchronize_session=False)
    ProjectCalendarEvent.query.filter_by(task_id=tid).delete(synchronize_session=False)
    ProjectTask.query.filter_by(parent_id=tid).update(
        {ProjectTask.parent_id: None},
        synchronize_session=False,
    )
    db.session.delete(task)


def user_can_edit_task(user: User, task: ProjectTask) -> bool:
    if user.is_admin or user.is_auditor:
        return True
    if task.assignee_id == user.id:
        return True
    if task.created_by_id == user.id:
        return True
    return task.collaborators.filter_by(user_id=user.id).first() is not None


def user_can_edit_task_plan(user: User, task: ProjectTask | None = None) -> bool:
    """Планирование задачи (сроки, этап, исполнитель, иерархия) — только ГИП/админ.

    Исполнитель правит контент: статус, чек-лист, файлы, комментарии, время, соисполнители.
    """
    return bool(user and (user.is_admin or user.is_auditor))


def user_can_delete_task(user: User, task: ProjectTask | None = None) -> bool:
    """Удаление из БД — только ГИП/админ. Исполнитель — статус Отклонено/Архив."""
    return bool(user and (user.is_admin or user.is_auditor))


def user_can_manage_collaborators(user: User, task: ProjectTask) -> bool:
    """Соисполнители: ГИП/админ или исполнитель своей карточки."""
    if not user or not task:
        return False
    if user.is_admin or user.is_auditor:
        return True
    return user_can_edit_task(user, task)


def user_can_view_others_time_logs(user: User) -> bool:
    """Чужие тайм-логи видят только ГИП/админ; исполнитель — только свои."""
    return bool(user and (user.is_admin or user.is_auditor))


def user_can_view_task(user: User, task: ProjectTask) -> bool:
    if user_can_edit_task(user, task):
        return True
    if user.role == "customer_curator" and task.project and task.project.customer_curator_id == user.id:
        return True
    if user.is_auditor:
        return True
    return False
