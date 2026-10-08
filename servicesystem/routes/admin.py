from datetime import datetime, timezone

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from servicesystem.decorators import admin_required, content_cms_required
from servicesystem.config import Config
from servicesystem.extensions import db
from servicesystem.models import (
    AuditLog,
    Contract,
    ContractContentAccess,
    IncidentCategory,
    ObjectCategory,
    ObjectCategoryRouting,
    Organization,
    Plugin,
    PluginVersion,
    Ticket,
    NewsPost,
    Tutorial,
    User,
    VideoChapter,
    VideoTutorial,
)
from servicesystem.services.audit import log_audit, unique_filename
from servicesystem.services.storage import get_storage

CMS_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
CMS_IMAGE_MAX_BYTES = 8 * 1024 * 1024

bp = Blueprint("admin", __name__)


@bp.route("/")
@login_required
@admin_required
def dashboard():
    stats = {
        "users": User.query.count(),
        "contracts": Contract.query.count(),
        "tickets_open": Ticket.query.filter(Ticket.status.in_(["new", "in_progress", "on_review", "ready"])).count(),
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
        master_key_expires_at=datetime.strptime(request.form["master_key_expires_at"], "%Y-%m-%d").date() if request.form.get("master_key_expires_at") else None,
        status=request.form.get("status", "active_warranty"),
        master_login=request.form["master_login"].strip(),
        document_url=request.form.get("document_url", "").strip() or None,
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
        old_end = contract.service_end_date
        old_status = contract.status
        contract.service_end_date = datetime.strptime(request.form["service_end_date"], "%Y-%m-%d").date() if request.form.get("service_end_date") else None
        contract.master_key_expires_at = datetime.strptime(request.form["master_key_expires_at"], "%Y-%m-%d").date() if request.form.get("master_key_expires_at") else None
        if request.form.get("sync_master_key") == "1" and contract.service_end_date:
            contract.master_key_expires_at = contract.service_end_date
        contract.status = request.form["status"]
        contract.notes = request.form.get("notes", "")
        contract.document_url = request.form.get("document_url", "").strip() or contract.document_url
        users_count = User.query.filter_by(contract_id=cid, role="customer", is_active=True).count()
        details = f"status={contract.status}"
        if contract.service_end_date != old_end:
            details += f"; service_end_date={old_end}->{contract.service_end_date}; users={users_count}"
        log_audit(current_user.id, "contract_update", "contract", cid, details)
        db.session.commit()
        if contract.service_end_date != old_end and users_count:
            flash(
                f"Договор обновлён. Доступ автоматически продлён для {users_count} "
                f"персональных учётных записей до {contract.service_end_date.strftime('%d.%m.%Y')}.",
                "success",
            )
        elif contract.status != old_status:
            flash(
                f"Статус договора изменён на «{Config.CONTRACT_STATUSES.get(contract.status, contract.status)}». "
                f"Затронуто учётных записей: {users_count}.",
                "success",
            )
        else:
            flash("Договор обновлён.", "success")
        return redirect(url_for("admin.contract_edit", cid=cid))
    plugins = Plugin.query.filter_by(is_active=True).all()
    tutorials = Tutorial.query.filter_by(is_published=True).all()
    videos = VideoTutorial.query.filter_by(is_published=True).all()
    access = {(a.content_type, a.content_id) for a in contract.content_access.all()}
    contract_users = User.query.filter_by(contract_id=cid, role="customer").order_by(User.full_name).all()
    org_contracts = Contract.query.filter_by(organization_id=contract.organization_id).order_by(Contract.number).all()
    return render_template(
        "admin/contract_edit.html",
        contract=contract,
        plugins=plugins,
        tutorials=tutorials,
        videos=videos,
        access=access,
        contract_users=contract_users,
        org_contracts=org_contracts,
    )


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


@bp.route("/contracts/<int:cid>/access/copy-org", methods=["POST"])
@login_required
@admin_required
def contract_access_copy_org(cid):
    """Применить видимость контента ко всем договорам организации (TZ 3.3.1)."""
    contract = db.session.get(Contract, cid) or abort(404)
    access_rows = list(contract.content_access.all())
    siblings = Contract.query.filter(
        Contract.organization_id == contract.organization_id,
        Contract.id != cid,
    ).all()
    for sibling in siblings:
        ContractContentAccess.query.filter_by(contract_id=sibling.id).delete()
        for row in access_rows:
            db.session.add(ContractContentAccess(
                contract_id=sibling.id,
                content_type=row.content_type,
                content_id=row.content_id,
            ))
    log_audit(
        current_user.id,
        "contract_access_copy_org",
        "organization",
        contract.organization_id,
        f"from_contract={contract.number}, targets={len(siblings)}",
    )
    db.session.commit()
    flash(f"Видимость контента скопирована на {len(siblings)} договор(ов) организации.", "success")
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


@bp.route("/users/<int:uid>", methods=["GET", "POST"])
@login_required
@admin_required
def user_edit(uid):
    user = db.session.get(User, uid) or abort(404)
    if request.method == "POST":
        user.full_name = request.form["full_name"].strip()
        user.position = request.form.get("position", "")
        user.role = request.form["role"]
        user.is_active = request.form.get("is_active") == "1"
        if request.form.get("password"):
            user.set_password(request.form["password"])
        db.session.commit()
        flash("Пользователь обновлён.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_edit.html", user=user)


@bp.route("/users/<int:uid>/audit")
@login_required
@admin_required
def user_audit(uid):
    """Журнал действий персонального аккаунта (TZ 3.1.4)."""
    user = db.session.get(User, uid) or abort(404)
    logs = (
        AuditLog.query.filter_by(user_id=uid)
        .order_by(AuditLog.created_at.desc())
        .limit(500)
        .all()
    )
    known_ids = {l.id for l in logs}
    legacy_register = (
        AuditLog.query.filter(
            AuditLog.user_id.is_(None),
            AuditLog.action == "register",
            AuditLog.details.contains(user.email),
        )
        .order_by(AuditLog.created_at.desc())
        .all()
    )
    for entry in legacy_register:
        if entry.id not in known_ids:
            logs.append(entry)
    logs.sort(key=lambda l: l.created_at or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    action_labels = {
        "login": "Вход в систему",
        "logout": "Выход",
        "register": "Персональная регистрация",
        "master_login": "Вход по мастер-ключу",
        "ticket_create": "Создание заявки",
        "download": "Скачивание материала",
        "view": "Просмотр материала",
        "contract_update": "Изменение договора",
    }
    return render_template(
        "admin/user_audit.html",
        user=user,
        logs=logs,
        action_labels=action_labels,
    )


@bp.route("/routing", methods=["GET", "POST"])
@login_required
@admin_required
def routing():
    objects = ObjectCategory.query.filter_by(is_active=True).order_by(ObjectCategory.sort_order).all()
    auditors = User.query.filter_by(role="auditor", is_active=True).all()
    executors = User.query.filter_by(role="executor", is_active=True).all()
    if request.method == "POST":
        for obj in objects:
            aud_id = request.form.get(f"auditor_{obj.id}")
            exec_id = request.form.get(f"executor_{obj.id}")
            if not aud_id:
                continue
            route = ObjectCategoryRouting.query.filter_by(object_category_id=obj.id).first()
            if not route:
                route = ObjectCategoryRouting(object_category_id=obj.id)
                db.session.add(route)
            route.auditor_id = int(aud_id)
            route.default_executor_id = int(exec_id) if exec_id else None
        db.session.commit()
        flash("Маршрутизация тикетов обновлена.", "success")
        return redirect(url_for("admin.routing"))
    routes = {r.object_category_id: r for r in ObjectCategoryRouting.query.all()}
    return render_template("admin/routing.html", objects=objects, auditors=auditors, executors=executors, routes=routes)


@bp.route("/categories/object/<int:oid>/edit", methods=["POST"])
@login_required
@admin_required
def object_category_edit(oid):
    obj = db.session.get(ObjectCategory, oid) or abort(404)
    obj.name = request.form["name"].strip()
    obj.is_active = request.form.get("is_active") == "1"
    db.session.commit()
    return redirect(url_for("admin.categories"))


@bp.route("/categories/incident/<int:iid>/edit", methods=["POST"])
@login_required
@admin_required
def incident_category_edit(iid):
    inc = db.session.get(IncidentCategory, iid) or abort(404)
    inc.name = request.form["name"].strip()
    inc.is_active = request.form.get("is_active") == "1"
    db.session.commit()
    return redirect(url_for("admin.categories"))


@bp.route("/plugins/<int:pid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def plugin_edit(pid):
    plugin = db.session.get(Plugin, pid) or abort(404)
    if request.method == "POST":
        plugin.name = request.form["name"]
        plugin.description = request.form.get("description", "")
        plugin.min_core_version = request.form.get("min_core_version")
        plugin.max_core_version = request.form.get("max_core_version")
        plugin.is_active = request.form.get("is_active") == "1"
        db.session.commit()
        flash("Плагин обновлён.", "success")
        return redirect(url_for("admin.plugin_edit", pid=pid))
    versions = plugin.versions.all()
    return render_template("admin/plugin_edit.html", plugin=plugin, versions=versions)


@bp.route("/tutorials/<int:tid>/edit", methods=["GET", "POST"])
@login_required
@content_cms_required
def tutorial_edit(tid):
    t = db.session.get(Tutorial, tid) or abort(404)
    if request.method == "POST":
        t.title = request.form["title"]
        t.slug = request.form.get("slug") or t.slug
        t.category = request.form.get("category")
        t.tags = request.form.get("tags")
        t.content_md = request.form["content_md"]
        t.is_published = request.form.get("is_published") == "1"
        db.session.commit()
        flash("Туториал обновлён.", "success")
        return redirect(url_for("admin.tutorials"))
    return render_template("admin/tutorial_edit.html", tutorial=t)


@bp.route("/videos/<int:vid>/edit", methods=["GET", "POST"])
@login_required
@content_cms_required
def video_edit(vid):
    v = db.session.get(VideoTutorial, vid) or abort(404)
    if request.method == "POST":
        v.title = request.form["title"]
        v.slug = request.form.get("slug") or v.slug
        v.category = request.form.get("category")
        v.description = request.form.get("description")
        v.video_url = request.form.get("video_url") or v.video_url
        v.duration_sec = int(request.form["duration_sec"]) if request.form.get("duration_sec") else v.duration_sec
        v.is_published = request.form.get("is_published") == "1"
        f = request.files.get("video_file")
        if f and f.filename:
            stored = unique_filename(f.filename)
            storage = get_storage()
            storage.ensure_dir("videos")
            size = storage.save_file(f"videos/{stored}", f)
            v.video_file = stored
            v.video_url = url_for("cabinet.stream_video", filename=stored, _external=False)
        VideoChapter.query.filter_by(video_id=v.id).delete()
        for i, line in enumerate(request.form.get("chapters", "").strip().split("\n")):
            if "|" in line:
                start, title = line.split("|", 1)
                desc = ""
                if ";" in title:
                    title, desc = title.split(";", 1)
                db.session.add(VideoChapter(
                    video_id=v.id, title=title.strip(), start_sec=int(start.strip()),
                    description=desc.strip() or None, sort_order=i,
                ))
        db.session.commit()
        flash("Видео обновлено.", "success")
        return redirect(url_for("admin.videos"))
    chapters = "\n".join(f"{c.start_sec}|{c.title}" + (f";{c.description}" if c.description else "") for c in v.chapters.all())
    return render_template("admin/video_edit.html", video=v, chapters=chapters)


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
    old_current = PluginVersion.query.filter_by(plugin_id=pid, is_current=True).first()
    if old_current and old_current.id != version.id:
        old_current.is_current = False
        old_current.is_archived = True
    PluginVersion.query.filter_by(plugin_id=pid, is_current=True).update({"is_current": False})
    version.is_current = True
    version.is_archived = False
    plugin.current_version = version.version
    log_audit(current_user.id, "plugin_rollback", "plugin", pid, f"version={version.version}")
    db.session.commit()
    flash(f"Откат к версии {version.version} выполнен.", "success")
    return redirect(url_for("admin.plugin_edit", pid=pid))


@bp.route("/plugins/<int:pid>/upload", methods=["POST"])
@login_required
@admin_required
def plugin_version_upload(pid):
    plugin = db.session.get(Plugin, pid) or abort(404)
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Выберите файл дистрибутива.", "danger")
        return redirect(url_for("admin.plugin_edit", pid=pid))
    version = request.form.get("version", "").strip()
    changelog = request.form.get("changelog_md", "").strip()
    if not version or not changelog:
        flash("Укажите номер версии и текст «Что нового».", "danger")
        return redirect(url_for("admin.plugin_edit", pid=pid))
    stored = unique_filename(f.filename)
    storage = get_storage()
    storage.ensure_dir("plugins")
    size = storage.save_file(f"plugins/{stored}", f)
    PluginVersion.query.filter_by(plugin_id=pid, is_current=True).update({"is_current": False, "is_archived": True})
    pv = PluginVersion(
        plugin_id=pid,
        version=version,
        changelog_md=changelog,
        stored_name=stored,
        original_name=f.filename,
        size_bytes=size,
        is_current=True,
        is_archived=False,
    )
    plugin.current_version = version
    db.session.add(pv)
    log_audit(current_user.id, "plugin_version_upload", "plugin", pid, f"version={version}; file={f.filename}")
    db.session.commit()
    flash(f"Версия {version} загружена. Предыдущая перемещена в архив.", "success")
    return redirect(url_for("admin.plugin_edit", pid=pid))


@bp.route("/cms-images", methods=["POST"])
@login_required
@content_cms_required
def cms_image_upload():
    """Upload image for tutorial Markdown (file picker, not URL prompt)."""
    f = request.files.get("image")
    if not f or not f.filename:
        return jsonify({"error": "Выберите файл изображения"}), 400
    name = f.filename.lower().strip()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in CMS_IMAGE_EXTENSIONS:
        return jsonify({"error": "Допустимы: PNG, JPG, GIF, WEBP"}), 400
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size <= 0 or size > CMS_IMAGE_MAX_BYTES:
        return jsonify({"error": f"Размер файла до {CMS_IMAGE_MAX_BYTES // (1024 * 1024)} МБ"}), 400
    stored = unique_filename(f.filename)
    storage = get_storage()
    storage.ensure_dir("cms")
    storage.save_file(f"cms/{stored}", f)
    url = url_for("admin.cms_image_serve", filename=stored)
    return jsonify({"url": url, "filename": stored})


@bp.route("/cms-images/<path:filename>")
@login_required
def cms_image_serve(filename):
    """Serve CMS images to staff and customers with article access (any logged-in)."""
    if "/" in filename or ".." in filename:
        abort(404)
    storage = get_storage()
    rel = f"cms/{filename}"
    if not storage.exists(rel):
        abort(404)
    mime = "image/jpeg"
    lower = filename.lower()
    if lower.endswith(".png"):
        mime = "image/png"
    elif lower.endswith(".gif"):
        mime = "image/gif"
    elif lower.endswith(".webp"):
        mime = "image/webp"
    return send_file(storage.read_path(rel), mimetype=mime)


@bp.route("/news")
@login_required
@content_cms_required
def news():
    items = NewsPost.query.order_by(NewsPost.created_at.desc()).all()
    return render_template("admin/news.html", news_items=items)


@bp.route("/news/create", methods=["POST"])
@login_required
@content_cms_required
def news_create():
    slug = (request.form.get("slug") or request.form["title"]).lower().replace(" ", "-")[:120]
    published = request.form.get("is_published") == "1"
    now = datetime.now(timezone.utc)
    post = NewsPost(
        title=request.form["title"].strip(),
        slug=slug,
        summary=(request.form.get("summary") or "").strip() or None,
        content_md=request.form["content_md"],
        is_published=published,
        author_id=current_user.id,
        published_at=now if published else None,
    )
    db.session.add(post)
    db.session.commit()
    flash("Новость добавлена.", "success")
    return redirect(url_for("admin.news"))


@bp.route("/news/<int:nid>/edit", methods=["GET", "POST"])
@login_required
@content_cms_required
def news_edit(nid):
    post = db.session.get(NewsPost, nid) or abort(404)
    if request.method == "POST":
        post.title = request.form["title"].strip()
        post.slug = (request.form.get("slug") or post.slug).strip()
        post.summary = (request.form.get("summary") or "").strip() or None
        post.content_md = request.form["content_md"]
        was_published = post.is_published
        post.is_published = request.form.get("is_published") == "1"
        if post.is_published and not post.published_at:
            post.published_at = datetime.now(timezone.utc)
        elif not post.is_published and was_published:
            post.published_at = None
        db.session.commit()
        flash("Новость обновлена.", "success")
        return redirect(url_for("admin.news"))
    return render_template("admin/news_edit.html", item=post)


@bp.route("/tutorials")
@login_required
@content_cms_required
def tutorials():
    items = Tutorial.query.order_by(Tutorial.title).all()
    return render_template("admin/tutorials.html", tutorials=items)


@bp.route("/tutorials/create", methods=["POST"])
@login_required
@content_cms_required
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
@content_cms_required
def videos():
    items = VideoTutorial.query.order_by(VideoTutorial.title).all()
    return render_template("admin/videos.html", videos=items)


@bp.route("/videos/create", methods=["POST"])
@login_required
@content_cms_required
def video_create():
    video_url = request.form.get("video_url", "").strip()
    video_file = None
    f = request.files.get("video_file")
    if f and f.filename:
        stored = unique_filename(f.filename)
        storage = get_storage()
        storage.ensure_dir("videos")
        storage.save_file(f"videos/{stored}", f)
        video_file = stored
        video_url = url_for("cabinet.stream_video", filename=stored, _external=False)
    if not video_url:
        flash("Укажите URL видео или загрузите файл.", "danger")
        return redirect(url_for("admin.videos"))
    v = VideoTutorial(
        title=request.form["title"],
        slug=request.form["slug"],
        category=request.form.get("category"),
        description=request.form.get("description"),
        video_url=video_url,
        video_file=video_file,
        duration_sec=int(request.form["duration_sec"]) if request.form.get("duration_sec") else None,
    )
    db.session.add(v)
    db.session.flush()
    chapters_raw = request.form.get("chapters", "")
    for i, line in enumerate(chapters_raw.strip().split("\n")):
        if "|" in line:
            start, title = line.split("|", 1)
            desc = ""
            if ";" in title:
                title, desc = title.split(";", 1)
            db.session.add(VideoChapter(
                video_id=v.id, title=title.strip(), start_sec=int(start.strip()),
                description=desc.strip() or None, sort_order=i,
            ))
    db.session.commit()
    return redirect(url_for("admin.videos"))


@bp.route("/audit")
@login_required
@admin_required
def audit():
    q = AuditLog.query
    user_id = request.args.get("user_id", type=int)
    action = request.args.get("action", "").strip()
    if user_id:
        q = q.filter_by(user_id=user_id)
    if action:
        q = q.filter(AuditLog.action == action)
    logs = q.order_by(AuditLog.created_at.desc()).limit(500).all()
    users = User.query.order_by(User.full_name).all()
    actions = [r[0] for r in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
    return render_template("admin/audit.html", logs=logs, users=users, actions=actions, filter_user=user_id, filter_action=action)


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
