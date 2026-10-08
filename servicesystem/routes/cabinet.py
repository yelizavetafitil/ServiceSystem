from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from servicesystem.decorators import contract_access_required, write_access_required
from servicesystem.extensions import db
from servicesystem.models import (
    ContractContentAccess,
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
    return render_template(
        "cabinet/dashboard.html",
        recent_tickets=recent,
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
    return render_template("cabinet/tutorials.html", tutorials=items, search=search)


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
