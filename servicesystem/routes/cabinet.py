from sqlalchemy import func

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from servicesystem.decorators import contract_access_required, customer_directory_self_required, write_access_required
from servicesystem.extensions import db
from servicesystem.models import (
    ContractContentAccess,
    NewsPost,
    Plugin,
    PluginVersion,
    Tutorial,
    VideoTutorial,
)
from servicesystem.services.audit import log_audit
from servicesystem.services.storage import get_storage

bp = Blueprint("cabinet", __name__, url_prefix="/cabinet")


def _allowed_content_ids(contract_id, content_type):
    rows = ContractContentAccess.query.filter_by(
        contract_id=contract_id, content_type=content_type
    ).all()
    return {r.content_id for r in rows}


@bp.route("/")
@login_required
@contract_access_required
def dashboard():
    from servicesystem.models import Ticket

    tickets_q = Ticket.query
    if current_user.is_customer:
        tickets_q = tickets_q.filter_by(author_id=current_user.id)
    recent = tickets_q.order_by(Ticket.created_at.desc()).limit(5).all()
    contract = current_user.contract
    stats = {
        "open": tickets_q.filter(Ticket.status.in_(["new", "in_progress", "on_review", "ready"])).count(),
        "resolved": tickets_q.filter_by(status="resolved").count(),
    }
    recent_news = (
        NewsPost.query.filter_by(is_published=True)
        .order_by(func.coalesce(NewsPost.published_at, NewsPost.created_at).desc())
        .limit(3)
        .all()
    )
    return render_template(
        "cabinet/dashboard.html",
        recent_tickets=recent,
        recent_news=recent_news,
        contract=contract,
        stats=stats,
    )


@bp.route("/contract")
@login_required
@contract_access_required
def contract():
    contract = current_user.contract
    if not contract:
        abort(404)
    return render_template("cabinet/contract.html", contract=contract)


@bp.route("/plugins")
@login_required
@contract_access_required
def plugins():
    if current_user.is_customer and current_user.contract.is_readonly:
        flash("Скачивание плагинов недоступно — договор приостановлен.", "warning")
    allowed = None
    if current_user.is_customer and current_user.contract_id:
        allowed = _allowed_content_ids(current_user.contract_id, "plugin")
    q = Plugin.query.filter_by(is_active=True)
    items = q.all()
    if allowed is not None:
        items = [p for p in items if p.id in allowed]
    can_download = not (
        current_user.is_customer
        and current_user.contract
        and current_user.contract.is_readonly
    )
    return render_template("cabinet/plugins.html", plugins=items, can_download=can_download)


@bp.route("/plugins/<int:pid>/download")
@login_required
@contract_access_required
@write_access_required
def plugin_download(pid):
    plugin = db.session.get(Plugin, pid) or abort(404)
    if current_user.is_customer:
        allowed = _allowed_content_ids(current_user.contract_id, "plugin")
        if pid not in allowed:
            abort(403)
    version = PluginVersion.query.filter_by(plugin_id=pid, is_current=True).first()
    if not version:
        abort(404)
    storage = get_storage()
    rel = f"plugins/{version.stored_name}"
    if not storage.exists(rel):
        flash("Файл не найден на сервере.", "danger")
        return redirect(url_for("cabinet.plugins"))
    log_audit(current_user.id, "download", "plugin", pid, f"version={version.version}")
    db.session.commit()
    return send_file(storage.read_path(rel), as_attachment=True, download_name=version.original_name)


@bp.route("/tutorials")
@login_required
@contract_access_required
def tutorials():
    allowed = None
    if current_user.is_customer and current_user.contract_id:
        allowed = _allowed_content_ids(current_user.contract_id, "tutorial")
    q = Tutorial.query.filter_by(is_published=True).order_by(Tutorial.title)
    items = q.all()
    if allowed is not None:
        items = [t for t in items if t.id in allowed]
    search = request.args.get("q", "").strip()
    if search:
        q_lower = search.lower()
        items = [
            t for t in items
            if q_lower in t.title.lower()
            or q_lower in (t.content_md or "").lower()
            or q_lower in (t.tags or "").lower()
            or q_lower in (t.category or "").lower()
        ]
    ctx = dict(tutorials=items, search=search)
    if request.args.get("partial") == "1":
        return render_template("cabinet/tutorials_rows.html", **ctx)
    return render_template("cabinet/tutorials.html", **ctx)


def _tutorial_access_or_abort(t):
    if current_user.is_customer:
        allowed = _allowed_content_ids(current_user.contract_id, "tutorial")
        if t.id not in allowed:
            abort(403)


@bp.route("/tutorials/<slug>")
@bp.route("/tutorials/<slug>/<lesson_slug>")
@login_required
@contract_access_required
def tutorial_detail(slug, lesson_slug=None):
    from servicesystem.models import TutorialSection
    from servicesystem.services.cms_html import render_cms_markdown
    from servicesystem.services.tutorial_structure import find_lesson_in_tutorial

    t = Tutorial.query.filter_by(slug=slug, is_published=True).first_or_404()
    _tutorial_access_or_abort(t)

    sections = (
        TutorialSection.query.filter_by(tutorial_id=t.id)
        .order_by(TutorialSection.sort_order, TutorialSection.id)
        .all()
    )
    has_structure = bool(sections)
    current_lesson = None
    prev_lesson = None
    next_lesson = None
    content_html = ""
    section_nav = []

    if has_structure:
        from servicesystem.models import TutorialLesson

        lessons = t.ordered_lessons()

        def _section_nav_entry(si, sec, current_id=None):
            les_list = (
                TutorialLesson.query.filter_by(section_id=sec.id)
                .order_by(TutorialLesson.sort_order, TutorialLesson.id)
                .all()
            )
            return {
                "num": si,
                "title": sec.title,
                "lessons": [
                    {
                        "num": f"{si}.{li}",
                        "lesson": les,
                        "active": current_id is not None and les.id == current_id,
                    }
                    for li, les in enumerate(les_list, start=1)
                ],
            }

        if not lessons:
            if lesson_slug:
                abort(404)
            content_html = render_cms_markdown(t.content_md or "")
            for si, sec in enumerate(sections, start=1):
                section_nav.append(_section_nav_entry(si, sec))
        else:
            if lesson_slug:
                current_lesson = find_lesson_in_tutorial(t, lesson_slug)
                if not current_lesson:
                    abort(404)
            else:
                current_lesson = lessons[0]
                return redirect(
                    url_for(
                        "cabinet.tutorial_detail",
                        slug=t.slug,
                        lesson_slug=current_lesson.slug,
                    )
                )
            idx = next((i for i, L in enumerate(lessons) if L.id == current_lesson.id), 0)
            prev_lesson = lessons[idx - 1] if idx > 0 else None
            next_lesson = lessons[idx + 1] if idx + 1 < len(lessons) else None
            content_html = render_cms_markdown(current_lesson.content_md or "")
            cur_id = current_lesson.id
            for si, sec in enumerate(sections, start=1):
                section_nav.append(_section_nav_entry(si, sec, cur_id))
    else:
        content_html = render_cms_markdown(t.content_md or "")

    log_audit(current_user.id, "view", "tutorial", t.id)
    db.session.commit()
    return render_template(
        "cabinet/tutorial_detail.html",
        tutorial=t,
        content_html=content_html,
        has_structure=has_structure,
        section_nav=section_nav,
        current_lesson=current_lesson,
        prev_lesson=prev_lesson,
        next_lesson=next_lesson,
    )


@bp.route("/news")
@login_required
@contract_access_required
def news_list():
    items = (
        NewsPost.query.filter_by(is_published=True)
        .order_by(func.coalesce(NewsPost.published_at, NewsPost.created_at).desc())
        .all()
    )
    return render_template("cabinet/news.html", news_items=items)


@bp.route("/news/<slug>")
@login_required
@contract_access_required
def news_detail(slug):
    from servicesystem.services.cms_html import render_cms_markdown

    item = NewsPost.query.filter_by(slug=slug, is_published=True).first_or_404()
    html = render_cms_markdown(item.content_md or "")
    log_audit(current_user.id, "view", "news", item.id)
    db.session.commit()
    return render_template("cabinet/news_detail.html", item=item, content_html=html)


@bp.route("/directory", defaults={"path": ""})
@bp.route("/directory/<path:path>")
@login_required
def directory_blocked(path):
    """Справочник заказчиков — только внутренний контур Исполнителя (ТЗ)."""
    abort(404)


@bp.route("/my-contact", methods=["GET", "POST"])
@login_required
@customer_directory_self_required
@write_access_required
def my_contact():
    from servicesystem.services.directory_sync import contact_for_user, create_contact_from_user, sync_user_to_contact

    contact = contact_for_user(current_user)
    if request.method == "POST":
        current_user.full_name = request.form.get("full_name", "").strip()
        current_user.position = request.form.get("position", "").strip()
        current_user.phone = request.form.get("phone_mobile", "").strip()
        current_user.phone_work = (request.form.get("phone_work") or "").strip() or None
        current_user.phone_extension = (request.form.get("phone_extension") or "").strip() or None
        if not current_user.phone:
            flash("Укажите мобильный телефон.", "danger")
            return redirect(url_for("cabinet.my_contact"))
        email = request.form.get("email", "").strip().lower()
        if email and "@" in email:
            current_user.email = email
        if contact:
            sync_user_to_contact(current_user)
        else:
            create_contact_from_user(current_user, author_id=current_user.id)
        db.session.commit()
        flash("Контактные данные обновлены.", "success")
        return redirect(url_for("cabinet.my_contact"))
    if not contact:
        create_contact_from_user(current_user, author_id=current_user.id)
        db.session.commit()
        contact = contact_for_user(current_user)
    return render_template("cabinet/my_contact.html", contact=contact)


@bp.route("/videos")
@login_required
@contract_access_required
def videos():
    allowed = None
    if current_user.is_customer and current_user.contract_id:
        allowed = _allowed_content_ids(current_user.contract_id, "video")
    items = VideoTutorial.query.filter_by(is_published=True).order_by(VideoTutorial.title).all()
    if allowed is not None:
        items = [v for v in items if v.id in allowed]
    return render_template("cabinet/videos.html", videos=items)


@bp.route("/videos/<slug>")
@login_required
@contract_access_required
def video_detail(slug):
    v = VideoTutorial.query.filter_by(slug=slug, is_published=True).first_or_404()
    if current_user.is_customer:
        allowed = _allowed_content_ids(current_user.contract_id, "video")
        if v.id not in allowed:
            abort(403)
    chapters = v.chapters.all()
    log_audit(current_user.id, "view", "video", v.id)
    db.session.commit()
    is_local_stream = bool(v.video_file) or (v.video_url or "").startswith("/cabinet/media/")
    return render_template(
        "cabinet/video_detail.html",
        video=v,
        chapters=chapters,
        is_local_stream=is_local_stream,
    )


@bp.route("/media/videos/<path:filename>")
@login_required
@contract_access_required
def stream_video(filename):
    """Stream uploaded video without download (TZ 3.2.2)."""
    storage = get_storage()
    rel = f"videos/{filename}"
    if not storage.exists(rel):
        abort(404)
    response = send_file(storage.read_path(rel), mimetype="video/mp4", as_attachment=False)
    response.headers["Content-Disposition"] = "inline"
    response.headers["Cache-Control"] = "no-store"
    return response


def _curator_projects():
    from datetime import date

    from servicesystem.project_management.models import Project

    today = date.today()
    return (
        Project.query.filter_by(customer_curator_id=current_user.id, is_active=True)
        .filter(
            db.or_(
                Project.customer_curator_active_until.is_(None),
                Project.customer_curator_active_until >= today,
            )
        )
        .order_by(Project.deadline.nulls_last(), Project.name)
        .all()
    )


def _curator_stage_or_403(stage_id: int):
    from servicesystem.project_management.models import ProjectStage

    stage = db.session.get(ProjectStage, stage_id) or abort(404)
    proj = stage.project
    if not proj or proj.customer_curator_id != current_user.id:
        abort(403)
    return stage


def _stage_remark_priority(acceptance_status: str) -> int:
    """ТЗ: «Принято с замечаниями» → Низший (1); «На доработку» → Самый высший (4)."""
    return 1 if acceptance_status == "accepted_remarks" else 4


def _contract_for_stage_remark(stage):
    """Договор для SLA заявки: сначала договор проекта, не личный договор куратора."""
    project = stage.project if stage else None
    if project and project.contract_id:
        return project.contract
    return current_user.contract


def _create_stage_remark_ticket(stage, subject: str, description: str, priority: int = 1):
    """Тикет-замечание по этапу. Категории объекта/инцидента скрыты в UI — подставляются автоматически."""
    from servicesystem.models import IncidentCategory, ObjectCategory, Ticket, TicketAttachment
    from servicesystem.routes.tickets import _next_ticket_number
    from servicesystem.services.notify import notify_ticket_created
    from servicesystem.services.routing import resolve_auditor, resolve_default_executor
    from servicesystem.services.sla import compute_deadlines
    from servicesystem.services.ticket_workflow import on_ticket_created
    from servicesystem.project_management.services import (
        create_stage_remark_project_task,
        on_ticket_created_hook,
    )
    from servicesystem.services.audit import log_ticket_history

    if not stage.project:
        raise ValueError("no_project")
    contract = _contract_for_stage_remark(stage)
    if not contract:
        raise ValueError("no_contract")
    obj = ObjectCategory.query.filter_by(is_active=True).order_by(ObjectCategory.sort_order).first()
    if not obj:
        raise ValueError("no_category")
    inc = (
        IncidentCategory.query.filter_by(object_category_id=obj.id, is_active=True)
        .order_by(IncidentCategory.sort_order)
        .first()
    )
    if not inc:
        raise ValueError("no_incident")
    # ГИП проекта предпочтительнее маршрутизации по категории
    auditor = stage.project.curator_auditor if stage.project else None
    if not auditor:
        auditor = resolve_auditor(obj.id)
    default_exec = resolve_default_executor(obj.id)
    reaction, resolution = compute_deadlines(priority)
    ticket = Ticket(
        number=_next_ticket_number(),
        contract_id=contract.id,
        author_id=current_user.id,
        auditor_id=auditor.id if auditor else None,
        executor_id=default_exec.id if default_exec else None,
        object_category_id=obj.id,
        incident_category_id=inc.id,
        priority=priority,
        subject=subject[:120],
        description_md=description,
        status="new",
        reaction_deadline=reaction,
        resolution_deadline=resolution,
    )
    db.session.add(ticket)
    db.session.flush()
    on_ticket_created(ticket)
    create_stage_remark_project_task(stage, ticket)
    on_ticket_created_hook(ticket)
    attachment_ids = (request.form.get("attachment_ids") or "").strip()
    if attachment_ids:
        for aid in attachment_ids.split(","):
            aid = aid.strip()
            if not aid:
                continue
            att = db.session.get(TicketAttachment, int(aid))
            if att and att.ticket_id is None:
                att.ticket_id = ticket.id
    log_ticket_history(
        ticket.id,
        current_user.id,
        "created",
        details=f"stage_remark stage_id={stage.id}; project_id={stage.project_id}; priority={priority}",
    )
    log_audit(current_user.id, "ticket_create", "ticket", ticket.id, f"stage={stage.id}")
    notify_ticket_created(ticket, current_user, auditor)
    return ticket


@bp.route("/projects")
@login_required
@contract_access_required
def customer_projects():
    """ЛК куратора-заказчика: проекты и приёмка этапов."""
    if not current_user.is_customer_curator:
        abort(403)
    from servicesystem.project_management.models import ProjectStage
    from servicesystem.project_management.services import stage_working_days_left

    projects = _curator_projects()
    stages_by_project = {}
    timers = {}
    stage_files = {}
    for p in projects:
        stages = p.stages.order_by(ProjectStage.sort_order, ProjectStage.id).all()
        stages_by_project[p.id] = stages
        for s in stages:
            timers[s.id] = stage_working_days_left(s)
            atts = list(s.attachments)
            reports = [a for a in atts if (getattr(a, "kind", None) or "report") != "act"]
            acts = [a for a in atts if getattr(a, "kind", None) == "act"]
            stage_files[s.id] = {"reports": reports, "acts": acts}
    return render_template(
        "cabinet/customer_projects.html",
        projects=projects,
        stages_by_project=stages_by_project,
        stage_timers=timers,
        stage_files=stage_files,
    )


@bp.route("/projects/stages/<int:sid>/accept", methods=["POST"])
@login_required
@contract_access_required
@write_access_required
def curator_stage_accept(sid):
    if not current_user.is_customer_curator:
        abort(403)
    from servicesystem.project_management.services import (
        notify_auditor_stage_acceptance,
        set_stage_acceptance,
    )

    stage = _curator_stage_or_403(sid)
    if not stage.released_at:
        flash("Этап ещё не выпущен ГИП — приёмка недоступна.", "warning")
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")
    status = (request.form.get("status") or "").strip()
    try:
        set_stage_acceptance(stage, status, current_user)
    except ValueError:
        flash("Некорректный статус приёмки.", "danger")
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")
    db.session.commit()
    notify_auditor_stage_acceptance(stage, stage.acceptance_label, current_user.full_name)
    flash(f"Этап «{stage.title}»: {stage.acceptance_label}.", "success")
    return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")


@bp.route("/projects/stages/<int:sid>/act", methods=["POST"])
@login_required
@contract_access_required
@write_access_required
def curator_stage_act_upload(sid):
    if not current_user.is_customer_curator:
        abort(403)
    from servicesystem.project_management.services import save_stage_attachment

    stage = _curator_stage_or_403(sid)
    if stage.acceptance_status not in ("accepted", "accepted_remarks"):
        flash("Скан акта доступен после статусов «Принято» / «Принято с замечаниями».", "warning")
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")
    f = request.files.get("act_file")
    if not f or not f.filename:
        flash("Выберите файл акта (PDF, JPG, PNG).", "warning")
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")
    ext = (f.filename.rsplit(".", 1)[-1] or "").lower()
    if ext not in ("pdf", "jpg", "jpeg", "png"):
        flash("Допустимы только PDF, JPG, PNG.", "danger")
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")
    try:
        att = save_stage_attachment(stage, f, current_user.id, kind="act")
        db.session.add(att)
        db.session.commit()
    except ValueError:
        flash("Файл слишком большой.", "danger")
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")
    flash("Акт выполненных работ загружен.", "success")
    return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")


@bp.route("/projects/stages/<int:sid>/remark", methods=["GET", "POST"])
@login_required
@contract_access_required
@write_access_required
def curator_stage_remark(sid):
    """Замечание по этапу → полная форма заявки (ТЗ: категории скрыты, пресет критичности)."""
    if not current_user.is_customer_curator:
        abort(403)
    stage = _curator_stage_or_403(sid)
    if stage.acceptance_status not in ("accepted_remarks", "rework"):
        flash("Сначала выберите статус «Принято с замечаниями» или «На доработку».", "warning")
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")

    project = stage.project
    contract = _contract_for_stage_remark(stage)
    if not contract:
        flash(
            "Нет договора для оформления заявки: привяжите договор к проекту или к учётной записи куратора.",
            "danger",
        )
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")

    default_priority = _stage_remark_priority(stage.acceptance_status)
    pref_subject = f"Замечание по этапу «{stage.title}»"
    pref_description = (
        f"**Проект:** {stage.project.name}\n"
        f"**Этап:** {stage.title}\n"
        f"**Статус приёмки:** {stage.acceptance_label}\n\n"
    )

    if request.method == "POST":
        subject = (request.form.get("subject") or "").strip()[:120]
        description = (request.form.get("description") or "").strip()
        try:
            priority = int(request.form.get("priority") or default_priority)
        except (TypeError, ValueError):
            priority = default_priority
        if priority not in (1, 2, 3, 4):
            priority = default_priority
        # Для статуса 2/3 по ТЗ фиксируем пресет (куратор может сменить вручную на форме — оставляем выбор)
        if not subject or not description:
            flash("Заполните тему и описание замечания.", "danger")
            return render_template(
                "cabinet/stage_remark_ticket.html",
                stage=stage,
                project=project,
                contract=contract,
                default_priority=priority,
                pref_subject=subject or pref_subject,
                pref_description=description or pref_description,
            )
        try:
            ticket = _create_stage_remark_ticket(stage, subject, description, priority=priority)
            db.session.commit()
        except ValueError as e:
            db.session.rollback()
            flash(f"Не удалось создать тикет ({e}).", "danger")
            return render_template(
                "cabinet/stage_remark_ticket.html",
                stage=stage,
                project=project,
                contract=contract,
                default_priority=priority,
                pref_subject=subject,
                pref_description=description,
            )
        flash(f"Замечание оформлено заявкой №{ticket.number}.", "success")
        return redirect(url_for("tickets.detail", tid=ticket.id))

    return render_template(
        "cabinet/stage_remark_ticket.html",
        stage=stage,
        project=project,
        contract=contract,
        default_priority=default_priority,
        pref_subject=pref_subject,
        pref_description=pref_description,
    )


@bp.route("/projects/stages/<int:sid>/files/<int:aid>")
@login_required
@contract_access_required
def curator_stage_file(sid, aid):
    """Скачивание отчётных материалов / акта этапа куратором."""
    from servicesystem.project_management.models import ProjectStageAttachment

    att = db.session.get(ProjectStageAttachment, aid) or abort(404)
    if att.stage_id != sid:
        abort(404)
    if current_user.is_customer_curator:
        _curator_stage_or_403(sid)
    elif not current_user.is_staff:
        abort(403)
    rel = f"project_stages/{att.stage_id}/{att.stored_name}"
    storage = get_storage()
    if not storage.exists(rel):
        abort(404)
    return send_file(
        storage.read_path(rel),
        as_attachment=True,
        download_name=att.original_name,
        mimetype=att.mime_type or "application/octet-stream",
    )
