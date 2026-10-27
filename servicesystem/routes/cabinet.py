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


@bp.route("/tutorials/<slug>")
@login_required
@contract_access_required
def tutorial_detail(slug):
    t = Tutorial.query.filter_by(slug=slug, is_published=True).first_or_404()
    if current_user.is_customer:
        allowed = _allowed_content_ids(current_user.contract_id, "tutorial")
        if t.id not in allowed:
            abort(403)
    from servicesystem.services.cms_html import render_cms_markdown
    html = render_cms_markdown(t.content_md or "")
    log_audit(current_user.id, "view", "tutorial", t.id)
    db.session.commit()
    return render_template("cabinet/tutorial_detail.html", tutorial=t, content_html=html)


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


def _create_stage_remark_ticket(stage, subject: str, description: str, priority: int = 1):
    """Тикет-замечание по этапу (низкая критичность по умолчанию)."""
    from servicesystem.models import IncidentCategory, ObjectCategory, Ticket
    from servicesystem.routes.tickets import _next_ticket_number
    from servicesystem.services.notify import notify_ticket_created
    from servicesystem.services.routing import resolve_auditor, resolve_default_executor
    from servicesystem.services.sla import compute_deadlines
    from servicesystem.services.ticket_workflow import on_ticket_created
    from servicesystem.project_management.services import on_ticket_created_hook
    from servicesystem.services.audit import log_ticket_history

    contract = current_user.contract or (stage.project.contract if stage.project else None)
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
    on_ticket_created_hook(ticket)
    log_ticket_history(
        ticket.id,
        current_user.id,
        "created",
        details=f"stage_remark stage_id={stage.id}; priority={priority}",
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


@bp.route("/projects/stages/<int:sid>/remark", methods=["POST"])
@login_required
@contract_access_required
@write_access_required
def curator_stage_remark(sid):
    """Замечание → тикет (низкая критичность для «принято с замечаниями»)."""
    if not current_user.is_customer_curator:
        abort(403)
    stage = _curator_stage_or_403(sid)
    if stage.acceptance_status not in ("accepted_remarks", "rework"):
        flash("Сначала выберите статус «Принято с замечаниями» или «На доработку».", "warning")
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")
    body = (request.form.get("remark") or "").strip()
    if not body:
        flash("Введите текст замечания.", "warning")
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")
    # 1 = низший для «с замечаниями»; для доработки — обычный (2)
    priority = 1 if stage.acceptance_status == "accepted_remarks" else 2
    subject = f"Замечание по этапу «{stage.title}»"
    desc = (
        f"**Проект:** {stage.project.name}\n"
        f"**Этап:** {stage.title}\n"
        f"**Статус приёмки:** {stage.acceptance_label}\n\n"
        f"{body}"
    )
    try:
        ticket = _create_stage_remark_ticket(stage, subject, desc, priority=priority)
        # Вложения к замечанию (ТЗ: «добавляет вложения»)
        import uuid as _uuid

        from servicesystem.models import TicketAttachment

        storage = get_storage()
        for f in request.files.getlist("remark_files"):
            if not f or not f.filename:
                continue
            stored = f"{_uuid.uuid4().hex}_{f.filename}"
            rel = f"tickets/{ticket.id}/{stored}"
            size = storage.save_file(rel, f)
            db.session.add(
                TicketAttachment(
                    ticket_id=ticket.id,
                    original_name=(f.filename or "file")[:512],
                    stored_name=f"{ticket.id}/{stored}",
                    mime_type=getattr(f, "mimetype", None),
                    size_bytes=size,
                )
            )
        db.session.commit()
    except ValueError as e:
        db.session.rollback()
        flash(f"Не удалось создать тикет ({e}).", "danger")
        return redirect(url_for("cabinet.customer_projects") + f"#project-{stage.project_id}")
    flash(f"Замечание оформлено заявкой №{ticket.number}.", "success")
    return redirect(url_for("tickets.detail", tid=ticket.id))


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
