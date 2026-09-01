import os
from datetime import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from servicesystem.decorators import admin_required
from servicesystem.extensions import db
from servicesystem.models import (
    AuditLog,
    Contract,
    ContractContentAccess,
    IncidentCategory,
    ObjectCategory,
    Organization,
    Plugin,
    PluginVersion,
    Ticket,
    Tutorial,
    User,
    VideoChapter,
    VideoTutorial,
)
from servicesystem.services.audit import ensure_upload_dir, log_audit, unique_filename

bp = Blueprint("admin", __name__)


@bp.route("/")
@login_required
@admin_required
def dashboard():
    stats = {
        "users": User.query.count(),
        "contracts": Contract.query.count(),
        "tickets_open": Ticket.query.filter(Ticket.status.in_(["new", "in_progress", "on_review"])).count(),
        "plugins": Plugin.query.count(),
    }
    expiring = Contract.query.filter(
        Contract.service_end_date.isnot(None),
        Contract.status.in_(["active_warranty", "active_post_warranty"]),
    ).order_by(Contract.service_end_date).limit(10).all()
    expiring = [c for c in expiring if c.days_until_expiry is not None and c.days_until_expiry <= 60]
    return render_template("admin/dashboard.html", stats=stats, expiring=expiring)


@bp.route("/contracts")
@login_required
@admin_required
def contracts():
    items = Contract.query.join(Organization).order_by(Contract.number).all()
    orgs = Organization.query.order_by(Organization.name).all()
    return render_template("admin/contracts.html", contracts=items, orgs=orgs)


@bp.route("/contracts/create", methods=["POST"])
@login_required
@admin_required
def contract_create():
    c = Contract(
        organization_id=int(request.form["organization_id"]),
        number=request.form["number"].strip(),
        signed_at=datetime.strptime(request.form["signed_at"], "%Y-%m-%d").date() if request.form.get("signed_at") else None,
        service_end_date=datetime.strptime(request.form["service_end_date"], "%Y-%m-%d").date() if request.form.get("service_end_date") else None,
        status=request.form.get("status", "active_warranty"),
        master_login=request.form["master_login"].strip(),
    )
    c.set_master_password(request.form["master_password"])
    db.session.add(c)
    db.session.commit()
    flash("Договор создан.", "success")
    return redirect(url_for("admin.contracts"))


@bp.route("/contracts/<int:cid>", methods=["GET", "POST"])
@login_required
@admin_required
def contract_edit(cid):
    contract = db.session.get(Contract, cid) or abort(404)
    if request.method == "POST":
        contract.service_end_date = datetime.strptime(request.form["service_end_date"], "%Y-%m-%d").date() if request.form.get("service_end_date") else None
        contract.status = request.form["status"]
        contract.notes = request.form.get("notes", "")
        log_audit(current_user.id, "contract_update", "contract", cid, f"status={contract.status}")
        db.session.commit()
        flash("Договор обновлён.", "success")
        return redirect(url_for("admin.contracts"))
    plugins = Plugin.query.filter_by(is_active=True).all()
    tutorials = Tutorial.query.filter_by(is_published=True).all()
    videos = VideoTutorial.query.filter_by(is_published=True).all()
    access = {(a.content_type, a.content_id) for a in contract.content_access.all()}
    return render_template("admin/contract_edit.html", contract=contract, plugins=plugins, tutorials=tutorials, videos=videos, access=access)


@bp.route("/contracts/<int:cid>/access", methods=["POST"])
@login_required
@admin_required
def contract_access(cid):
    contract = db.session.get(Contract, cid) or abort(404)
    ContractContentAccess.query.filter_by(contract_id=cid).delete()
    for key in request.form:
        if key.startswith("access_"):
            _, ctype, cid_str = key.split("_", 2)
            db.session.add(ContractContentAccess(contract_id=cid, content_type=ctype, content_id=int(cid_str)))
    db.session.commit()
    flash("Доступ к контенту обновлён.", "success")
    return redirect(url_for("admin.contract_edit", cid=cid))


@bp.route("/users")
@login_required
@admin_required
def users():
    items = User.query.order_by(User.full_name).all()
    return render_template("admin/users.html", users=items)


@bp.route("/users/create", methods=["POST"])
@login_required
@admin_required
def user_create():
    u = User(
        email=request.form["email"].strip().lower(),
        full_name=request.form["full_name"].strip(),
        position=request.form.get("position", ""),
        role=request.form["role"],
    )
    u.set_password(request.form["password"])
    db.session.add(u)
    db.session.commit()
    flash("Пользователь создан.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/categories")
@login_required
@admin_required
def categories():
    objects = ObjectCategory.query.order_by(ObjectCategory.sort_order).all()
    return render_template("admin/categories.html", objects=objects)


@bp.route("/categories/object", methods=["POST"])
@login_required
@admin_required
def object_category_create():
    db.session.add(ObjectCategory(name=request.form["name"].strip()))
    db.session.commit()
    return redirect(url_for("admin.categories"))


@bp.route("/categories/incident", methods=["POST"])
@login_required
@admin_required
def incident_category_create():
    db.session.add(IncidentCategory(
        object_category_id=int(request.form["object_category_id"]),
        name=request.form["name"].strip(),
    ))
    db.session.commit()
    return redirect(url_for("admin.categories"))


@bp.route("/plugins")
@login_required
@admin_required
def plugins():
    items = Plugin.query.order_by(Plugin.name).all()
    return render_template("admin/plugins.html", plugins=items)


@bp.route("/plugins/create", methods=["POST"])
@login_required
@admin_required
def plugin_create():
    p = Plugin(
        name=request.form["name"],
        slug=request.form["slug"],
        min_core_version=request.form.get("min_core_version"),
        max_core_version=request.form.get("max_core_version"),
    )
    db.session.add(p)
    db.session.commit()
    return redirect(url_for("admin.plugins"))


@bp.route("/plugins/<int:pid>/rollback/<int:vid>", methods=["POST"])
@login_required
@admin_required
def plugin_version_rollback(pid, vid):
    plugin = db.session.get(Plugin, pid) or abort(404)
    version = db.session.get(PluginVersion, vid)
    if not version or version.plugin_id != pid:
        abort(404)
    PluginVersion.query.filter_by(plugin_id=pid, is_current=True).update({"is_current": False})
    version.is_current = True
    version.is_archived = False
    plugin.current_version = version.version
    db.session.commit()
    flash(f"Откат к версии {version.version} выполнен.", "success")
    return redirect(url_for("admin.plugins"))


@bp.route("/plugins/<int:pid>/upload", methods=["POST"])
@login_required
@admin_required
def plugin_version_upload(pid):
    plugin = db.session.get(Plugin, pid) or abort(404)
    f = request.files.get("file")
    version = request.form["version"]
    stored = unique_filename(f.filename)
    ensure_upload_dir(current_app.config["UPLOAD_FOLDER"], "plugins")
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "plugins", stored)
    f.save(path)
    PluginVersion.query.filter_by(plugin_id=pid, is_current=True).update({"is_current": False, "is_archived": True})
    pv = PluginVersion(
        plugin_id=pid,
        version=version,
        changelog_md=request.form.get("changelog_md", ""),
        stored_name=stored,
        original_name=f.filename,
        size_bytes=os.path.getsize(path),
        is_current=True,
    )
    plugin.current_version = version
    db.session.add(pv)
    db.session.commit()
    flash(f"Версия {version} загружена.", "success")
    return redirect(url_for("admin.plugins"))


@bp.route("/tutorials")
@login_required
@admin_required
def tutorials():
    items = Tutorial.query.order_by(Tutorial.title).all()
    return render_template("admin/tutorials.html", tutorials=items)


@bp.route("/tutorials/create", methods=["POST"])
@login_required
@admin_required
def tutorial_create():
    slug = request.form["slug"] or request.form["title"].lower().replace(" ", "-")[:120]
    t = Tutorial(
        title=request.form["title"],
        slug=slug,
        category=request.form.get("category"),
        tags=request.form.get("tags"),
        content_md=request.form["content_md"],
    )
    db.session.add(t)
    db.session.commit()
    return redirect(url_for("admin.tutorials"))


@bp.route("/videos")
@login_required
@admin_required
def videos():
    items = VideoTutorial.query.order_by(VideoTutorial.title).all()
    return render_template("admin/videos.html", videos=items)


@bp.route("/videos/create", methods=["POST"])
@login_required
@admin_required
def video_create():
    v = VideoTutorial(
        title=request.form["title"],
        slug=request.form["slug"],
        category=request.form.get("category"),
        description=request.form.get("description"),
        video_url=request.form["video_url"],
        duration_sec=int(request.form["duration_sec"]) if request.form.get("duration_sec") else None,
    )
    db.session.add(v)
    db.session.flush()
    chapters_raw = request.form.get("chapters", "")
    for i, line in enumerate(chapters_raw.strip().split("\n")):
        if "|" in line:
            start, title = line.split("|", 1)
            db.session.add(VideoChapter(video_id=v.id, title=title.strip(), start_sec=int(start.strip()), sort_order=i))
    db.session.commit()
    return redirect(url_for("admin.videos"))


@bp.route("/audit")
@login_required
@admin_required
def audit():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template("admin/audit.html", logs=logs)


@bp.route("/organizations/create", methods=["POST"])
@login_required
@admin_required
def org_create():
    db.session.add(Organization(
        name=request.form["name"],
        short_name=request.form.get("short_name"),
    ))
    db.session.commit()
    flash("Организация добавлена.", "success")
    return redirect(url_for("admin.contracts"))
