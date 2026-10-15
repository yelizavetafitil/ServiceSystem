"""ARM проектов: Kanban, неделя, календарь, Gantt (ТЗ 2)."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
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
    duplicate_task,
    gantt_sla_breach,
    kanban_sort_key,
    move_task_kanban,
    project_from_template,
    rollover_overdue_tasks,
    sync_calendar_events_for_task,
    task_opens_as_ticket,
    tasks_for_user_query,
    update_customer_curator_window,
    user_can_create_task,
    user_can_edit_task,
    user_can_manage_project,
    user_can_reschedule_gantt,
    user_can_view_custom_field,
)

bp = Blueprint("projects", __name__)

KANBAN_LABELS = {
    "todo": "К исполнению",
    "in_progress": "В работе",
    "review": "На верификации",
    "done": "Выполнено",
}

PROJECT_LINK_LABELS = {
    "blocks": "Блокирующая",
    "blocked_by": "Ожидающая",
    "related": "Связывающая",
}

GANTT_LINK_TYPE_LABELS = {
    "blocks": "Блокирующая (конец → начало)",
    "related": "Связывающая",
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


def _staff_or_curator():
    if not current_user.is_authenticated:
        abort(403)
    if current_user.is_staff or current_user.role == "customer_curator":
        return
    abort(403)


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
    if view not in ("kanban", "week", "calendar", "gantt"):
        view = "kanban"
    if current_user.is_staff:
        try:
            rollover_overdue_tasks()
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("rollover_overdue_tasks failed")
    project_id = request.args.get("project", type=int)
    gantt_scale = (request.args.get("scale") or "week").lower()
    if gantt_scale not in ("day", "week", "month", "quarter"):
        gantt_scale = "month"
    gantt_group = (request.args.get("group") or ("project" if not project_id else "none")).lower()
    if gantt_group not in ("project", "none"):
        gantt_group = "project"
    cal_mode = request.args.get("cal_mode", "month")
    projects = _projects_visible()
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
    tasks = sorted(tasks_q.all(), key=kanban_sort_key)
    ctx = dict(
        view=view,
        projects=projects,
        filter_project=project_id,
        tasks=tasks,
        kanban_labels=KANBAN_LABELS,
        columns=TASK_KANBAN_COLUMNS,
        today=date.today(),
        gantt_scale=gantt_scale,
        gantt_group=gantt_group,
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
        return render_template("projects/week.html", **ctx, week_days=_week_days())
    if view == "calendar":
        return render_template(
            "projects/calendar.html",
            **ctx,
            month_grid=_month_grid(cal_mode),
            team_load=_team_load(tasks) if cal_mode == "team" else None,
        )
    gantt = _gantt_layout(
        tasks,
        gantt_scale,
        group_by=gantt_group,
        user=current_user,
        project_filter=project_id,
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
                responsible_id=request.form.get("stage_responsible_id", type=int),
                sort_order=proj.stages.count(),
            )
            db.session.add(st)
            db.session.commit()
            flash("Этап добавлен.", "success")
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
            proj.curator_auditor_id = request.form.get("curator_auditor_id", type=int)
            proj.customer_curator_id = request.form.get("customer_curator_id", type=int) or None
            proj.description = (request.form.get("description") or "").strip() or None
            update_customer_curator_window(proj)
            db.session.commit()
            flash("Сохранено.", "success")
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
    executors = User.query.filter_by(role="executor", is_active=True).all()
    parent_task = db.session.get(ProjectTask, parent_id) if parent_id else None
    if parent_task and not preset_project_id:
        preset_project_id = parent_task.project_id
    stages_by_project: dict[int, list] = {}
    for p in projects:
        stages_by_project[p.id] = [
            {"id": s.id, "title": s.title}
            for s in p.stages.order_by(ProjectStage.sort_order)
        ]
    if parent_task and parent_task.project_id not in stages_by_project:
        stages_by_project[parent_task.project_id] = [
            {"id": s.id, "title": s.title}
            for s in parent_task.project.stages.order_by(ProjectStage.sort_order)
        ] if parent_task.project else []
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        project_id = request.form.get("project_id", type=int)
        if parent_task:
            project_id = parent_task.project_id
        if not title or not project_id:
            flash("Укажите проект и название задачи.", "warning")
            return redirect(url_for("projects.task_new", project=preset_project_id, parent=parent_id))
        stage_id = request.form.get("stage_id", type=int) or None
        if parent_task and not stage_id:
            stage_id = parent_task.stage_id
        task = ProjectTask(
            project_id=project_id,
            stage_id=stage_id,
            parent_id=parent_task.id if parent_task else (request.form.get("parent_id", type=int) or None),
            title=title,
            description=(request.form.get("description") or "").strip() or None,
            priority=int(request.form.get("priority") or 2),
            assignee_id=request.form.get("assignee_id", type=int) or None,
            due_date=_parse_form_date(request.form.get("due_date")),
            start_date=_parse_form_date(request.form.get("start_date")),
            kanban_status="todo",
            created_by_id=current_user.id,
        )
        db.session.add(task)
        db.session.flush()
        for uid in request.form.getlist("collaborator_ids"):
            db.session.add(ProjectTaskCollaborator(task_id=task.id, user_id=int(uid)))
        from servicesystem.project_management.services import sync_calendar_events_for_task

        sync_calendar_events_for_task(task)
        db.session.commit()
        flash("Задача создана.", "success")
        return redirect(url_for("projects.task_detail", tid=task.id))
    return render_template(
        "projects/task_form.html",
        task=None,
        projects=projects,
        executors=executors,
        parent_id=parent_id,
        parent_task=parent_task,
        preset_project_id=preset_project_id,
        stages_by_project=stages_by_project,
        preset_stage_id=parent_task.stage_id if parent_task else None,
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
    tab = request.args.get("tab", "main")
    executors = User.query.filter_by(role="executor", is_active=True).all()
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
    task_files: list = []
    deletable_file_ids: set[int] = set()
    preview_aid = request.args.get("preview", type=int)
    if tab == "files":
        task_files = list(list_task_attachments(task.id))
        known_ids = {f.id for f in task_files}
        if preview_aid:
            att = db.session.get(ProjectTaskAttachment, preview_aid)
            if att and att.task_id == task.id:
                preview_att = att
                if att.id not in known_ids:
                    task_files.insert(0, att)
            else:
                preview_att = None
        elif task_files:
            preview_att = task_files[0]
        for f in task_files:
            if user_can_delete_task_attachment(current_user, task, f):
                deletable_file_ids.add(f.id)
    return render_template(
        "projects/task_detail.html",
        task=task,
        task_files=task_files,
        deletable_file_ids=deletable_file_ids,
        preview_att=preview_att,
        kanban_labels=KANBAN_LABELS,
        tab=tab,
        executors=executors,
        custom_fields=custom_fields,
        link_rows=link_rows,
        link_rows_in=link_rows_in,
        sibling_tasks=sibling_tasks,
        project_stages=project_stages,
        blocked=blocked,
        subtasks=subtasks,
        collaborator_ids=collaborator_ids,
        time_logs=time_logs,
        link_type_choices=list(PROJECT_LINK_LABELS.items()),
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
    if start_d:
        task.start_date = start_d
    if due_d:
        task.due_date = due_d
    if task.start_date and not task.due_date:
        task.due_date = task.start_date
    if task.due_date and not task.start_date:
        task.start_date = task.due_date
    sla = gantt_sla_breach(task, task.project)
    if sla and task.project:
        task.is_critical_path = True
    sync_calendar_events_for_task(task)
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
    try:
        if start_s:
            task.start_date = date.fromisoformat(start_s)
        if due_s:
            task.due_date = date.fromisoformat(due_s)
    except ValueError:
        return jsonify({"error": "bad_date"}), 400
    if task.start_date and task.due_date and task.due_date < task.start_date:
        task.start_date, task.due_date = task.due_date, task.start_date
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
    sync_calendar_events_for_task(task)
    db.session.commit()
    return jsonify({"ok": True})


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
    from servicesystem.project_management.models import TASK_LINK_TYPES, ProjectTaskLink

    if link_type not in TASK_LINK_TYPES:
        return jsonify({"error": "bad_type"}), 400
    exists = ProjectTaskLink.query.filter_by(
        from_task_id=from_id, to_task_id=to_id, link_type=link_type
    ).first()
    if exists:
        return jsonify({"ok": True, "existing": True})
    db.session.add(ProjectTaskLink(from_task_id=from_id, to_task_id=to_id, link_type=link_type))
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


def _team_load(tasks):
    load: dict[date, int] = {}
    for t in tasks:
        if t.due_date:
            load[t.due_date] = load.get(t.due_date, 0) + 1
    return load


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


def _gantt_span_for_scale(scale: str, today: date) -> tuple[date, date]:
    if scale == "day":
        return today, today
    if scale == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if scale == "quarter":
        qm = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=qm, day=1)
        return start, start + timedelta(days=91)
    start = today.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return start, end


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


def _gantt_bar_caption(s: date, e: date, width_pct: float) -> str:
    if width_pct < 7:
        return ""
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

    def _ref(tid: int) -> dict:
        return {"id": tid, "title": title_by_id[tid]}

    for link in links:
        pair = _gantt_link_pair(link)
        if not pair:
            continue
        pred_id, succ_id, kind = pair
        if pred_id not in title_by_id or succ_id not in title_by_id:
            continue
        if kind == "blocks":
            waits_for[succ_id].append(_ref(pred_id))
            blocks[pred_id].append(_ref(succ_id))
        else:
            related_with[pred_id].append(_ref(succ_id))
            related_with[succ_id].append(_ref(pred_id))
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
    for b in bars:
        b["display_no"] = b["row"] + 1
        b["waits_for"] = [{**w, "no": no_by_id.get(w["id"])} for w in b.get("waits_for", [])]
        b["blocks"] = [{**x, "no": no_by_id.get(x["id"])} for x in b.get("blocks", [])]


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
    width_pct = max(0.8, ((end_f - start_f) / n) * 100)
    min_col = 100.0 / n
    width_pct = max(width_pct, min_col * (0.9 if scale == "day" else 0.45))
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
            in_r, left, w = _bar_geometry(st.deadline, st.deadline, span_start, span_end, scale, n_cols)
            if not in_r:
                continue
            pname = st.project.name if st.project else ""
            cap = _gantt_short_title(st.title, 28)
            out.append(
                {
                    "title": st.title,
                    "short_title": cap,
                    "project": pname,
                    "date_label": st.deadline.strftime("%d.%m.%Y"),
                    "left_pct": left,
                    "width_pct": max(w, 100 / n_cols),
                    "center_pct": min(99.0, left + max(w, 100 / n_cols) / 2),
                }
            )
    out.sort(key=lambda m: m["left_pct"])
    return out[:20]


def _gantt_milestone_groups(milestones: list[dict], *, min_gap_pct: float = 5.0) -> list[dict]:
    """Склеивает вехи с близкими позициями на шкале — подписи столбиком, без наложения."""
    if not milestones:
        return []
    ordered = sorted(milestones, key=lambda m: (m["center_pct"], m["date_label"], m["title"]))
    groups: list[dict] = []
    for m in ordered:
        if not groups or abs(m["center_pct"] - groups[-1]["center_pct"]) > min_gap_pct:
            groups.append({"center_pct": m["center_pct"], "milestones": [m]})
        else:
            groups[-1]["milestones"].append(m)
    return groups


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
    for idx, (t, s, e) in enumerate(dated):
        in_range, left_pct, width_pct = _bar_geometry(s, e, span_start, span_end, scale, n_cols)
        sla = gantt_sla_breach(t, t.project)
        critical = sla or bool(t.is_critical_path)
        bars.append(
            {
                "task": t,
                "row": row_offset + idx,
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
) -> dict:
    """Данные для диаграммы Gantt — стратегическое планирование (ТЗ 2.1)."""
    today = date.today()
    span_start, span_end = _gantt_span_for_scale(scale, today)
    columns = _gantt_columns(span_start, span_end, scale)
    n_cols = max(1, len(columns))
    dated = _gantt_collect_dated(tasks)
    task_list = [t for t, _, _ in dated]
    links = _gantt_links(task_list)
    waits_for, blocks, related_with = _gantt_task_relations(task_list, links)

    groups: list[dict] = []
    if group_by == "project" and not project_filter:
        by_pid: dict[int, list] = {}
        for item in dated:
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
            chunk = by_pid[pid]
            proj = chunk[0][0].project
            bars = _gantt_build_bars(
                chunk, span_start, span_end, scale, n_cols,
                waits_for, blocks, related_with, user, row_off,
            )
            row_off += len(bars)
            groups.append(
                {
                    "project_id": pid or None,
                    "title": proj.name if proj else "Без проекта",
                    "deadline_label": proj.deadline.strftime("%d.%m.%Y") if proj and proj.deadline else "",
                    "bars": bars,
                }
            )
    else:
        bars = _gantt_build_bars(
            dated, span_start, span_end, scale, n_cols,
            waits_for, blocks, related_with, user, 0,
        )
        groups.append({"project_id": project_filter, "title": "Задачи", "deadline_label": "", "bars": bars})

    gantt_bars = [b for g in groups for b in g["bars"]]
    _gantt_apply_row_numbers(gantt_bars)
    if scale == "day":
        span_label = span_start.strftime("%d.%m.%Y")
    else:
        span_label = f"{span_start.strftime('%d.%m.%Y')} — {span_end.strftime('%d.%m.%Y')}"

    link_edges = _gantt_link_edges(gantt_bars, links)
    gantt_milestones = _gantt_milestones(task_list, span_start, span_end, scale, n_cols)
    gantt_milestone_groups = _gantt_milestone_groups(gantt_milestones)
    milestone_stack_max = max((len(g["milestones"]) for g in gantt_milestone_groups), default=1)

    return {
        "gantt_bars": gantt_bars,
        "gantt_groups": groups,
        "gantt_columns": columns,
        "gantt_milestones": gantt_milestones,
        "gantt_milestone_groups": gantt_milestone_groups,
        "gantt_milestone_lane_min_h": 36 + milestone_stack_max * 24,
        "gantt_fs_links": [
            {"from_id": e["from_task_id"], "to_id": e["to_task_id"]}
            for e in link_edges
            if e.get("kind") == "blocks"
        ],
        "gantt_span_label": span_label,
        "gantt_span_start": span_start.isoformat(),
        "gantt_span_end": span_end.isoformat(),
        "gantt_today": today,
        "gantt_links": links,
        "gantt_link_edges": link_edges,
        "project_link_labels": PROJECT_LINK_LABELS,
        "gantt_scale_label": {
            "day": "Один день",
            "week": "7 дней (пн–вс)",
            "month": "Календарный месяц",
            "quarter": "Квартал (по месяцам)",
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
