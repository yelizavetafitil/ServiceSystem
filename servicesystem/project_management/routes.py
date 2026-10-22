"""ARM проектов: Kanban, неделя, календарь, Gantt (ТЗ 2)."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from flask_login import current_user, login_required

from servicesystem.decorators import staff_required
from servicesystem.extensions import db
from servicesystem.models import Contract, Organization, User
from servicesystem.project_management.models import (
    TASK_KANBAN_COLUMNS,
    Project,
    ProjectMember,
    ProjectStage,
    ProjectTask,
    ProjectTaskCollaborator,
)
from servicesystem.project_management.dates import parse_optional_date as _parse_form_date
from servicesystem.project_management.services import (
    apply_fs_cascade_and_expand,
    cascade_fs_from_task,
    cascade_fs_schedule,
    clamp_task_dates,
    dates_within_parent,
    dates_within_project,
    default_dates_within_parent,
    duplicate_task,
    effective_date_window,
    gantt_sla_breach,
    gantt_sort_key,
    kanban_sort_key,
    move_task_kanban,
    next_gantt_sort,
    non_working_dates_message,
    cascade_fs_successors_only,
    parent_date_window,
    project_dates_violation_message,
    project_earliest_start,
    project_latest_due,
    project_from_template,
    fs_link_parent_window_violation,
    tasks_hierarchically_related,
    rollover_overdue_tasks,
    shift_task_subtree,
    reschedule_project_tasks_to_workdays,
    sync_calendar_events_for_task,
    task_opens_as_ticket,
    tasks_for_user_query,
    update_customer_curator_window,
    executors_for_project,
    is_project_member,
    user_can_create_task,
    user_can_edit_task,
    user_can_manage_project,
    user_can_reschedule_gantt,
    user_can_view_custom_field,
    user_can_view_gantt,
)

bp = Blueprint("projects", __name__)

_ARM_FILTER_PROJECT_KEY = "projects_arm_filter_project"
_ARM_FILTER_SCALE_KEY = "projects_arm_filter_scale"
_ARM_FILTER_GROUP_KEY = "projects_arm_filter_group"
_ARM_FILTER_SUBTASKS_KEY = "projects_arm_filter_subtasks"
_ARM_FILTER_CAL_MODE_KEY = "projects_arm_filter_cal_mode"
_ARM_FILTER_ASSIGNEE_KEY = "projects_arm_filter_assignee"
_ARM_BACK_VIEW_KEY = "projects_arm_back_view"
_ARM_VIEWS = ("kanban", "week", "calendar", "gantt")

KANBAN_LABELS = {
    "todo": "К исполнению",
    "in_progress": "В работе",
    "review": "На верификации",
    "done": "Выполнено",
}

# UI: blocks и blocked_by — одна зависимость «предшественник» (FS); в БД blocked_by остаётся для старых записей
PROJECT_LINK_LABELS = {
    "blocks": "Предшественник",
    "blocked_by": "Предшественник",
    "related": "Связанная",
}

# Выбор при добавлении связи на карточке: предшественник = другая задача → текущая (blocks)
PROJECT_LINK_UI_CHOICES = (
    ("predecessor", "Предшественник"),
    ("related", "Связанная"),
)

GANTT_LINK_TYPE_LABELS = {
    "blocks": "Предшественник (конец → начало)",
    "related": "Связанная",
}

PROJECT_FIELD_TYPE_LABELS = {
    "text": "Текст",
    "date": "Дата",
    "url": "Ссылка",
    "budget": "Бюджет",
    "tag": "Тег",
}

PROJECT_VISIBILITY_LABELS = {
    "all": "Все участники",
    "staff": "Персонал",
    "auditor": "Только ГИП",
}

PRIORITY_LABELS = {
    1: "Низший",
    2: "Обычный",
    3: "Высокий",
    4: "Самый высший",
}


def projects_ui_context() -> dict:
    """Подписи для шаблонов projects/* (и app.context_processor)."""
    return {
        "project_link_labels": PROJECT_LINK_LABELS,
        "project_field_type_labels": PROJECT_FIELD_TYPE_LABELS,
        "project_visibility_labels": PROJECT_VISIBILITY_LABELS,
        "project_priority_labels": PRIORITY_LABELS,
    }


def _project_period_label(project) -> str:
    """Подпись периода проекта для дерева задач и шапки Ганта."""
    if not project:
        return ""
    ps = getattr(project, "planned_start", None)
    de = getattr(project, "deadline", None)
    if ps and de:
        return f"{ps.strftime('%d.%m.%Y')} — {de.strftime('%d.%m.%Y')}"
    if de:
        return f"до {de.strftime('%d.%m.%Y')}"
    if ps:
        return f"с {ps.strftime('%d.%m.%Y')}"
    return ""


def _stage_deadline_label(stage) -> str:
    if not stage or not getattr(stage, "deadline", None):
        return ""
    return stage.deadline.strftime("%d.%m.%Y")


def _project_task_tree_payload(project_id: int) -> list[dict]:
    out: list[dict] = []
    for t in (
        ProjectTask.query.filter_by(project_id=project_id)
        .order_by(ProjectTask.gantt_sort.asc(), ProjectTask.id.asc())
        .limit(400)
    ):
        s, e = t.start_date, t.due_date
        if s and e:
            dates_label = (
                f"{s.strftime('%d.%m')}–{e.strftime('%d.%m.%Y')}"
                if s != e
                else s.strftime("%d.%m.%Y")
            )
        elif s or e:
            d = s or e
            dates_label = d.strftime("%d.%m.%Y")
        else:
            dates_label = ""
        out.append(
            {
                "id": t.id,
                "title": t.title,
                "stage_id": t.stage_id,
                "parent_id": t.parent_id,
                "start": s.isoformat() if s else "",
                "due": e.isoformat() if e else "",
                "dates_label": dates_label,
            }
        )
    return out


def _project_stages_payload(project) -> list[dict]:
    if not project:
        return []
    return [
        {
            "id": s.id,
            "title": s.title,
            "deadline_label": _stage_deadline_label(s),
        }
        for s in project.stages.order_by(ProjectStage.sort_order)
    ]


def _task_detail_tree_context(task: ProjectTask) -> dict:
    """JSON для навигационного дерева в карточке задачи."""
    if not task or not task.project_id:
        return {
            "task_tree_stages": [],
            "task_tree_tasks": [],
            "task_tree_project": {"name": "Проект", "dates_label": ""},
        }
    proj = task.project
    return {
        "task_tree_stages": _project_stages_payload(proj),
        "task_tree_tasks": _project_task_tree_payload(task.project_id),
        "task_tree_project": {
            "name": proj.name if proj else "Проект",
            "dates_label": _project_period_label(proj),
        },
    }


def _staff_or_curator():
    if not current_user.is_authenticated:
        abort(403)
    if current_user.is_staff or current_user.role == "customer_curator":
        return
    abort(403)


def _parse_stage_cost(raw) -> object:
    """Стоимость этапа: пусто → None, иначе Decimal."""
    from decimal import Decimal, InvalidOperation

    s = (raw or "").strip().replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


@bp.route("/")
@login_required
def index():
    _staff_or_curator()
    view = request.args.get("view", "kanban")
    return redirect(url_for("projects.arm", view=view))


@bp.route("/arm")
@login_required
def arm():
    _staff_or_curator()
    view = (request.args.get("view") or "kanban").lower()
    if view not in _ARM_VIEWS:
        view = "kanban"
    # Гант / неделя / календарь — планирование ГИП; исполнители — канбан (список/доски)
    if view in ("gantt", "week", "calendar") and not user_can_view_gantt(current_user):
        flash("Диаграмма Ганта и планирование доступны только ГИП.", "warning")
        return redirect(url_for("projects.arm", view="kanban", project=request.args.get("project")))
    if current_user.is_staff:
        try:
            rollover_overdue_tasks()
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("rollover_overdue_tasks failed")
    projects = _projects_visible()
    project_id = _arm_filter_project(projects)
    _remember_arm_back(view, project_id)
    gantt_scale = _arm_filter_choice(
        "scale",
        _ARM_FILTER_SCALE_KEY,
        allowed=("day", "week", "month", "quarter"),
        default="month",
    )
    gantt_group = _arm_filter_choice(
        "group",
        _ARM_FILTER_GROUP_KEY,
        allowed=("project", "none"),
        default=("none" if project_id else "project"),
    )
    gantt_show_subtasks = _arm_filter_choice(
        "subtasks",
        _ARM_FILTER_SUBTASKS_KEY,
        allowed=("1", "0"),
        default="1",
    ) == "1"
    cal_mode = _arm_filter_choice(
        "cal_mode",
        _ARM_FILTER_CAL_MODE_KEY,
        allowed=("month", "workweek", "day", "team"),
        default="month",
    )
    filter_assignee = _arm_filter_assignee()
    include_done = view in ("kanban", "gantt")
    if current_user.is_admin or current_user.is_auditor:
        tasks_q = ProjectTask.query
        if project_id:
            tasks_q = tasks_q.filter_by(project_id=project_id)
        if not include_done:
            tasks_q = tasks_q.filter(ProjectTask.kanban_status != "done")
    else:
        tasks_q = tasks_for_user_query(
            current_user,
            project_id=project_id,
            include_completed=include_done,
        )
    if view == "gantt" and not gantt_show_subtasks:
        tasks_q = tasks_q.filter(ProjectTask.parent_id.is_(None))
    tasks_raw = tasks_q.all()
    if view == "gantt":
        tasks = sorted(tasks_raw, key=gantt_sort_key)
    else:
        tasks = sorted(tasks_raw, key=kanban_sort_key)
    calendar_executors = (
        _calendar_executors(project_id, projects) if view == "calendar" else []
    )
    ctx = dict(
        view=view,
        projects=projects,
        filter_project=project_id,
        filter_assignee=filter_assignee,
        calendar_executors=calendar_executors,
        tasks=tasks,
        kanban_labels=KANBAN_LABELS,
        columns=TASK_KANBAN_COLUMNS,
        today=date.today(),
        gantt_scale=gantt_scale,
        gantt_group=gantt_group,
        gantt_show_subtasks=gantt_show_subtasks,
        cal_mode=cal_mode,
    )
    if view == "kanban":
        grouped = {c: [] for c in TASK_KANBAN_COLUMNS}
        for t in tasks:
            grouped.setdefault(t.kanban_status, []).append(t)
        for col in grouped:
            grouped[col] = sorted(grouped[col], key=kanban_sort_key)
        ctx["grouped"] = grouped
        return render_template("projects/kanban.html", **ctx)
    if view == "week":
        week_days = _week_days()
        week_dates = [d for d, _ in week_days]
        return render_template(
            "projects/week.html",
            **ctx,
            week_days=week_days,
            tasks_by_day=_tasks_by_day(tasks, week_dates),
        )
    if view == "calendar":
        month_grid = _month_grid(cal_mode)
        executor_workload = _executor_workload(tasks, list(month_grid))
        ctx["calendar_executors"] = _calendar_executors(
            project_id, projects, extra_ids=[w["id"] for w in executor_workload]
        )
        grid_tasks = (
            [t for t in tasks if _task_involves_user(t, filter_assignee)]
            if filter_assignee
            else tasks
        )
        return render_template(
            "projects/calendar.html",
            **ctx,
            month_grid=month_grid,
            tasks_by_day=_tasks_by_day(grid_tasks, list(month_grid)),
            team_load=_team_load(grid_tasks) if cal_mode == "team" else None,
            executor_workload=executor_workload,
        )
    gantt_anchor = _parse_form_date(request.args.get("anchor"))
    span_projects = (
        [p for p in projects if p.id == project_id] if project_id else list(projects)
    )
    gantt = _gantt_layout(
        tasks,
        gantt_scale,
        group_by=gantt_group,
        user=current_user,
        anchor=gantt_anchor,
        project_filter=project_id,
        projects=span_projects,
    )
    gantt_stages = []
    for p in projects:
        for st in p.stages.order_by(ProjectStage.sort_order):
            gantt_stages.append(
                {"id": st.id, "title": st.title, "project_id": p.id, "project": p.name}
            )
    return render_template(
        "projects/gantt.html",
        **ctx,
        **gantt,
        gantt_stages=gantt_stages,
        gantt_can_edit=bool(current_user.is_admin or current_user.is_auditor),
    )


def _projects_visible():
    q = Project.query.filter_by(is_active=True, is_template=False)
    if current_user.is_admin or current_user.is_auditor:
        return q.order_by(Project.name).all()
    if current_user.role == "customer_curator":
        return q.filter_by(customer_curator_id=current_user.id).order_by(Project.name).all()
    if current_user.is_executor:
        ids = db.session.query(ProjectMember.project_id).filter_by(user_id=current_user.id)
        return q.filter(or_(Project.id.in_(ids), Project.is_support_project.is_(True))).order_by(Project.name).all()
    return []


def _remember_arm_back(view: str | None = None, project_id: int | None = None) -> None:
    """Запомнить вид ARM для «назад» с карточки задачи."""
    if view and view in _ARM_VIEWS:
        session[_ARM_BACK_VIEW_KEY] = view
    # project_id фильтруется отдельно в _arm_filter_project / сессии проекта


def _arm_back_url(*, project_id: int | None = None) -> str:
    """Ссылка «К модулю проектов» — тот же view (Гант/канбан/…), откуда пришли."""
    view = session.get(_ARM_BACK_VIEW_KEY) or "kanban"
    if view not in _ARM_VIEWS:
        view = "kanban"
    if view in ("gantt", "week", "calendar") and not user_can_view_gantt(current_user):
        view = "kanban"
    pid = project_id if project_id is not None else session.get(_ARM_FILTER_PROJECT_KEY)
    kwargs: dict = {"view": view}
    if isinstance(pid, int) and pid:
        kwargs["project"] = pid
    # сохранить зум/режим, если есть в сессии
    if view == "gantt":
        scale = session.get(_ARM_FILTER_SCALE_KEY)
        if scale in ("day", "week", "month", "quarter"):
            kwargs["scale"] = scale
        group = session.get(_ARM_FILTER_GROUP_KEY)
        if group in ("project", "none"):
            kwargs["group"] = group
        subtasks = session.get(_ARM_FILTER_SUBTASKS_KEY)
        if subtasks in ("0", "1"):
            kwargs["subtasks"] = subtasks
    elif view == "calendar":
        cal_mode = session.get(_ARM_FILTER_CAL_MODE_KEY)
        if cal_mode in ("month", "workweek", "day", "team"):
            kwargs["cal_mode"] = cal_mode
    return url_for("projects.arm", **kwargs)


def _arm_view_from_request() -> str | None:
    raw = (request.args.get("arm_view") or request.args.get("from") or "").strip().lower()
    return raw if raw in _ARM_VIEWS else None


def _arm_filter_project(projects) -> int | None:
    """Фильтр проекта ARM: из query или из сессии; «Все проекты» сбрасывает сессию."""
    visible = {p.id for p in projects or []}
    if "project" in request.args:
        raw = (request.args.get("project") or "").strip()
        if not raw:
            session.pop(_ARM_FILTER_PROJECT_KEY, None)
            return None
        pid = request.args.get("project", type=int)
        if pid and pid in visible:
            session[_ARM_FILTER_PROJECT_KEY] = pid
            return pid
        session.pop(_ARM_FILTER_PROJECT_KEY, None)
        return None
    stored = session.get(_ARM_FILTER_PROJECT_KEY)
    if isinstance(stored, int) and stored in visible:
        return stored
    if stored is not None:
        session.pop(_ARM_FILTER_PROJECT_KEY, None)
    return None


def _arm_filter_choice(
    arg: str,
    session_key: str,
    *,
    allowed: tuple[str, ...],
    default: str,
) -> str:
    if arg in request.args:
        val = (request.args.get(arg) or "").strip().lower()
        if val in allowed:
            session[session_key] = val
            return val
        session.pop(session_key, None)
        return default
    stored = session.get(session_key)
    if isinstance(stored, str) and stored in allowed:
        return stored
    return default


def _arm_filter_assignee() -> int | None:
    if "assignee" in request.args:
        raw = (request.args.get("assignee") or "").strip()
        if not raw:
            session.pop(_ARM_FILTER_ASSIGNEE_KEY, None)
            return None
        uid = request.args.get("assignee", type=int)
        if uid:
            session[_ARM_FILTER_ASSIGNEE_KEY] = uid
            return uid
        session.pop(_ARM_FILTER_ASSIGNEE_KEY, None)
        return None
    stored = session.get(_ARM_FILTER_ASSIGNEE_KEY)
    return stored if isinstance(stored, int) else None


@bp.route("/manage")
@login_required
@staff_required
def manage_list():
    if not (current_user.is_admin or current_user.is_auditor):
        abort(403)
    items = Project.query.filter_by(is_template=False).order_by(Project.name).all()
    templates = Project.query.filter_by(is_template=True).order_by(Project.name).all()
    return render_template("projects/manage.html", projects=items, templates=templates)


def _resolve_contract_from_project_form():
    """Существующий договор или создание нового (для admin/auditor)."""
    import secrets
    import string

    mode = request.form.get("contract_mode") or "existing"
    if mode == "new":
        org_id = request.form.get("new_contract_org_id", type=int)
        number = (request.form.get("new_contract_number") or "").strip()
        if not org_id or not number:
            return None, "Для нового договора укажите организацию и номер."
        if Contract.query.filter_by(number=number).first():
            return None, f"Договор с номером «{number}» уже существует."
        org = db.session.get(Organization, org_id)
        if not org:
            return None, "Организация не найдена."
        alphabet = string.ascii_letters + string.digits
        master_login = f"m_{secrets.token_hex(4)}"
        master_password = "".join(secrets.choice(alphabet) for _ in range(12))
        contract = Contract(
            organization_id=org_id,
            number=number,
            signed_at=_parse_form_date(request.form.get("new_contract_signed_at")),
            service_end_date=_parse_form_date(request.form.get("new_contract_service_end")),
            master_key_expires_at=_parse_form_date(request.form.get("new_contract_service_end")),
            status="active_warranty",
            master_login=master_login,
        )
        contract.set_master_password(master_password)
        db.session.add(contract)
        db.session.flush()
        return contract, f"Договор {number} создан. Master-логин: {master_login}, пароль: {master_password}"
    cid = request.form.get("contract_id", type=int) or None
    if not cid:
        return None, None
    contract = db.session.get(Contract, cid)
    if not contract:
        return None, "Выбранный договор не найден."
    return contract, None


@bp.route("/manage/new", methods=["GET", "POST"])
@login_required
@staff_required
def manage_new():
    if not (current_user.is_admin or current_user.is_auditor):
        abort(403)
    contracts = Contract.query.order_by(Contract.number).all()
    organizations = Organization.query.order_by(Organization.name).all()
    auditors = User.query.filter_by(role="auditor", is_active=True).all()
    executors = User.query.filter_by(role="executor", is_active=True).all()
    customers = User.query.filter(User.role.in_(("customer", "customer_curator")), User.is_active.is_(True)).all()
    templates = Project.query.filter_by(is_template=True, is_active=True).order_by(Project.name).all()
    preset_template_id = request.args.get("template", type=int)
    if request.method == "POST":
        mode = request.form.get("create_mode") or "blank"
        contract, contract_msg = _resolve_contract_from_project_form()
        if contract_msg and contract is None and (request.form.get("contract_mode") or "existing") == "new":
            flash(contract_msg, "warning")
            return redirect(url_for("projects.manage_new", template=preset_template_id))
        if contract_msg and contract is None and request.form.get("contract_id"):
            flash(contract_msg, "warning")
            return redirect(url_for("projects.manage_new", template=preset_template_id))
        contract_id = contract.id if contract else None
        if mode == "from_template":
            tpl_id = request.form.get("template_id", type=int)
            tpl = db.session.get(Project, tpl_id) if tpl_id else None
            if not tpl or not tpl.is_template:
                flash("Выберите шаблон из списка.", "warning")
                return redirect(url_for("projects.manage_new", template=preset_template_id))
            name = (request.form.get("name") or "").strip()
            if not name:
                flash("Укажите название нового проекта.", "warning")
                return redirect(url_for("projects.manage_new", template=tpl_id or preset_template_id))
            else:
                member_ids = [int(x) for x in request.form.getlist("member_ids")]
                proj = project_from_template(
                    tpl,
                    name=name,
                    contract_id=contract_id,
                    curator_id=request.form.get("curator_auditor_id", type=int) or current_user.id,
                    customer_curator_id=request.form.get("customer_curator_id", type=int) or None,
                    planned_start=_parse_form_date(request.form.get("planned_start")),
                    deadline=_parse_form_date(request.form.get("deadline")),
                    member_ids=member_ids,
                )
                if "skip_weekends" in request.form or "skip_public_holidays" in request.form:
                    proj.skip_weekends = request.form.get("skip_weekends") == "on"
                    proj.skip_public_holidays = request.form.get("skip_public_holidays") == "on"
                update_customer_curator_window(proj)
                db.session.commit()
                flash("Проект развёрнут из шаблона — проверьте сроки и договор.", "success")
                if contract_msg and contract:
                    flash(contract_msg, "info")
                return redirect(url_for("projects.manage_edit", pid=proj.id))
        else:
            name = (request.form.get("name") or "").strip()
            if not name:
                flash("Укажите название проекта.", "warning")
                return redirect(url_for("projects.manage_new"))
            proj = Project(
                name=name,
                contract_id=contract_id,
                planned_start=_parse_form_date(request.form.get("planned_start")),
                deadline=_parse_form_date(request.form.get("deadline")),
                skip_weekends=request.form.get("skip_weekends") == "on",
                skip_public_holidays=request.form.get("skip_public_holidays") == "on",
                curator_auditor_id=request.form.get("curator_auditor_id", type=int) or current_user.id,
                customer_curator_id=request.form.get("customer_curator_id", type=int) or None,
                description=(request.form.get("description") or "").strip() or None,
            )
            if request.form.get("save_as_template"):
                proj.is_template = True
            db.session.add(proj)
            db.session.flush()
            for uid in request.form.getlist("member_ids"):
                db.session.add(ProjectMember(project_id=proj.id, user_id=int(uid), role="executor"))
            update_customer_curator_window(proj)
            db.session.commit()
            flash("Шаблон создан." if proj.is_template else "Проект создан.", "success")
            if contract_msg and contract and not proj.is_template:
                flash(contract_msg, "info")
            return redirect(url_for("projects.manage_edit", pid=proj.id))
    return render_template(
        "projects/project_form.html",
        project=None,
        contracts=contracts,
        organizations=organizations,
        auditors=auditors,
        executors=executors,
        customers=customers,
        templates=templates,
        preset_template_id=preset_template_id,
    )


@bp.route("/manage/<int:pid>", methods=["GET", "POST"])
@login_required
@staff_required
def manage_edit(pid):
    proj = db.session.get(Project, pid) or abort(404)
    if not user_can_manage_project(current_user, proj) and not current_user.is_admin:
        abort(403)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "stage_add":
            st = ProjectStage(
                project_id=proj.id,
                title=request.form["stage_title"].strip(),
                deadline=_parse_form_date(request.form.get("stage_deadline")),
                cost=_parse_stage_cost(request.form.get("stage_cost")),
                responsible_id=request.form.get("stage_responsible_id", type=int),
                sort_order=proj.stages.count(),
            )
            db.session.add(st)
            db.session.commit()
            flash("Этап добавлен.", "success")
        elif action == "stage_update":
            sid = request.form.get("stage_id", type=int)
            st = db.session.get(ProjectStage, sid) if sid else None
            wants_json = (
                request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or "application/json" in (request.headers.get("Accept") or "")
            )
            if not st or st.project_id != proj.id:
                if wants_json:
                    return jsonify({"ok": False, "error": "Этап не найден"}), 404
            else:
                title = (request.form.get("stage_title") or "").strip()
                if not title:
                    if wants_json:
                        return jsonify({"ok": False, "error": "Укажите название этапа"}), 400
                else:
                    st.title = title
                    if "stage_deadline" in request.form:
                        st.deadline = _parse_form_date(request.form.get("stage_deadline"))
                    if "stage_cost" in request.form:
                        st.cost = _parse_stage_cost(request.form.get("stage_cost"))
                    if "stage_responsible_id" in request.form:
                        st.responsible_id = request.form.get("stage_responsible_id", type=int) or None
                    db.session.commit()
                    if wants_json:
                        cost_val = float(st.cost) if st.cost is not None else None
                        return jsonify(
                            {
                                "ok": True,
                                "message": "Этап сохранён",
                                "stage": {
                                    "id": st.id,
                                    "title": st.title,
                                    "deadline": st.deadline.isoformat() if st.deadline else None,
                                    "deadline_label": st.deadline.strftime("%d.%m.%Y") if st.deadline else "—",
                                    "cost": cost_val,
                                    "cost_label": f"{cost_val:.2f} BYN" if cost_val is not None else None,
                                    "responsible_id": st.responsible_id,
                                    "released": bool(st.released_at),
                                },
                            }
                        )
                    flash("Этап обновлён.", "success")
        elif action == "stage_delete":
            sid = request.form.get("stage_id", type=int)
            st = db.session.get(ProjectStage, sid) if sid else None
            if st and st.project_id == proj.id:
                # Задачи отвязываем от этапа, вложения удалятся каскадом
                ProjectTask.query.filter_by(stage_id=st.id).update(
                    {ProjectTask.stage_id: None}, synchronize_session=False
                )
                db.session.delete(st)
                db.session.commit()
                flash("Этап удалён.", "success")
        elif action == "stage_release":
            from datetime import datetime, timezone

            from servicesystem.project_management.services import save_stage_attachment
            from servicesystem.services.notify import send_email

            sid = request.form.get("stage_id", type=int)
            st = db.session.get(ProjectStage, sid) if sid else None
            if st and st.project_id == proj.id:
                st.release_notes = (request.form.get("release_notes") or "").strip() or None
                st.released_at = datetime.now(timezone.utc)
                for f in request.files.getlist("stage_files"):
                    if f and f.filename:
                        try:
                            att = save_stage_attachment(st, f, current_user.id)
                            db.session.add(att)
                        except ValueError:
                            flash("Файл этапа превышает 100 Мб.", "danger")
                if proj.customer_curator and proj.customer_curator.email:
                    send_email(
                        proj.customer_curator.email,
                        f"Выпуск этапа: {st.title}",
                        st.release_notes or f"Этап «{st.title}» проекта {proj.name} выпущен.",
                    )
                db.session.commit()
                flash("Этап выпущен, материалы направлены куратору-заказчику.", "success")
        elif action == "field_add":
            from servicesystem.project_management.models import ProjectCustomField

            db.session.add(
                ProjectCustomField(
                    project_id=proj.id,
                    name=request.form["field_name"].strip(),
                    field_type=request.form.get("field_type") or "text",
                    visibility=request.form.get("visibility") or "all",
                    sort_order=proj.custom_fields.count(),
                )
            )
            db.session.commit()
            flash("Пользовательское поле добавлено.", "success")
        elif action == "mark_template":
            if not proj.is_template:
                proj.is_template = True
                db.session.commit()
                flash("Проект сохранён как шаблон (не отображается в ARM как рабочий проект).", "success")
        else:
            proj.name = request.form["name"].strip()
            proj.contract_id = request.form.get("contract_id", type=int) or None
            proj.planned_start = _parse_form_date(request.form.get("planned_start"))
            proj.deadline = _parse_form_date(request.form.get("deadline"))
            proj.skip_weekends = request.form.get("skip_weekends") == "on"
            proj.skip_public_holidays = request.form.get("skip_public_holidays") == "on"
            proj.curator_auditor_id = request.form.get("curator_auditor_id", type=int)
            proj.customer_curator_id = request.form.get("customer_curator_id", type=int) or None
            proj.description = (request.form.get("description") or "").strip() or None
            update_customer_curator_window(proj)
            snapped = reschedule_project_tasks_to_workdays(proj)
            db.session.commit()
            flash("Сохранено.", "success")
            if snapped:
                flash(
                    f"Сроки {snapped} задач сдвинуты с нерабочих дней "
                    "(выходные/праздники по настройкам проекта).",
                    "info",
                )
        return redirect(url_for("projects.manage_edit", pid=pid))
    contracts = Contract.query.order_by(Contract.number).all()
    staff = User.query.filter(User.role.in_(("auditor", "executor")), User.is_active.is_(True)).all()
    customers = User.query.filter(User.role.in_(("customer", "customer_curator")), User.is_active.is_(True)).all()
    template_tasks = (
        ProjectTask.query.filter_by(project_id=proj.id, parent_id=None).order_by(ProjectTask.id).all()
        if proj.is_template
        else []
    )
    return render_template(
        "projects/project_edit.html",
        project=proj,
        contracts=contracts,
        staff=staff,
        customers=customers,
        template_tasks=template_tasks,
    )


@bp.route("/tasks/new", methods=["GET", "POST"])
@login_required
@staff_required
def task_new():
    parent_id = request.args.get("parent", type=int) or request.form.get("parent_id", type=int)
    if not user_can_create_task(current_user, parent_id=parent_id):
        abort(403)
    preset_project_id = request.args.get("project", type=int)
    preset_stage_id = request.args.get("stage", type=int)
    arm_view = _arm_view_from_request()
    if arm_view:
        _remember_arm_back(arm_view, preset_project_id)
    projects_q = Project.query.filter_by(is_active=True)
    if preset_project_id and (current_user.is_admin or current_user.is_auditor):
        tpl = db.session.get(Project, preset_project_id)
        if tpl and tpl.is_template:
            projects_q = projects_q.filter(
                or_(Project.is_template.is_(False), Project.id == preset_project_id)
            )
        else:
            projects_q = projects_q.filter_by(is_template=False)
    else:
        projects_q = projects_q.filter_by(is_template=False)
    projects = projects_q.order_by(Project.name).all()
    parent_task = db.session.get(ProjectTask, parent_id) if parent_id else None
    if parent_task and not preset_project_id:
        preset_project_id = parent_task.project_id
    stages_by_project: dict[int, list] = {}
    tasks_by_project: dict[int, list] = {}
    executors_by_project: dict[int, list] = {}
    for p in projects:
        stages_by_project[p.id] = _project_stages_payload(p)
        tasks_by_project[p.id] = _project_task_tree_payload(p.id)
        executors_by_project[p.id] = [
            {"id": u.id, "name": u.full_name} for u in executors_for_project(p.id)
        ]
    if parent_task and parent_task.project_id not in stages_by_project:
        stages_by_project[parent_task.project_id] = (
            _project_stages_payload(parent_task.project)
            if parent_task.project
            else []
        )
    if parent_task and parent_task.project_id not in tasks_by_project:
        tasks_by_project[parent_task.project_id] = _project_task_tree_payload(
            parent_task.project_id
        )
    if parent_task and parent_task.project_id not in executors_by_project:
        executors_by_project[parent_task.project_id] = [
            {"id": u.id, "name": u.full_name}
            for u in executors_for_project(parent_task.project_id)
        ]
    if request.method == "POST":
        from servicesystem.project_management.models import ProjectTaskLink

        project_id = request.form.get("project_id", type=int)
        if parent_task:
            project_id = parent_task.project_id
        stage_id = request.form.get("stage_id", type=int) or None
        if parent_task and not stage_id:
            stage_id = parent_task.stage_id
        assignee_id = request.form.get("assignee_id", type=int) or None
        priority = int(request.form.get("priority") or 2)
        arm_next = (request.form.get("arm_view") or "").strip().lower()
        if arm_next not in _ARM_VIEWS:
            arm_next = _arm_view_from_request()

        def _back_new(**extra):
            q = {"project": project_id or preset_project_id, "parent": parent_id}
            if stage_id:
                q["stage"] = stage_id
            if arm_next:
                q["arm_view"] = arm_next
            q.update({k: v for k, v in extra.items() if v is not None})
            return redirect(url_for("projects.task_new", **{k: v for k, v in q.items() if v is not None}))

        # --- пакетное создание (структура + уровни + даты) ---
        if (request.form.get("create_mode") or "") == "batch":
            if not project_id:
                flash("Укажите проект.", "warning")
                return _back_new()
            if assignee_id and not is_project_member(project_id, assignee_id):
                flash("Исполнитель должен быть участником проекта.", "warning")
                return _back_new()
            titles = request.form.getlist("batch_title")
            depths_raw = request.form.getlist("batch_depth")
            starts_raw = request.form.getlist("batch_start")
            dues_raw = request.form.getlist("batch_due")
            rows: list[dict] = []
            for i, raw_title in enumerate(titles):
                title = (raw_title or "").strip()
                if not title:
                    continue
                try:
                    depth = max(0, min(8, int(depths_raw[i] if i < len(depths_raw) else 0)))
                except (TypeError, ValueError):
                    depth = 0
                start_d = _parse_form_date(starts_raw[i] if i < len(starts_raw) else None)
                due_d = _parse_form_date(dues_raw[i] if i < len(dues_raw) else None)
                rows.append({"title": title, "depth": depth, "start": start_d, "due": due_d})
            if not rows:
                flash("Добавьте хотя бы одну строку с названием.", "warning")
                return _back_new()
            # depth 0 без parent_task — верхний уровень (только ГИП)
            if any(r["depth"] == 0 for r in rows) and not parent_task:
                if not user_can_create_task(current_user, parent_id=None):
                    flash("Задачи верхнего уровня может создавать только ГИП.", "danger")
                    return _back_new()
            proj_for_dates = db.session.get(Project, project_id)
            stack: list[tuple[int, ProjectTask]] = []  # (depth, task)
            created: list[ProjectTask] = []
            try:
                for r in rows:
                    depth = r["depth"]
                    while stack and stack[-1][0] >= depth:
                        stack.pop()
                    if depth > 0 and not stack:
                        depth = 0
                    row_parent = stack[-1][1] if stack else parent_task
                    row_parent_id = row_parent.id if row_parent else None
                    start_date, due_date = r["start"], r["due"]
                    if not start_date and not due_date:
                        start_date, due_date = default_dates_within_parent(
                            row_parent, project=proj_for_dates
                        )
                    elif start_date and not due_date:
                        due_date = start_date
                    elif due_date and not start_date:
                        start_date = due_date
                    if row_parent and not dates_within_parent(start_date, due_date, row_parent):
                        p_start, p_due = parent_date_window(row_parent)
                        flash(
                            f"«{r['title']}»: сроки вне родителя "
                            f"({p_start.strftime('%d.%m.%Y')} — {p_due.strftime('%d.%m.%Y')}).",
                            "warning",
                        )
                        db.session.rollback()
                        return _back_new()
                    proj_msg = project_dates_violation_message(start_date, due_date, proj_for_dates)
                    if proj_msg:
                        flash(f"«{r['title']}»: {proj_msg}", "warning")
                        db.session.rollback()
                        return _back_new()
                    t = ProjectTask(
                        project_id=project_id,
                        stage_id=(row_parent.stage_id if row_parent and row_parent.stage_id else stage_id),
                        parent_id=row_parent_id,
                        title=r["title"],
                        priority=priority,
                        assignee_id=assignee_id,
                        start_date=start_date,
                        due_date=due_date,
                        kanban_status="todo",
                        gantt_sort=next_gantt_sort(project_id),
                        created_by_id=current_user.id,
                    )
                    db.session.add(t)
                    db.session.flush()
                    clamp_task_dates(t)
                    sync_calendar_events_for_task(t)
                    created.append(t)
                    stack.append((depth, t))
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception("batch task create failed")
                flash("Не удалось создать список задач.", "danger")
                return _back_new()
            flash(f"Создано задач: {len(created)}.", "success")
            if arm_next and project_id:
                return redirect(url_for("projects.arm", view=arm_next, project=project_id))
            if created:
                return redirect(url_for("projects.task_detail", tid=created[0].id))
            return _back_new()

        # --- одна задача ---
        title = (request.form.get("title") or "").strip()
        if not title or not project_id:
            flash("Укажите проект и название задачи.", "warning")
            return redirect(url_for("projects.task_new", project=preset_project_id, parent=parent_id))
        if assignee_id and not is_project_member(project_id, assignee_id):
            flash("Исполнитель должен быть участником проекта.", "warning")
            return redirect(
                url_for("projects.task_new", project=project_id, parent=parent_id, stage=stage_id)
            )
        start_date = _parse_form_date(request.form.get("start_date"))
        due_date = _parse_form_date(request.form.get("due_date"))
        # Без дат задача не видна на шкале Ганта — по умолчанию сегодня (1 день)
        proj_for_dates = db.session.get(Project, project_id) if project_id else None
        if not start_date and not due_date:
            start_date, due_date = default_dates_within_parent(parent_task, project=proj_for_dates)
        elif start_date and not due_date:
            due_date = start_date
        elif due_date and not start_date:
            start_date = due_date
        if parent_task and not dates_within_parent(start_date, due_date, parent_task):
            p_start, p_due = parent_date_window(parent_task)
            flash(
                f"Сроки подзадачи должны быть внутри родителя "
                f"({p_start.strftime('%d.%m.%Y')} — {p_due.strftime('%d.%m.%Y')}).",
                "warning",
            )
            return redirect(
                url_for("projects.task_new", project=project_id, parent=parent_id, stage=stage_id)
            )
        proj_msg = project_dates_violation_message(start_date, due_date, proj_for_dates)
        if proj_msg:
            flash(proj_msg, "warning")
            return redirect(
                url_for("projects.task_new", project=project_id, parent=parent_id, stage=stage_id)
            )
        task = ProjectTask(
            project_id=project_id,
            stage_id=stage_id,
            parent_id=parent_task.id if parent_task else (request.form.get("parent_id", type=int) or None),
            title=title,
            description=(request.form.get("description") or "").strip() or None,
            priority=priority,
            assignee_id=assignee_id,
            due_date=due_date,
            start_date=start_date,
            kanban_status="todo",
            gantt_sort=next_gantt_sort(project_id),
            created_by_id=current_user.id,
        )
        db.session.add(task)
        db.session.flush()
        for uid in request.form.getlist("collaborator_ids"):
            if is_project_member(project_id, int(uid)):
                db.session.add(ProjectTaskCollaborator(task_id=task.id, user_id=int(uid)))
        pred_id = request.form.get("predecessor_task_id", type=int) or None
        if pred_id:
            pred = db.session.get(ProjectTask, pred_id)
            if pred and pred.project_id == project_id and pred.id != task.id:
                if tasks_hierarchically_related(pred, task):
                    flash(
                        "Нельзя связать родительскую задачу с её подзадачей "
                        "(родитель = совокупность подзадач).",
                        "warning",
                    )
                else:
                    bound_msg = fs_link_parent_window_violation(pred, task)
                    if bound_msg:
                        flash(bound_msg, "warning")
                    else:
                        db.session.add(
                            ProjectTaskLink(
                                from_task_id=pred.id,
                                to_task_id=task.id,
                                link_type="blocks",
                            )
                        )
                        apply_fs_cascade_and_expand(task)
        sync_calendar_events_for_task(task)
        db.session.commit()
        after = (request.form.get("after_create") or "view").strip().lower()
        if after == "another":
            flash(
                f"«{task.title}» создана. Можно сразу добавить следующую "
                + ("подзадачу к тому же родителю." if parent_task else "задачу в этом проекте."),
                "success",
            )
            q = {"project": project_id}
            if parent_task:
                q["parent"] = parent_task.id
            if stage_id:
                q["stage"] = stage_id
            if arm_next:
                q["arm_view"] = arm_next
            return redirect(url_for("projects.task_new", **q))
        if parent_task:
            flash(
                f"Подзадача к «{parent_task.title}» создана.",
                "success",
            )
        else:
            flash("Задача создана.", "success")
        detail_q = {"tid": task.id}
        if arm_next:
            detail_q["arm_view"] = arm_next
        if parent_task:
            detail_q["offer_sibling"] = 1
        else:
            # Предложить сразу добавить подзадачу к новой задаче
            detail_q["offer_child"] = 1
        return redirect(url_for("projects.task_detail", **detail_q))
    proj_for_form = (
        parent_task.project
        if parent_task
        else (db.session.get(Project, preset_project_id) if preset_project_id else None)
    )
    if parent_task:
        preset_stage_id = parent_task.stage_id or preset_stage_id
        default_start, default_due = default_dates_within_parent(parent_task, project=proj_for_form)
    else:
        default_start, default_due = default_dates_within_parent(None, project=proj_for_form)
    if preset_stage_id and preset_project_id and not parent_task:
        st = db.session.get(ProjectStage, preset_stage_id)
        if not st or st.project_id != preset_project_id:
            preset_stage_id = None
    elif not preset_stage_id and preset_project_id and not parent_task:
        # Один этап в проекте — подставляем его по умолчанию
        stages = stages_by_project.get(preset_project_id) or []
        if len(stages) == 1:
            preset_stage_id = stages[0]["id"]
    initial_project_id = (
        parent_task.project_id
        if parent_task
        else (preset_project_id or (projects[0].id if projects else None))
    )
    executors = executors_for_project(initial_project_id)
    project_names = {
        str(p.id): {"name": p.name, "dates_label": _project_period_label(p)}
        for p in projects
    }
    if parent_task and parent_task.project and str(parent_task.project_id) not in project_names:
        project_names[str(parent_task.project_id)] = {
            "name": parent_task.project.name,
            "dates_label": _project_period_label(parent_task.project),
        }
    date_min, date_max = effective_date_window(parent=parent_task, project=proj_for_form)
    preset_pred_id = request.args.get("pred", type=int)
    return render_template(
        "projects/task_form.html",
        task=None,
        projects=projects,
        executors=executors,
        parent_id=parent_id,
        parent_task=parent_task,
        preset_project_id=preset_project_id,
        stages_by_project=stages_by_project,
        tasks_by_project=tasks_by_project,
        executors_by_project=executors_by_project,
        project_names=project_names,
        preset_stage_id=preset_stage_id,
        preset_pred_id=preset_pred_id,
        default_start=default_start,
        default_due=default_due,
        parent_window_start=date_min,
        parent_window_due=date_max,
        project_start=project_earliest_start(proj_for_form),
        project_deadline=project_latest_due(proj_for_form),
        proj_for_form=proj_for_form,
        arm_view=arm_view,
        arm_back_url=_arm_back_url(project_id=preset_project_id or (parent_task.project_id if parent_task else None)),
        **projects_ui_context(),
    )


@bp.route("/tasks/<int:tid>", methods=["GET"])
@login_required
def task_detail(tid):
    task = db.session.get(ProjectTask, tid) or abort(404)
    if not user_can_edit_task(current_user, task) and current_user.role != "customer_curator":
        abort(403)
    if task_opens_as_ticket(task) and task.ticket_id:
        return redirect(url_for("tickets.detail", tid=task.ticket_id))
    arm_view = _arm_view_from_request()
    if arm_view:
        _remember_arm_back(arm_view, task.project_id)
    tab = request.args.get("tab", "main")
    if tab != "main":
        anchor_map = {
            "files": "task-files",
            "comments": "task-comments",
            "links": "task-links",
            "custom": "task-custom",
            "time": "task-time",
        }
        anchor = anchor_map.get(tab)
        if anchor:
            preview_q: dict = {}
            preview_arg = request.args.get("preview", type=int)
            if preview_arg:
                preview_q["preview"] = preview_arg
            return redirect(
                url_for("projects.task_detail", tid=tid, **preview_q) + "#" + anchor
            )
        tab = "main"
    executors = executors_for_project(task.project_id)
    # Текущий исполнитель/соисполнители вне состава — оставляем в списке, чтобы не потерять
    seen = {u.id for u in executors}
    if task.assignee_id and task.assignee_id not in seen and task.assignee:
        executors = list(executors) + [task.assignee]
        seen.add(task.assignee_id)
    for c in task.collaborators:
        if c.user_id not in seen and c.user:
            executors = list(executors) + [c.user]
            seen.add(c.user_id)
    custom_fields = []
    if task.project:
        for f in task.project.custom_fields.order_by("sort_order"):
            if user_can_view_custom_field(current_user, f):
                custom_fields.append(f)
    link_rows = list(task.links_out)
    from servicesystem.project_management.models import ProjectTaskLink

    link_rows_in = ProjectTaskLink.query.filter_by(to_task_id=task.id).all()
    sibling_tasks = (
        ProjectTask.query.filter(
            ProjectTask.project_id == task.project_id,
            ProjectTask.id != task.id,
        )
        .order_by(ProjectTask.title)
        .all()
        if task.project_id
        else []
    )
    project_stages = (
        list(task.project.stages.order_by(ProjectStage.sort_order)) if task.project else []
    )
    blocked = False
    from servicesystem.project_management.services import task_is_completion_blocked

    if task_is_completion_blocked(task):
        blocked = True
    subtasks = ProjectTask.query.filter_by(parent_id=task.id).all()
    collaborator_ids = {c.user_id for c in task.collaborators}
    from servicesystem.project_management.models import ProjectTimeLog

    time_logs = (
        ProjectTimeLog.query.filter_by(task_id=task.id)
        .order_by(ProjectTimeLog.created_at.desc())
        .limit(20)
        .all()
    )
    from servicesystem.project_management.models import ProjectTaskAttachment
    from servicesystem.project_management.services import (
        list_task_attachments,
        user_can_delete_task_attachment,
    )

    preview_att = None
    task_files: list = list(list_task_attachments(task.id))
    deletable_file_ids: set[int] = set()
    preview_aid = request.args.get("preview", type=int)
    known_ids = {f.id for f in task_files}
    if preview_aid:
        att = db.session.get(ProjectTaskAttachment, preview_aid)
        if att and att.task_id == task.id:
            preview_att = att
            if att.id not in known_ids:
                task_files.insert(0, att)
    elif task_files:
        preview_att = task_files[0]
    for f in task_files:
        if user_can_delete_task_attachment(current_user, task, f):
            deletable_file_ids.add(f.id)
    date_min, date_max = effective_date_window(parent=task.parent, project=task.project)
    from servicesystem.project_management.services import count_task_links, iter_task_descendants

    desc_ids = {c.id for c in iter_task_descendants(task)} | {task.id}
    hierarchy_parents = [t for t in sibling_tasks if t.id not in desc_ids]
    task_link_count = count_task_links(task)
    offer_sibling = bool(request.args.get("offer_sibling")) and bool(task.parent_id)
    offer_child = bool(request.args.get("offer_child")) and not bool(task.parent_id)
    sibling_new_url = None
    child_new_url = None
    if offer_sibling and task.parent_id:
        sq = {"parent": task.parent_id, "project": task.project_id}
        if session.get(_ARM_BACK_VIEW_KEY):
            sq["arm_view"] = session.get(_ARM_BACK_VIEW_KEY)
        sibling_new_url = url_for("projects.task_new", **sq)
    if offer_child:
        cq = {"parent": task.id, "project": task.project_id}
        if session.get(_ARM_BACK_VIEW_KEY):
            cq["arm_view"] = session.get(_ARM_BACK_VIEW_KEY)
        child_new_url = url_for("projects.task_new", **cq)
    return render_template(
        "projects/task_detail.html",
        task=task,
        task_files=task_files,
        deletable_file_ids=deletable_file_ids,
        preview_att=preview_att,
        kanban_labels=KANBAN_LABELS,
        tab="main",
        **_task_detail_tree_context(task),
        executors=executors,
        custom_fields=custom_fields,
        link_rows=link_rows,
        link_rows_in=link_rows_in,
        sibling_tasks=sibling_tasks,
        hierarchy_parents=hierarchy_parents,
        task_link_count=task_link_count,
        offer_sibling=offer_sibling,
        offer_child=offer_child,
        sibling_new_url=sibling_new_url,
        child_new_url=child_new_url,
        sibling_parent_title=(task.parent.title if task.parent else ""),
        project_stages=project_stages,
        blocked=blocked,
        subtasks=subtasks,
        parent_window_start=date_min,
        parent_window_due=date_max,
        project_start=project_earliest_start(task.project),
        project_deadline=project_latest_due(task.project),
        arm_back_url=_arm_back_url(project_id=task.project_id),
        arm_back_view=session.get(_ARM_BACK_VIEW_KEY),
        collaborator_ids=collaborator_ids,
        time_logs=time_logs,
        link_type_choices=list(PROJECT_LINK_UI_CHOICES),
        **projects_ui_context(),
    )


@bp.route("/tasks/<int:tid>/duplicate", methods=["POST"])
@login_required
@staff_required
def task_duplicate(tid):
    source = db.session.get(ProjectTask, tid) or abort(404)
    if not user_can_edit_task(current_user, source):
        abort(403)
    clone = duplicate_task(
        source,
        copy_subtasks=request.form.get("copy_subtasks") == "1",
        copy_links=request.form.get("copy_links") == "1",
        created_by_id=current_user.id,
    )
    db.session.commit()
    flash("Копия задачи создана.", "success")
    return redirect(url_for("projects.task_detail", tid=clone.id))


@bp.route("/gantt/tasks/<int:tid>/dates", methods=["POST"])
@login_required
def gantt_task_dates(tid):
    """Drag-and-drop на Ганте: сдвиг start/due (только admin/auditor)."""
    _staff_or_curator()
    task = db.session.get(ProjectTask, tid) or abort(404)
    if not user_can_reschedule_gantt(current_user, task):
        abort(403)
    data = request.get_json(silent=True) or {}
    start_s = (data.get("start_date") or "").strip()
    due_s = (data.get("due_date") or "").strip()
    try:
        start_d = date.fromisoformat(start_s) if start_s else None
        due_d = date.fromisoformat(due_s) if due_s else None
    except ValueError:
        return jsonify({"error": "bad_date"}), 400
    if not start_d and not due_d:
        return jsonify({"error": "no_dates"}), 400
    if start_d and due_d and due_d < start_d:
        start_d, due_d = due_d, start_d
    old_start = task.start_date or task.due_date
    if start_d:
        task.start_date = start_d
    if due_d:
        task.due_date = due_d
    if task.start_date and not task.due_date:
        task.due_date = task.start_date
    if task.due_date and not task.start_date:
        task.start_date = task.due_date
    nw = non_working_dates_message(task.start_date, task.due_date, task.project)
    if nw:
        db.session.rollback()
        return jsonify({"error": "non_working", "message": nw}), 400
    parent = task.parent
    if parent and not dates_within_parent(task.start_date, task.due_date, parent):
        p_start, p_due = parent_date_window(parent)
        db.session.rollback()
        return jsonify({
            "error": "parent_window",
            "message": (
                "Сроки должны быть внутри родителя "
                f"({p_start.strftime('%d.%m.%Y')} — {p_due.strftime('%d.%m.%Y')})."
                if p_start and p_due
                else "Сроки должны быть внутри родителя."
            ),
        }), 400
    proj_msg = project_dates_violation_message(task.start_date, task.due_date, task.project)
    if proj_msg:
        db.session.rollback()
        return jsonify({"error": "project_window", "message": proj_msg}), 400
    # Без автосдвига с выходных — только укладка уже проверенных дат
    clamp_task_dates(task, snap_workdays=False)
    new_start = task.start_date or task.due_date
    if old_start and new_start:
        delta = (new_start - old_start).days
        if delta:
            shift_task_subtree(task, delta)
    sla = gantt_sla_breach(task, task.project)
    if sla and task.project:
        task.is_critical_path = True
    sync_calendar_events_for_task(task)
    shifted = cascade_fs_successors_only(task)
    db.session.commit()
    from servicesystem.project_management.caldav_sync import try_push_task_to_caldav

    try_push_task_to_caldav(task)
    return jsonify(
        {
            "ok": True,
            "start_date": task.start_date.isoformat() if task.start_date else None,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "sla_breach": sla,
            "critical_pulse": sla or bool(task.is_critical_path),
            "fs_shifted": shifted,
            "label_dates": f"{task.start_date.strftime('%d.%m.%Y')} — {task.due_date.strftime('%d.%m.%Y')}"
            if task.start_date and task.due_date
            else "",
        }
    )


@bp.route("/gantt/tasks/<int:tid>/panel", methods=["POST"])
@login_required
def gantt_task_panel(tid):
    """Быстрое редактирование задачи с Ганта (сроки, этап, статус)."""
    _staff_or_curator()
    task = db.session.get(ProjectTask, tid) or abort(404)
    if not (current_user.is_admin or current_user.is_auditor):
        abort(403)
    data = request.get_json(silent=True) or {}
    start_s = (data.get("start_date") or "").strip()
    due_s = (data.get("due_date") or "").strip()
    old_start = task.start_date or task.due_date
    try:
        if start_s:
            task.start_date = date.fromisoformat(start_s)
        if due_s:
            task.due_date = date.fromisoformat(due_s)
    except ValueError:
        return jsonify({"error": "bad_date", "message": "Некорректная дата."}), 400
    if task.start_date and task.due_date and task.due_date < task.start_date:
        task.start_date, task.due_date = task.due_date, task.start_date
    if start_s or due_s:
        nw = non_working_dates_message(task.start_date, task.due_date, task.project)
        if nw:
            db.session.rollback()
            return jsonify({"error": "non_working", "message": nw}), 400
        parent = task.parent
        if parent and not dates_within_parent(task.start_date, task.due_date, parent):
            p_start, p_due = parent_date_window(parent)
            db.session.rollback()
            return jsonify({
                "error": "parent_window",
                "message": (
                    "Сроки должны быть внутри родителя "
                    f"({p_start.strftime('%d.%m.%Y')} — {p_due.strftime('%d.%m.%Y')}). "
                    "Измените даты или сначала сдвиньте родителя."
                    if p_start and p_due
                    else "Сроки должны быть внутри родителя."
                ),
            }), 400
        proj_msg = project_dates_violation_message(task.start_date, task.due_date, task.project)
        if proj_msg:
            db.session.rollback()
            return jsonify({"error": "project_window", "message": proj_msg}), 400
        clamp_task_dates(task, snap_workdays=False)
        new_start = task.start_date or task.due_date
        if old_start and new_start:
            delta = (new_start - old_start).days
            if delta:
                shift_task_subtree(task, delta)
    if "stage_id" in data:
        stage_id = data.get("stage_id")
        if stage_id in ("", None):
            task.stage_id = None
        else:
            try:
                sid = int(stage_id)
            except (TypeError, ValueError):
                return jsonify({"error": "bad_stage"}), 400
            st = db.session.get(ProjectStage, sid)
            if not st or st.project_id != task.project_id:
                return jsonify({"error": "bad_stage"}), 400
            task.stage_id = sid
    status = data.get("kanban_status")
    if status:
        try:
            move_task_kanban(task, status, task.kanban_sort or 0)
        except ValueError as exc:
            if str(exc) == "blocked":
                return jsonify({"error": "blocked"}), 409
            return jsonify({"error": "bad_status"}), 400
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "empty_title"}), 400
        if len(title) > 255:
            return jsonify({"error": "title_too_long"}), 400
        task.title = title
    sync_calendar_events_for_task(task)
    shifted = cascade_fs_successors_only(task) if (start_s or due_s) else []
    db.session.commit()
    return jsonify({
        "ok": True,
        "fs_shifted": shifted,
        "title": task.title,
        "start_date": task.start_date.isoformat() if task.start_date else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
    })


@bp.route("/gantt/links", methods=["POST"])
@login_required
def gantt_link_add():
    """Связь FS (blocks) между задачами с Ганта."""
    _staff_or_curator()
    if not (current_user.is_admin or current_user.is_auditor):
        abort(403)
    data = request.get_json(silent=True) or {}
    from_id = data.get("from_task_id")
    to_id = data.get("to_task_id")
    link_type = data.get("link_type") or "blocks"
    try:
        from_id = int(from_id)
        to_id = int(to_id)
    except (TypeError, ValueError):
        return jsonify({"error": "bad_ids"}), 400
    if from_id == to_id:
        return jsonify({"error": "same"}), 400
    from_task = db.session.get(ProjectTask, from_id) or abort(404)
    to_task = db.session.get(ProjectTask, to_id) or abort(404)
    if from_task.project_id != to_task.project_id:
        return jsonify({"error": "different_project"}), 400
    from servicesystem.project_management.models import ProjectTaskLink

    # На Ганте только FS-предшественник (blocks) или related; blocked_by не создаём
    if link_type == "blocked_by":
        from_id, to_id, link_type = to_id, from_id, "blocks"
        from_task, to_task = to_task, from_task
    if link_type not in ("blocks", "related"):
        return jsonify({"error": "bad_type"}), 400
    if tasks_hierarchically_related(from_task, to_task):
        return jsonify({
            "error": "parent_child",
            "message": "Нельзя связать родительскую задачу с её подзадачей "
            "(родитель = совокупность подзадач). Связи между подзадачами допустимы.",
        }), 400
    if link_type == "blocks":
        bound_msg = fs_link_parent_window_violation(from_task, to_task)
        if bound_msg:
            return jsonify({"error": "parent_window", "message": bound_msg}), 400
    exists = ProjectTaskLink.query.filter_by(
        from_task_id=from_id, to_task_id=to_id, link_type=link_type
    ).first()
    if exists:
        return jsonify({"ok": True, "existing": True})
    db.session.add(ProjectTaskLink(from_task_id=from_id, to_task_id=to_id, link_type=link_type))
    shifted: list[int] = []
    if link_type == "blocks":
        # После связи: вторая задача не раньше дня после окончания первой;
        # родителей расширяем, чтобы окно покрывало подзадачи.
        shifted = apply_fs_cascade_and_expand(to_task)
    db.session.commit()
    return jsonify({"ok": True, "fs_shifted": shifted})


@bp.route("/gantt/links/<int:lid>", methods=["DELETE"])
@login_required
def gantt_link_remove(lid):
    """Удаление связи с Ганта (таблица связей / панель задачи)."""
    _staff_or_curator()
    if not (current_user.is_admin or current_user.is_auditor):
        abort(403)
    from servicesystem.project_management.models import ProjectTaskLink

    link = db.session.get(ProjectTaskLink, lid)
    if not link:
        return jsonify({"error": "not_found"}), 404
    db.session.delete(link)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/gantt/reorder", methods=["POST"])
@login_required
def gantt_reorder():
    """Ручной порядок строк на Ганте (перетаскивание списка слева)."""
    _staff_or_curator()
    if not (current_user.is_admin or current_user.is_auditor):
        abort(403)
    data = request.get_json(silent=True) or {}
    raw_ids = data.get("task_ids") or []
    try:
        task_ids = [int(x) for x in raw_ids]
    except (TypeError, ValueError):
        return jsonify({"error": "bad_ids"}), 400
    if not task_ids:
        return jsonify({"error": "empty"}), 400
    tasks = ProjectTask.query.filter(ProjectTask.id.in_(task_ids)).all()
    by_id = {t.id: t for t in tasks}
    if len(by_id) != len(set(task_ids)):
        return jsonify({"error": "missing"}), 400
    project_ids = {t.project_id for t in tasks}
    if len(project_ids) > 1:
        return jsonify({"error": "mixed_projects"}), 400
    for idx, tid in enumerate(task_ids):
        by_id[tid].gantt_sort = idx + 1
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/tasks/<int:tid>/move", methods=["POST"])
@login_required
def api_move_task(tid):
    _staff_or_curator()
    task = db.session.get(ProjectTask, tid) or abort(404)
    if not user_can_edit_task(current_user, task):
        abort(403)
    data = request.get_json(silent=True) or {}
    status = data.get("status") or request.form.get("status")
    sort = int(data.get("sort") or request.form.get("sort") or 0)
    try:
        move_task_kanban(task, status, sort)
    except ValueError as exc:
        if str(exc) == "blocked":
            return jsonify({"error": "blocked"}), 409
        return jsonify({"error": "bad status"}), 400
    db.session.commit()
    return jsonify({"ok": True})


_WEEKDAY_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_MONTH_RU = ("", "янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


def _week_days():
    """7 дней с текущего дня + подписи на русском (ТЗ 2.2)."""
    start = date.today()
    out = []
    for i in range(7):
        d = start + timedelta(days=i)
        out.append((d, _WEEKDAY_RU[d.weekday()]))
    return out


def _month_grid(cal_mode: str):
    today = date.today()
    if cal_mode == "day":
        return [today]
    if cal_mode == "workweek":
        start = today - timedelta(days=today.weekday())
        return [start + timedelta(days=i) for i in range(5)]
    first = today.replace(day=1)
    start = first - timedelta(days=(first.weekday()))
    return [start + timedelta(days=i) for i in range(42)]


def _task_date_range(t) -> tuple[date, date] | None:
    s = t.start_date or t.due_date
    e = t.due_date or t.start_date
    if not s:
        return None
    e = e or s
    if e < s:
        s, e = e, s
    return s, e


def _tasks_by_day(tasks, days: list[date]) -> dict[date, list]:
    """Задачи на каждый день сетки: start…due, без нерабочих дней проекта."""
    from servicesystem.project_management.work_calendar import is_non_working_day

    day_set = set(days)
    out: dict[date, list] = {d: [] for d in days}
    for t in tasks:
        rng = _task_date_range(t)
        if not rng:
            continue
        s, e = rng
        proj = t.project
        d = s
        while d <= e:
            if d in day_set and not is_non_working_day(d, proj):
                out[d].append(t)
            d += timedelta(days=1)
            if (d - s).days > 800:
                break
    return out


def _team_load(tasks):
    """Нагрузка по дням: только рабочие дни проекта."""
    from servicesystem.project_management.work_calendar import is_non_working_day

    load: dict[date, int] = {}
    for t in tasks:
        rng = _task_date_range(t)
        if not rng:
            continue
        s, e = rng
        proj = t.project
        d = s
        while d <= e:
            if not is_non_working_day(d, proj):
                load[d] = load.get(d, 0) + 1
            d += timedelta(days=1)
            if (d - s).days > 800:
                break
    return load


def _calendar_executors(
    project_id: int | None,
    projects,
    extra_ids: list[int] | None = None,
) -> list[User]:
    """Исполнители для фильтра календаря: по проекту или объединение видимых."""
    seen: set[int] = set()
    out: list[User] = []
    if project_id:
        base = executors_for_project(project_id)
    else:
        base = []
        for p in projects or []:
            base.extend(executors_for_project(p.id))
    for u in base:
        if u.id in seen:
            continue
        seen.add(u.id)
        out.append(u)
    missing = [i for i in (extra_ids or []) if i not in seen]
    if missing:
        for u in User.query.filter(User.id.in_(missing), User.is_active.is_(True)).all():
            if u.id in seen:
                continue
            seen.add(u.id)
            out.append(u)
    out.sort(key=lambda u: (u.full_name or "").lower())
    return out


def _task_people(t) -> list[User]:
    """Исполнитель + соисполнители задачи."""
    people: list[User] = []
    seen: set[int] = set()
    if t.assignee_id and t.assignee:
        people.append(t.assignee)
        seen.add(t.assignee_id)
    for c in t.collaborators.all():
        if c.user_id in seen or not c.user:
            continue
        seen.add(c.user_id)
        people.append(c.user)
    return people


def _task_involves_user(t, user_id: int) -> bool:
    if t.assignee_id == user_id:
        return True
    return any(c.user_id == user_id for c in t.collaborators.all())


def _executor_workload(tasks, days: list[date]) -> list[dict]:
    """Загрузка исполнителей: человеко-дни только по рабочим дням проекта."""
    from servicesystem.project_management.work_calendar import is_non_working_day

    day_set = set(days)
    load: dict[int, int] = {}
    names: dict[int, str] = {}
    for t in tasks:
        rng = _task_date_range(t)
        if not rng:
            continue
        s, e = rng
        proj = t.project
        days_in = 0
        d = s
        while d <= e:
            if d in day_set and not is_non_working_day(d, proj):
                days_in += 1
            d += timedelta(days=1)
            if (d - s).days > 800:
                break
        if not days_in:
            continue
        for u in _task_people(t):
            load[u.id] = load.get(u.id, 0) + days_in
            names[u.id] = u.full_name or f"#{u.id}"
    return [
        {"id": uid, "name": names[uid], "load": load[uid]}
        for uid in sorted(load.keys(), key=lambda i: (-load[i], names[i].lower()))
    ]


def _format_gantt_tick(d: date, scale: str) -> str:
    wd = _WEEKDAY_RU[d.weekday()]
    if scale == "quarter":
        return f"{_MONTH_RU[d.month].capitalize()} {d.year}"
    if scale == "month":
        return f"{wd} {d.strftime('%d.%m')}"
    if scale == "week":
        return f"{wd} {d.strftime('%d.%m')}"
    if scale == "day":
        return d.strftime("%d.%m.%Y")
    return d.strftime("%d.%m.%Y")


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    return (_month_start(d) + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def _add_months(d: date, months: int) -> date:
    m0 = d.month - 1 + months
    y = d.year + m0 // 12
    m = m0 % 12 + 1
    return date(y, m, 1)


def _quarter_start(d: date) -> date:
    qm = ((d.month - 1) // 3) * 3 + 1
    return d.replace(month=qm, day=1)


def _quarter_end(d: date) -> date:
    qs = _quarter_start(d)
    return _month_end(_add_months(qs, 2))


def _gantt_base_window(scale: str, today: date) -> tuple[date, date]:
    """Минимальное окно вокруг «сегодня» для выбранного масштаба."""
    if scale == "day":
        return today - timedelta(days=7), today + timedelta(days=7)
    if scale == "week":
        start = today - timedelta(days=today.weekday())
        return start - timedelta(days=7), start + timedelta(days=13)
    if scale == "quarter":
        return _quarter_start(today), _quarter_end(today)
    start = _month_start(today)
    return start, _month_end(today)


def _gantt_data_extent(tasks) -> tuple[date | None, date | None]:
    """Крайние даты задач и вех этапов видимого набора."""
    dates: list[date] = []
    project_ids: set[int] = set()
    for t in tasks:
        if t.start_date:
            dates.append(t.start_date)
        if t.due_date:
            dates.append(t.due_date)
        if t.project_id:
            project_ids.add(t.project_id)
    if project_ids:
        for st in ProjectStage.query.filter(
            ProjectStage.project_id.in_(project_ids),
            ProjectStage.deadline.isnot(None),
        ):
            if st.deadline:
                dates.append(st.deadline)
    if not dates:
        return None, None
    return min(dates), max(dates)


def _gantt_align_span(scale: str, start: date, end: date) -> tuple[date, date]:
    """Выравнивание под сетку колонок без запаса за пределы периода."""
    if end < start:
        start, end = end, start
    if scale == "quarter":
        return _month_start(start), _month_end(end)
    if scale == "month":
        return start, end
    if scale == "week":
        s = start - timedelta(days=start.weekday())
        e = end + timedelta(days=(6 - end.weekday()) % 7)
        return s, e
    return start, end


def _gantt_projects_for_span(projects, tasks) -> list:
    """Проекты для шкалы: явный список или уникальные проекты задач."""
    seen: dict[int, object] = {}
    for p in projects or []:
        if p is not None and getattr(p, "id", None) is not None:
            seen[p.id] = p
    for t in tasks or []:
        p = getattr(t, "project", None)
        if p is not None and getattr(p, "id", None) is not None and p.id not in seen:
            seen[p.id] = p
    return list(seen.values())


def _gantt_project_extent(projects) -> tuple[date | None, date | None]:
    """Крайние даты проектов: planned_start … deadline (прокрутка Ганта)."""
    starts: list[date] = []
    ends: list[date] = []
    for p in projects or []:
        if getattr(p, "planned_start", None):
            starts.append(p.planned_start)
        if getattr(p, "deadline", None):
            ends.append(p.deadline)
    if not starts and not ends:
        return None, None
    start = min(starts) if starts else min(ends)
    end = max(ends) if ends else max(starts)
    if end < start:
        start, end = end, start
    return start, end


def _gantt_period_label_from_projects(projects) -> str:
    """Подпись периода проекта для Ганта (как в карточке проекта)."""
    start, end = _gantt_project_extent(projects or [])
    if start and end:
        return f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"
    if end:
        return f"до {end.strftime('%d.%m.%Y')}"
    if start:
        return f"с {start.strftime('%d.%m.%Y')}"
    return ""


def _gantt_span_for_scale(
    scale: str,
    today: date,
    *,
    tasks=None,
    projects=None,
    anchor: date | None = None,
) -> tuple[date, date]:
    """
    Шкала = старт…дедлайн проекта (из карточки).
    Расширяем только если задачи/этапы выходят за эти границы; не укорачиваем.
    """
    pivot = anchor or today
    span_projects = _gantt_projects_for_span(projects, tasks)
    proj_s, proj_e = _gantt_project_extent(span_projects)
    work_s, work_e = _gantt_data_extent(tasks or [])

    if proj_s and proj_e:
        start, end = proj_s, proj_e
        if work_s and work_s < start:
            start = work_s
        if work_e and work_e > end:
            end = work_e
        return _gantt_align_span(scale, start, end)

    if proj_s or proj_e:
        start = proj_s or work_s or pivot
        end = proj_e or work_e or pivot
        if work_s and work_s < start:
            start = work_s
        if work_e and work_e > end:
            end = work_e
        return _gantt_align_span(scale, start, end)

    if work_s and work_e:
        return _gantt_align_span(scale, work_s, work_e)
    start, end = _gantt_base_window(scale, pivot)
    return _gantt_align_span(scale, start, end)


def _gantt_col_px(scale: str, n_cols: int) -> int:
    """Ширина колонки под масштаб — от неё зависит ползунок горизонтальной прокрутки."""
    # Квартал: широкие месячные колонки — подписи этапов не наезжают друг на друга
    base = {"day": 96, "week": 72, "month": 52, "quarter": 280}.get(scale, 56)
    # На очень длинной шкале чуть ужмём, чтобы ползунок оставался управляемым
    if scale != "quarter" and n_cols > 120:
        return max(32, base - 12)
    if scale == "quarter" and n_cols > 18:
        return max(200, base - 40)
    return base


def _gantt_columns(span_start: date, span_end: date, scale: str) -> list[dict]:
    """Колонки шкалы (без наложения подписей)."""
    cols: list[dict] = []
    if scale == "quarter":
        d = span_start.replace(day=1)
        while d <= span_end:
            cols.append(
                {
                    "date": d,
                    "label": f"{_MONTH_RU[d.month].capitalize()} {d.year}",
                    "is_today": d.month == date.today().month and d.year == date.today().year,
                }
            )
            nm = d.month + 1 if d.month < 12 else 1
            ny = d.year if d.month < 12 else d.year + 1
            d = d.replace(year=ny, month=nm, day=1)
        return cols or [{"date": span_start, "label": _format_gantt_tick(span_start, scale), "is_today": False}]

    d = span_start
    while d <= span_end:
        if scale == "day":
            label = f"{_WEEKDAY_RU[d.weekday()]}, {d.strftime('%d.%m.%Y')}"
        elif scale == "week":
            label = f"{_WEEKDAY_RU[d.weekday()]}\n{d.strftime('%d.%m')}"
        else:
            label = f"{d.day}\n{_WEEKDAY_RU[d.weekday()]}" if d.day == 1 or d.weekday() == 0 else str(d.day)
        cols.append({"date": d, "label": label, "is_today": d == date.today()})
        d += timedelta(days=1)
    return cols


def _task_overlaps_span(s: date, e: date, span_start: date, span_end: date) -> bool:
    return s <= span_end and e >= span_start


def _days_in_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def _gantt_bar_caption(s: date, e: date, width_pct: float = 100.0) -> str:
    """Полный диапазон на полоске (не режем по % ширины — места хватает в px)."""
    if s == e:
        return s.strftime("%d.%m")
    return f"{s.strftime('%d.%m')}–{e.strftime('%d.%m')}"


def _gantt_short_title(title: str, max_len: int = 32) -> str:
    t = (title or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _gantt_link_pair(link) -> tuple[int, int, str] | None:
    if link.link_type == "blocks":
        return link.from_task_id, link.to_task_id, "blocks"
    if link.link_type == "blocked_by":
        return link.to_task_id, link.from_task_id, "blocks"
    if link.link_type == "related":
        return link.from_task_id, link.to_task_id, "related"
    return None


def _gantt_task_relations(tasks, links) -> tuple[dict[int, list], dict[int, list], dict[int, list]]:
    """Связи для подписей: ждёт / блокирует / связана с."""
    title_by_id = {t.id: _gantt_short_title(t.title, 42) for t in tasks}
    waits_for: dict[int, list] = {i: [] for i in title_by_id}
    blocks: dict[int, list] = {i: [] for i in title_by_id}
    related_with: dict[int, list] = {i: [] for i in title_by_id}

    def _ref(tid: int, link_id: int) -> dict:
        return {"id": tid, "title": title_by_id[tid], "link_id": link_id}

    for link in links:
        pair = _gantt_link_pair(link)
        if not pair:
            continue
        pred_id, succ_id, kind = pair
        if pred_id not in title_by_id or succ_id not in title_by_id:
            continue
        if kind == "blocks":
            waits_for[succ_id].append(_ref(pred_id, link.id))
            blocks[pred_id].append(_ref(succ_id, link.id))
        else:
            related_with[pred_id].append(_ref(succ_id, link.id))
            related_with[succ_id].append(_ref(pred_id, link.id))
    return waits_for, blocks, related_with


def _gantt_link_edges(bars: list[dict], links) -> list[dict]:
    """Список связей для блока под диаграммой (без SVG)."""
    by_id = {b["task"].id: b for b in bars}
    edges: list[dict] = []
    for link in links:
        pair = _gantt_link_pair(link)
        if not pair:
            continue
        pred_id, succ_id, kind = pair
        pb = by_id.get(pred_id)
        sb = by_id.get(succ_id)
        if not pb or not sb or not pb["in_range"] or not sb["in_range"]:
            continue
        edges.append(
            {
                "id": link.id,
                "kind": kind,
                "type_label": GANTT_LINK_TYPE_LABELS.get(kind, kind),
                "from_title": _gantt_short_title(pb["task"].title, 48),
                "to_title": _gantt_short_title(sb["task"].title, 48),
                "from_task_id": pred_id,
                "to_task_id": succ_id,
                "from_row": pb["row"] + 1,
                "to_row": sb["row"] + 1,
            }
        )
    return edges


def _gantt_apply_row_numbers(bars: list[dict]) -> None:
    no_by_id = {b["task"].id: b["row"] + 1 for b in bars}
    wbs_by_id = {b["task"].id: b.get("wbs") or str(b["row"] + 1) for b in bars}
    for b in bars:
        b["display_no"] = b["row"] + 1
        if not b.get("wbs"):
            b["wbs"] = str(b["display_no"])
        b["waits_for"] = [
            {**w, "no": no_by_id.get(w["id"]), "wbs": wbs_by_id.get(w["id"])}
            for w in b.get("waits_for", [])
        ]
        b["blocks"] = [
            {**x, "no": no_by_id.get(x["id"]), "wbs": wbs_by_id.get(x["id"])}
            for x in b.get("blocks", [])
        ]


def _gantt_date_center_pct(
    d: date,
    span_start: date,
    span_end: date,
    scale: str,
    n_cols: int,
) -> float | None:
    """Горизонтальная позиция (центр дня) на шкале — для вех и пунктира дедлайна."""
    in_r, left, width = _bar_geometry(d, d, span_start, span_end, scale, n_cols)
    if not in_r:
        return None
    return min(99.5, left + width / 2.0)


def _bar_geometry(
    s: date,
    e: date,
    span_start: date,
    span_end: date,
    scale: str,
    n_cols: int,
) -> tuple[bool, float, float]:
    if not _task_overlaps_span(s, e, span_start, span_end):
        return False, 0.0, 0.0
    vis_s = max(s, span_start)
    vis_e = min(e, span_end)
    n = max(1, n_cols)
    if scale == "quarter":

        def _month_pos(d: date, end_of_day: bool) -> float:
            slot = (d.year - span_start.year) * 12 + d.month - span_start.month
            dim = _days_in_month(d)
            frac = d.day / dim if end_of_day else (d.day - 1) / dim
            return slot + min(1.0, max(0.0, frac))

        start_f = _month_pos(vis_s, end_of_day=False)
        end_f = _month_pos(vis_e, end_of_day=True)
    else:
        start_f = float((vis_s - span_start).days)
        end_f = float((vis_e - span_start).days + 1)
    left_pct = max(0.0, (start_f / n) * 100)
    width_pct = max(0.4, ((end_f - start_f) / n) * 100)
    # Минимальная ширина только для день/неделя (кликабельность).
    # На квартале/месяце раздувание до ~½ колонки ломало последовательность FS-стрелок.
    min_col = 100.0 / n
    if scale == "day":
        width_pct = max(width_pct, min_col * 0.85)
    elif scale == "week":
        width_pct = max(width_pct, min_col * 0.4)
    width_pct = min(width_pct, 100.0 - left_pct)
    return True, left_pct, width_pct


def _gantt_collect_dated(tasks) -> list[tuple]:
    dated: list[tuple] = []
    for t in tasks:
        s = t.start_date or t.due_date
        e = t.due_date or t.start_date
        if not s:
            continue
        e = e or s
        if e < s:
            s, e = e, s
        dated.append((t, s, e))
    return dated


def _gantt_tree_order(items: list[tuple]) -> list[tuple]:
    """Родитель → дети: (task, *rest, depth, wbs). WBS: 1, 1.1, 1.2.1 по порядку gantt_sort."""
    if not items:
        return []
    by_id = {it[0].id: it for it in items}
    children: dict[int | None, list[int]] = {None: []}
    for it in items:
        t = it[0]
        pid = t.parent_id if t.parent_id in by_id else None
        children.setdefault(pid, []).append(t.id)
    for pid, ids in children.items():
        ids.sort(key=lambda i: gantt_sort_key(by_id[i][0]))

    out: list[tuple] = []
    visited: set[int] = set()

    def walk(tid: int, depth: int, parts: list[int]) -> None:
        if tid in visited:
            return
        visited.add(tid)
        it = by_id[tid]
        wbs = ".".join(str(p) for p in parts)
        out.append((*it, depth, wbs))
        for j, cid in enumerate(children.get(tid, []), start=1):
            walk(cid, depth + 1, parts + [j])

    roots = children.get(None, [])
    for i, tid in enumerate(roots, start=1):
        walk(tid, 0, [i])
    n_root = len(roots)
    for tid in by_id:
        if tid not in visited:
            n_root += 1
            walk(tid, 0, [n_root])
    return out


def _gantt_milestones(
    tasks,
    span_start: date,
    span_end: date,
    scale: str,
    n_cols: int,
) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple] = set()
    project_ids = {t.project_id for t in tasks if t.project_id}
    if project_ids:
        for st in ProjectStage.query.filter(
            ProjectStage.project_id.in_(project_ids),
            ProjectStage.deadline.isnot(None),
        ):
            if not st.deadline or st.deadline < span_start or st.deadline > span_end:
                continue
            key = ("stage", st.id)
            if key in seen:
                continue
            seen.add(key)
            center = _gantt_date_center_pct(st.deadline, span_start, span_end, scale, n_cols)
            if center is None:
                continue
            in_r, left, w = _bar_geometry(st.deadline, st.deadline, span_start, span_end, scale, n_cols)
            if not in_r:
                continue
            col_w = 100.0 / max(1, n_cols)
            pname = st.project.name if st.project else ""
            cap = _gantt_short_title(st.title, 28)
            out.append(
                {
                    "id": st.id,
                    "title": st.title,
                    "short_title": cap,
                    "project": pname,
                    "deadline": st.deadline,
                    "date_label": st.deadline.strftime("%d.%m.%Y"),
                    "left_pct": left,
                    "width_pct": col_w,
                    "center_pct": center,
                }
            )
    out.sort(key=lambda m: m["left_pct"])
    return out[:20]


def _mark_stage_deadline_columns(columns: list[dict], milestones: list[dict], scale: str) -> None:
    """Пометить колонки шкалы, на которые попадают дедлайны этапов."""
    for col in columns:
        col.setdefault("is_stage_deadline", False)
        col.setdefault("stage_deadline_titles", [])
    if not milestones:
        return
    for m in milestones:
        d = m.get("deadline")
        if not d:
            continue
        for col in columns:
            cd = col.get("date")
            if not cd:
                continue
            if scale == "quarter":
                hit = cd.month == d.month and cd.year == d.year
            else:
                hit = cd == d
            if hit:
                col["is_stage_deadline"] = True
                title = m.get("short_title") or m.get("title") or "Этап"
                tip = f"{title} · {m.get('date_label') or d.strftime('%d.%m.%Y')}"
                if tip not in col["stage_deadline_titles"]:
                    col["stage_deadline_titles"].append(tip)


def _gantt_milestone_groups(
    milestones: list[dict],
    *,
    min_gap_pct: float = 5.0,
    n_cols: int = 1,
) -> list[dict]:
    """Каждый этап — отдельная веха (не склеиваем, чтобы все этапы были видны)."""
    del min_gap_pct, n_cols  # порог склейки больше не используем
    if not milestones:
        return []
    ordered = sorted(milestones, key=lambda m: (m["center_pct"], m["date_label"], m["title"]))
    return [{"center_pct": m["center_pct"], "milestones": [m]} for m in ordered]


def _gantt_build_bars(
    dated: list[tuple],
    span_start: date,
    span_end: date,
    scale: str,
    n_cols: int,
    waits_for,
    blocks,
    related_with,
    user,
    row_offset: int = 0,
) -> list[dict]:
    bars = []
    for idx, item in enumerate(dated):
        t = item[0]
        s, e = item[1], item[2]
        # хвост: depth, wbs (после _gantt_tree_order)
        depth = 0
        wbs = str(row_offset + idx + 1)
        if len(item) >= 5 and isinstance(item[-1], str) and isinstance(item[-2], int):
            depth = max(0, int(item[-2]))
            wbs = item[-1]
        elif len(item) >= 4 and isinstance(item[3], int):
            depth = max(0, int(item[3]))
        in_range, left_pct, width_pct = _bar_geometry(s, e, span_start, span_end, scale, n_cols)
        sla = gantt_sla_breach(t, t.project)
        critical = sla or bool(t.is_critical_path)
        bars.append(
            {
                "task": t,
                "row": row_offset + idx,
                "depth": depth,
                "wbs": wbs,
                "left_pct": left_pct,
                "width_pct": width_pct,
                "bar_caption": _gantt_bar_caption(s, e, width_pct if in_range else 0),
                "in_range": in_range,
                "sla": sla,
                "critical_pulse": critical,
                "label_dates": f"{s.strftime('%d.%m.%Y')} — {e.strftime('%d.%m.%Y')}",
                "status_label": KANBAN_LABELS.get(t.kanban_status, t.kanban_status),
                "waits_for": waits_for.get(t.id, []),
                "blocks": blocks.get(t.id, []),
                "related_with": related_with.get(t.id, []),
                "can_drag": user_can_reschedule_gantt(user, t) if user else False,
                "can_edit_panel": bool(user and (user.is_admin or user.is_auditor)),
                "open_as_ticket": task_opens_as_ticket(t),
                "ticket_id": t.ticket_id,
                "stage_id": t.stage_id,
                "stage_title": t.stage.title if t.stage else None,
                "start_iso": s.isoformat(),
                "due_iso": e.isoformat(),
                "kanban_status": t.kanban_status,
                "project_deadline": t.project.deadline.isoformat()
                if t.project and t.project.deadline
                else "",
                "parent_start_iso": (
                    (t.parent.start_date or t.parent.due_date).isoformat()
                    if t.parent and (t.parent.start_date or t.parent.due_date)
                    else ""
                ),
                "parent_due_iso": (
                    (t.parent.due_date or t.parent.start_date).isoformat()
                    if t.parent and (t.parent.start_date or t.parent.due_date)
                    else ""
                ),
                "project_start_iso": (
                    t.project.planned_start.isoformat()
                    if t.project and t.project.planned_start
                    else ""
                ),
            }
        )
    return bars


def _gantt_layout(
    tasks,
    scale: str,
    *,
    group_by: str = "project",
    user=None,
    project_filter: int | None = None,
    anchor: date | None = None,
    projects=None,
) -> dict:
    """Данные для диаграммы Gantt — стратегическое планирование (ТЗ 2.1)."""
    today = date.today()
    projects = _gantt_projects_for_span(projects, tasks)
    span_start, span_end = _gantt_span_for_scale(
        scale, today, tasks=tasks, projects=projects, anchor=anchor
    )
    if scale == "quarter":
        span_start = _month_start(span_start)
        span_end = _month_end(span_end)
    columns = _gantt_columns(span_start, span_end, scale)
    n_cols = max(1, len(columns))
    col_px = _gantt_col_px(scale, n_cols)
    dated_flat = _gantt_collect_dated(tasks)
    dated = _gantt_tree_order(dated_flat)
    task_list = [it[0] for it in dated]
    links = _gantt_links(task_list)
    waits_for, blocks, related_with = _gantt_task_relations(task_list, links)

    groups: list[dict] = []
    if group_by == "project" and not project_filter:
        by_pid: dict[int, list] = {}
        for item in dated_flat:
            t = item[0]
            by_pid.setdefault(t.project_id or 0, []).append(item)
        order = sorted(
            by_pid.keys(),
            key=lambda pid: (
                (by_pid[pid][0][0].project.name if by_pid[pid][0][0].project else "яяя"),
                pid,
            ),
        )
        row_off = 0
        for pid in order:
            chunk = _gantt_tree_order(by_pid[pid])
            proj = chunk[0][0].project if chunk else None
            bars = _gantt_build_bars(
                chunk, span_start, span_end, scale, n_cols,
                waits_for, blocks, related_with, user, row_off,
            )
            row_off += len(bars)
            groups.append(
                {
                    "project_id": pid or None,
                    "title": proj.name if proj else "Без проекта",
                    "period_label": _project_period_label(proj),
                    "deadline_label": proj.deadline.strftime("%d.%m.%Y") if proj and proj.deadline else "",
                    "bars": bars,
                }
            )
    else:
        bars = _gantt_build_bars(
            dated, span_start, span_end, scale, n_cols,
            waits_for, blocks, related_with, user, 0,
        )
        proj = None
        if project_filter:
            proj = db.session.get(Project, project_filter)
        groups.append(
            {
                "project_id": project_filter,
                "title": proj.name if proj else "Задачи",
                "period_label": _project_period_label(proj),
                "deadline_label": proj.deadline.strftime("%d.%m.%Y") if proj and proj.deadline else "",
                "bars": bars,
            }
        )

    gantt_bars = [b for g in groups for b in g["bars"]]
    _gantt_apply_row_numbers(gantt_bars)

    dated_ids = {it[0].id for it in dated_flat}
    undated_flat = [
        (t,)
        for t in tasks
        if t.id not in dated_ids and not (t.start_date or t.due_date)
    ]
    undated_ordered = _gantt_tree_order(undated_flat)
    undated_row0 = len(gantt_bars)
    gantt_undated: list[dict] = []
    for i, item in enumerate(undated_ordered):
        t = item[0]
        depth = 0
        wbs = str(undated_row0 + i + 1)
        if len(item) >= 3 and isinstance(item[-1], str) and isinstance(item[-2], int):
            depth = max(0, int(item[-2]))
            wbs = item[-1]
        gantt_undated.append(
            {
                "task": t,
                "row": undated_row0 + i,
                "depth": depth,
                "wbs": wbs,
                "display_no": undated_row0 + i + 1,
                "status_label": KANBAN_LABELS.get(t.kanban_status, t.kanban_status),
                "open_as_ticket": task_opens_as_ticket(t),
                "ticket_id": t.ticket_id,
                "can_edit_panel": bool(user and (user.is_admin or user.is_auditor)),
                "can_drag": False,
            }
        )

    if span_start == span_end:
        span_label = span_start.strftime("%d.%m.%Y")
    else:
        span_label = f"{span_start.strftime('%d.%m.%Y')} — {span_end.strftime('%d.%m.%Y')}"
    period_label = _gantt_period_label_from_projects(projects) or span_label

    link_edges = _gantt_link_edges(gantt_bars, links)
    gantt_milestones = _gantt_milestones(task_list, span_start, span_end, scale, n_cols)
    _mark_stage_deadline_columns(columns, gantt_milestones, scale)
    gantt_milestone_groups = _gantt_milestone_groups(gantt_milestones, n_cols=n_cols)
    milestone_stack_max = max((len(g["milestones"]) for g in gantt_milestone_groups), default=0)
    # Полоска вех: ромб + короткая подпись этапа
    milestone_lane_h = (28 if milestone_stack_max else 0)
    return {
        "gantt_bars": gantt_bars,
        "gantt_groups": groups,
        "gantt_undated": gantt_undated,
        "gantt_columns": columns,
        "gantt_milestones": gantt_milestones,
        "gantt_milestone_groups": gantt_milestone_groups,
        "gantt_milestone_lane_min_h": milestone_lane_h,
        "gantt_fs_links": [
            {
                "id": e["id"],
                "from_id": e["from_task_id"],
                "to_id": e["to_task_id"],
                "from_title": e.get("from_title") or "",
                "to_title": e.get("to_title") or "",
                "label": f"{e.get('from_title') or '…'} → {e.get('to_title') or '…'}",
            }
            for e in link_edges
            if e.get("kind") == "blocks"
        ],
        "gantt_span_label": span_label,
        "gantt_period_label": period_label,
        "gantt_span_start": span_start.isoformat(),
        "gantt_span_end": span_end.isoformat(),
        "gantt_today": today,
        "gantt_col_px": col_px,
        "gantt_timeline_min_px": n_cols * col_px,
        "gantt_links": links,
        "gantt_link_edges": link_edges,
        "project_link_labels": PROJECT_LINK_LABELS,
        "gantt_scale_label": {
            "day": "Зум: день",
            "week": "Зум: неделя",
            "month": "Зум: месяц",
            "quarter": "Зум: квартал",
        }.get(scale, ""),
    }


def _gantt_links(tasks):
    ids = {t.id for t in tasks}
    if not ids:
        return []
    from servicesystem.project_management.models import ProjectTaskLink

    out = []
    for link in ProjectTaskLink.query.filter(
        ProjectTaskLink.from_task_id.in_(ids),
        ProjectTaskLink.to_task_id.in_(ids),
        ProjectTaskLink.link_type.in_(("blocks", "blocked_by", "related")),
    ):
        out.append(link)
    return out


from servicesystem.project_management import task_routes  # noqa: F401, E402
