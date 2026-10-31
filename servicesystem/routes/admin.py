from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from servicesystem.decorators import admin_required, content_cms_required, staff_required
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
    PhoneDirectoryContact,
    PhoneDirectoryDepartment,
    Tutorial,
    TutorialLesson,
    TutorialSection,
    User,
    VideoChapter,
    VideoTutorial,
)
from servicesystem.services.audit import log_audit, unique_filename
from servicesystem.services.storage import get_storage
from servicesystem.services.directory import find_active_contact_by_mobile, staff_directory_query
from servicesystem.services.directory_import import parse_directory_csv
from servicesystem.services.directory_sync import log_directory_field_changes, snapshot_contact, sync_contact_to_user
from servicesystem.services.cms_html import normalize_cms_markdown_source
from servicesystem.services.phone_format import split_work_phone


def _form_cms_md(key: str = "content_md") -> str:
    return normalize_cms_markdown_source(request.form.get(key) or "")


def _save_uploaded_video(file_storage):
    """Сохранить MP4/видео в storage. Возвращает (имя файла, url потока) или None."""
    if not file_storage or not file_storage.filename:
        return None
    max_video = current_app.config.get("VIDEO_MAX_UPLOAD_MB", 1024) * 1024 * 1024
    file_storage.seek(0, 2)
    fsize = file_storage.tell()
    file_storage.seek(0)
    if fsize <= 0:
        raise ValueError("Файл видео пустой или не был передан (проверьте лимит прокси/nginx и размер).")
    if fsize > max_video:
        raise ValueError(
            f"Видео больше {current_app.config.get('VIDEO_MAX_UPLOAD_MB', 1024)} МБ."
        )
    stored = unique_filename(file_storage.filename)
    storage = get_storage()
    storage.ensure_dir("videos")
    try:
        storage.save_file(f"videos/{stored}", file_storage)
    except OSError as exc:
        raise ValueError(f"Не удалось сохранить видео на диск: {exc}") from exc
    stream_url = url_for("cabinet.stream_video", filename=stored, _external=False)
    return stored, stream_url


from servicesystem.services.vcard import (
    build_vcard,
    parse_vcf_text,
    repair_quoted_printable_text,
    safe_vcf_filename,
)

CMS_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
CMS_IMAGE_MAX_BYTES = 8 * 1024 * 1024

bp = Blueprint("admin", __name__)


def sync_contract_personal_access(contract: Contract) -> int:
    """Истёк мастер-ключ или договор закрыт → персональные УЗ «Отключён».

    При продлении мастер-ключа / срока обслуживания снова «Подключён».
    Возвращает число затронутых учёток.
    """
    q = User.query.filter(
        User.contract_id == contract.id,
        User.role.in_(("customer", "customer_curator")),
    )
    users = q.all()
    if not users:
        return 0
    want_active = not contract.is_access_disabled
    changed = 0
    for u in users:
        if u.is_active != want_active:
            u.is_active = want_active
            changed += 1
    return changed


def sync_expired_master_key_access() -> int:
    """Ленивая синхронизация: все договоры с истёкшим мастер-ключом / блоком."""
    total = 0
    for c in Contract.query.all():
        if c.is_access_disabled:
            total += sync_contract_personal_access(c)
        else:
            # Продлили ключ — вернуть доступ, если УЗ были отключены только из‑за срока
            total += sync_contract_personal_access(c)
    return total


@bp.after_request
def admin_html_no_cache(response):
    ct = (response.content_type or "").lower()
    if "text/html" in ct:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


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


def _organization_name_taken(name: str, exclude_id: int | None = None) -> bool:
    q = Organization.query.filter(Organization.name.ilike(name))
    if exclude_id is not None:
        q = q.filter(Organization.id != exclude_id)
    return q.first() is not None


def _organization_delete_blockers(org: Organization) -> list[str]:
    blockers: list[str] = []
    n_contracts = org.contracts.count()
    if n_contracts:
        blockers.append(f"договоров: {n_contracts}")
    n_contacts = PhoneDirectoryContact.query.filter_by(organization_id=org.id).count()
    if n_contacts:
        blockers.append(f"контактов в справочнике: {n_contacts}")
    n_depts = PhoneDirectoryDepartment.query.filter_by(organization_id=org.id).count()
    if n_depts:
        blockers.append(f"подразделений: {n_depts}")
    n_users = User.query.filter_by(organization_id=org.id).count()
    if n_users:
        blockers.append(f"пользователей: {n_users}")
    return blockers


@bp.route("/contracts")
@login_required
@admin_required
def contracts():
    if sync_expired_master_key_access():
        db.session.commit()
    items = Contract.query.join(Organization).order_by(Contract.number).all()
    orgs = Organization.query.order_by(Organization.name).all()
    org_blockers = {o.id: _organization_delete_blockers(o) for o in orgs}
    return render_template(
        "admin/contracts.html",
        contracts=items,
        orgs=orgs,
        org_blockers=org_blockers,
    )


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
        synced = sync_contract_personal_access(contract)
        users_count = User.query.filter(
            User.contract_id == cid,
            User.role.in_(("customer", "customer_curator")),
        ).count()
        details = f"status={contract.status}"
        if contract.service_end_date != old_end:
            details += f"; service_end_date={old_end}->{contract.service_end_date}; users={users_count}"
        if contract.is_master_key_expired:
            details += "; master_key_expired=1"
        log_audit(current_user.id, "contract_update", "contract", cid, details)
        db.session.commit()
        if contract.is_access_disabled:
            when = contract.access_disabled_at
            when_txt = when.strftime("%d.%m.%Y") if when else "—"
            reason = (
                "истёк мастер-ключ"
                if contract.is_master_key_expired
                else "закрыт срок обслуживания / договор"
            )
            flash(
                f"Договор обновлён. Персональные УЗ отключены ({reason}, дата {when_txt}). "
                f"Затронуто: {synced or users_count}.",
                "warning",
            )
        elif contract.service_end_date != old_end and users_count:
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
    contract_users = (
        User.query.filter(
            User.contract_id == cid,
            User.role.in_(("customer", "customer_curator")),
        )
        .order_by(User.full_name)
        .all()
    )
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
    if sync_expired_master_key_access():
        db.session.commit()
    items = User.query.order_by(User.full_name).all()
    curator_project_tips: dict[int, str] = {}
    curator_ids = [u.id for u in items if u.role == "customer_curator"]
    if curator_ids:
        from servicesystem.project_management.models import Project

        by_curator: dict[int, list] = {}
        for p in (
            Project.query.filter(
                Project.customer_curator_id.in_(curator_ids),
                Project.is_template.is_(False),
            )
            .order_by(Project.name)
            .all()
        ):
            by_curator.setdefault(p.customer_curator_id, []).append(p)
        for uid, projs in by_curator.items():
            u = next((x for x in items if x.id == uid), None)
            bits = []
            if u and u.contract:
                c = u.contract
                bit = f"Договор №{c.number}"
                if c.service_end_date:
                    bit += f" · до {c.service_end_date.strftime('%d.%m.%Y')}"
                bits.append(bit)
            for p in projs[:5]:
                line = p.name
                if p.deadline:
                    line += f" · до {p.deadline.strftime('%d.%m.%Y')}"
                bits.append(line)
            if len(projs) > 5:
                bits.append(f"ещё {len(projs) - 5}")
            curator_project_tips[uid] = " | ".join(bits) if bits else "Проект не назначен"
        for uid in curator_ids:
            if uid not in curator_project_tips:
                u = next((x for x in items if x.id == uid), None)
                if u and u.contract:
                    c = u.contract
                    tip = f"Договор №{c.number}"
                    if c.service_end_date:
                        tip += f" · до {c.service_end_date.strftime('%d.%m.%Y')}"
                    tip += " · проект не назначен"
                    curator_project_tips[uid] = tip
                else:
                    curator_project_tips[uid] = "Проект не назначен"
    return render_template(
        "admin/users.html",
        users=items,
        curator_project_tips=curator_project_tips,
    )


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
        if user.role == "admin":
            user.is_active = True
        elif user.role == "customer_curator":
            # Куратор-заказчик: в админке всегда «Подключён» + синхрон договора с проектами
            user.is_active = True
            from servicesystem.project_management.services import (
                ensure_customer_curator_contract_access,
            )

            ok = ensure_customer_curator_contract_access(user)
            if not ok:
                flash(
                    "Роль куратора сохранена, но вход закрыт: продлите «Срок обслуживания» "
                    "в договоре организации или снимите статус «расторгнут».",
                    "warning",
                )
        else:
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


def _wants_structure_ajax() -> bool:
    return request.headers.get("X-Structure-Ajax") == "1"


def _tutorial_structure_bundle(tutorial: Tutorial):
    sections = (
        TutorialSection.query.filter_by(tutorial_id=tutorial.id)
        .order_by(TutorialSection.sort_order, TutorialSection.id)
        .all()
    )
    from servicesystem.services.tutorial_structure import build_lesson_tree

    lesson_trees_by_section: dict[int, list] = {}
    for sec in sections:
        rows = (
            TutorialLesson.query.filter_by(section_id=sec.id)
            .order_by(TutorialLesson.sort_order, TutorialLesson.id)
            .all()
        )
        lesson_trees_by_section[sec.id] = build_lesson_tree(rows)
    return sections, lesson_trees_by_section


def _structure_response(tutorial_id: int, message: str, category: str = "success", **extra):
    t = db.session.get(Tutorial, tutorial_id) or abort(404)
    if _wants_structure_ajax():
        sections, lesson_trees_by_section = _tutorial_structure_bundle(t)
        html = render_template(
            "admin/tutorial_structure_body.html",
            tutorial=t,
            sections=sections,
            lesson_trees_by_section=lesson_trees_by_section,
        )
        payload = {"ok": category != "danger", "message": message, "html": html}
        payload.update(extra)
        return jsonify(payload)
    flash(message, category)
    return redirect(url_for("admin.tutorial_edit", tid=tutorial_id) + "#tutorial-structure")


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
        if "content_md" in request.form:
            t.content_md = _form_cms_md("content_md")
        elif t.content_md is None:
            t.content_md = ""
        t.is_published = request.form.get("is_published") == "1"
        db.session.commit()
        flash("Туториал обновлён.", "success")
        return redirect(url_for("admin.tutorial_edit", tid=tid))
    sections, lesson_trees_by_section = _tutorial_structure_bundle(t)
    return render_template(
        "admin/tutorial_edit.html",
        tutorial=t,
        sections=sections,
        lesson_trees_by_section=lesson_trees_by_section,
    )


@bp.route("/tutorials/<int:tid>/delete", methods=["POST"])
@login_required
@content_cms_required
def tutorial_delete(tid):
    t = db.session.get(Tutorial, tid) or abort(404)
    title = (t.title or "")[:512]
    ContractContentAccess.query.filter_by(content_type="tutorial", content_id=t.id).delete(
        synchronize_session=False
    )
    db.session.delete(t)
    db.session.commit()
    log_audit(current_user.id, "tutorial_delete", "tutorial", tid, title)
    flash(f"Текстовый материал «{title}» удалён.", "success")
    return redirect(url_for("admin.tutorials"))


@bp.route("/tutorials/<int:tid>/sections", methods=["POST"])
@login_required
@content_cms_required
def tutorial_section_add(tid):
    from servicesystem.services.tutorial_structure import next_section_sort

    t = db.session.get(Tutorial, tid) or abort(404)
    title = (request.form.get("section_title") or "").strip() or "Новый раздел"
    sec = TutorialSection(tutorial_id=t.id, title=title[:512], sort_order=next_section_sort(t))
    db.session.add(sec)
    db.session.commit()
    return _structure_response(tid, "Раздел добавлен.", "success")


@bp.route("/tutorials/<int:tid>/structure/save", methods=["POST"])
@login_required
@content_cms_required
def tutorial_structure_save(tid):
    """Сохранить названия разделов и подразделов одной кнопкой."""
    t = db.session.get(Tutorial, tid) or abort(404)
    updated = 0
    sections = TutorialSection.query.filter_by(tutorial_id=t.id).all()
    for sec in sections:
        key = f"section_title_{sec.id}"
        val = (request.form.get(key) or "").strip()
        if not val:
            continue
        if sec.title != val:
            sec.title = val[:512]
            updated += 1
    for sec in sections:
        for les in (
            TutorialLesson.query.filter_by(section_id=sec.id)
            .order_by(TutorialLesson.sort_order, TutorialLesson.id)
            .all()
        ):
            key = f"lesson_title_{les.id}"
            val = (request.form.get(key) or "").strip()
            if not val:
                continue
            if les.title != val:
                les.title = val[:512]
                updated += 1
    if updated:
        db.session.commit()
        return _structure_response(tid, "Названия разделов и подразделов сохранены.", "success")
    return _structure_response(tid, "Изменений нет или не заполнены названия.", "warning")


@bp.route("/tutorials/sections/<int:sid>/edit", methods=["GET", "POST"])
@login_required
@content_cms_required
def tutorial_section_edit(sid):
    from servicesystem.services.tutorial_structure import section_page_slug

    sec = db.session.get(TutorialSection, sid) or abort(404)
    tutorial = sec.tutorial
    if request.method == "POST":
        sec.title = (request.form.get("title") or sec.title).strip()[:512]
        sec.content_md = _form_cms_md("content_md")
        db.session.commit()
        flash("Раздел сохранён.", "success")
        return redirect(url_for("admin.tutorial_section_edit", sid=sid))
    return render_template(
        "admin/tutorial_section_edit.html",
        section=sec,
        tutorial=tutorial,
        preview_slug=tutorial.slug,
        section_page_slug=section_page_slug(sec),
    )


@bp.route("/tutorials/sections/<int:sid>/rename", methods=["POST"])
@login_required
@content_cms_required
def tutorial_section_rename(sid):
    """Совместимость: один раздел."""
    sec = db.session.get(TutorialSection, sid) or abort(404)
    title = (request.form.get("section_title") or "").strip()
    if not title:
        for key, raw in request.form.items():
            if key.startswith("section_title_"):
                title = (raw or "").strip()
                break
    if title:
        sec.title = title[:512]
        db.session.commit()
        flash("Раздел переименован.", "success")
    return redirect(url_for("admin.tutorial_edit", tid=sec.tutorial_id) + "#tutorial-structure")


@bp.route("/tutorials/sections/<int:sid>/move", methods=["POST"])
@login_required
@content_cms_required
def tutorial_section_move(sid):
    from servicesystem.services.tutorial_structure import move_section

    sec = db.session.get(TutorialSection, sid) or abort(404)
    direction = -1 if request.form.get("dir") == "up" else 1
    move_section(sec, direction)
    db.session.commit()
    return _structure_response(sec.tutorial_id, "Порядок разделов обновлён.", "success")


@bp.route("/tutorials/sections/<int:sid>/delete", methods=["POST"])
@login_required
@content_cms_required
def tutorial_section_delete(sid):
    sec = db.session.get(TutorialSection, sid) or abort(404)
    tid = sec.tutorial_id
    db.session.delete(sec)
    db.session.commit()
    return _structure_response(tid, "Раздел удалён.", "success")


@bp.route("/tutorials/sections/<int:sid>/lessons", methods=["POST"])
@login_required
@content_cms_required
def tutorial_lesson_add(sid):
    from servicesystem.services.tutorial_structure import next_lesson_sort, unique_lesson_slug

    sec = db.session.get(TutorialSection, sid) or abort(404)
    title = (request.form.get("lesson_title") or "").strip() or "Новый урок"
    les = TutorialLesson(
        section_id=sec.id,
        title=title[:512],
        slug=unique_lesson_slug(sec, title),
        content_md="",
        sort_order=next_lesson_sort(sec),
    )
    db.session.add(les)
    db.session.commit()
    edit_url = url_for("admin.tutorial_lesson_edit", lid=les.id)
    if _wants_structure_ajax():
        return _structure_response(
            sec.tutorial_id,
            "Подраздел добавлен. Нажмите «Редактировать» для текста.",
            "success",
            edit_url=edit_url,
        )
    flash("Урок создан — заполните содержание.", "success")
    return redirect(edit_url)


@bp.route("/tutorials/lessons/<int:lid>/children", methods=["POST"])
@login_required
@content_cms_required
def tutorial_lesson_add_child(lid):
    from servicesystem.services.tutorial_structure import next_lesson_sort, unique_lesson_slug

    parent = db.session.get(TutorialLesson, lid) or abort(404)
    sec = parent.section
    depth = 0
    cur = parent
    while cur.parent_id:
        depth += 1
        cur = db.session.get(TutorialLesson, cur.parent_id) or cur
        if depth > 8:
            break
    if depth >= 3:
        return _structure_response(sec.tutorial_id, "Не более 4 уровней вложенности.", "warning")
    title = (request.form.get("lesson_title") or "").strip() or "Новый подпункт"
    les = TutorialLesson(
        section_id=sec.id,
        parent_id=parent.id,
        title=title[:512],
        slug=unique_lesson_slug(sec, title),
        content_md="",
        sort_order=next_lesson_sort(sec, parent.id),
    )
    db.session.add(les)
    db.session.commit()
    edit_url = url_for("admin.tutorial_lesson_edit", lid=les.id)
    if _wants_structure_ajax():
        return _structure_response(
            sec.tutorial_id,
            "Подпункт добавлен. Нажмите «Редактировать» для текста.",
            "success",
            edit_url=edit_url,
        )
    flash("Подпункт создан — заполните содержание.", "success")
    return redirect(edit_url)


@bp.route("/tutorials/lessons/<int:lid>/edit", methods=["GET", "POST"])
@login_required
@content_cms_required
def tutorial_lesson_edit(lid):
    from servicesystem.services.tutorial_structure import unique_lesson_slug

    les = db.session.get(TutorialLesson, lid) or abort(404)
    sec = les.section
    if request.method == "POST":
        les.title = (request.form.get("title") or les.title).strip()[:512]
        raw_slug = (request.form.get("slug") or "").strip()
        if raw_slug:
            les.slug = unique_lesson_slug(sec, raw_slug, exclude_id=les.id)
        else:
            les.slug = unique_lesson_slug(sec, les.title, exclude_id=les.id)
        les.content_md = _form_cms_md("content_md")
        db.session.commit()
        flash("Урок сохранён.", "success")
        return redirect(url_for("admin.tutorial_lesson_edit", lid=lid))
    return render_template(
        "admin/tutorial_lesson_edit.html",
        lesson=les,
        section=sec,
        tutorial=sec.tutorial,
    )


@bp.route("/tutorials/lessons/<int:lid>/move", methods=["POST"])
@login_required
@content_cms_required
def tutorial_lesson_move(lid):
    from servicesystem.services.tutorial_structure import move_lesson

    les = db.session.get(TutorialLesson, lid) or abort(404)
    direction = -1 if request.form.get("dir") == "up" else 1
    move_lesson(les, direction)
    db.session.commit()
    return _structure_response(les.section.tutorial_id, "Порядок уроков обновлён.", "success")


@bp.route("/tutorials/lessons/<int:lid>/delete", methods=["POST"])
@login_required
@content_cms_required
def tutorial_lesson_delete(lid):
    les = db.session.get(TutorialLesson, lid) or abort(404)
    tid = les.section.tutorial_id
    db.session.delete(les)
    db.session.commit()
    return _structure_response(tid, "Урок удалён.", "success")


@bp.route("/tutorials/<int:tid>/split-md", methods=["POST"])
@login_required
@content_cms_required
def tutorial_split_md(tid):
    """Разбить legacy content_md по заголовкам # / ## на разделы и уроки."""
    from servicesystem.services.tutorial_structure import split_markdown_into_structure

    t = db.session.get(Tutorial, tid) or abort(404)
    n = split_markdown_into_structure(t, t.content_md or "")
    db.session.commit()
    if n:
        return _structure_response(
            tid,
            f"Создано уроков: {n}. Проверьте структуру и отредактируйте при необходимости.",
            "success",
        )
    return _structure_response(tid, "Нечего разбивать — пустое содержание.", "warning")


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
            try:
                stored, stream_url = _save_uploaded_video(f)
            except ValueError as err:
                flash(str(err), "danger")
                chapters = "\n".join(
                    f"{c.start_sec}|{c.title}" + (f";{c.description}" if c.description else "")
                    for c in v.chapters.all()
                )
                return render_template("admin/video_edit.html", video=v, chapters=chapters)
            v.video_file = stored
            v.video_url = stream_url
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


@bp.route("/cms/preview-md", methods=["POST"])
@login_required
@content_cms_required
def cms_preview_md():
    """Предпросмотр Markdown тем же пайплайном, что и в ЛК."""
    from servicesystem.services.cms_html import render_cms_markdown

    data = request.get_json(silent=True) or {}
    md = data.get("md")
    if md is None:
        md = request.form.get("md") or ""
    return jsonify({"html": render_cms_markdown(md)})


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
        content_md=_form_cms_md("content_md"),
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
        post.content_md = _form_cms_md("content_md")
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


def _directory_form_context(org_id: int | None = None) -> dict:
    orgs = Organization.query.order_by(Organization.name).all()
    departments = (
        PhoneDirectoryDepartment.query.filter_by(is_active=True)
        .order_by(PhoneDirectoryDepartment.organization_id, PhoneDirectoryDepartment.sort_order)
        .all()
    )
    return {
        "organizations": orgs,
        "departments": departments,
        "filter_org": org_id,
    }


def _directory_departments_for_org(org_id: int):
    return (
        PhoneDirectoryDepartment.query.filter_by(organization_id=org_id, is_active=True)
        .order_by(PhoneDirectoryDepartment.sort_order, PhoneDirectoryDepartment.name)
        .all()
    )


def _parse_directory_contact_form(form):
    org_id = int(form["organization_id"])
    department = (form.get("department") or "").strip()
    email = (form.get("email") or "").strip().lower() or None
    if email and "@" not in email:
        raise ValueError("Некорректный email")
    mobile = (form.get("phone_mobile") or "").strip()
    if not mobile:
        raise ValueError("Мобильный телефон обязателен")
    work_raw = (form.get("phone_work") or form.get("phone_internal") or "").strip()
    phone_internal, phone_extension = split_work_phone(work_raw)
    if not phone_extension:
        phone_extension = (form.get("phone_extension") or "").strip() or None
    return {
        "organization_id": org_id,
        "department": repair_quoted_printable_text(department),
        "full_name": repair_quoted_printable_text(form["full_name"].strip()),
        "position": repair_quoted_printable_text((form.get("position") or "").strip()) or None,
        "phone_internal": phone_internal,
        "phone_extension": phone_extension,
        "phone_mobile": mobile,
        "email": email,
        "sort_order": max(0, int(form.get("sort_order") or 0)),
        "is_published": True,
    }


@bp.route("/directory")
@login_required
@staff_required
def directory():
    org_id = request.args.get("org", type=int)
    q = (request.args.get("q") or "").strip()
    contacts = staff_directory_query(org_id=org_id, q=q or None).all()
    orgs = Organization.query.order_by(Organization.name).all()
    archived_count = PhoneDirectoryContact.query.filter_by(is_active=False).count()
    ctx = dict(
        contacts=contacts,
        organizations=orgs,
        filter_org=org_id,
        search_q=q,
        archived_count=archived_count,
    )
    if request.args.get("partial") == "1":
        return render_template("admin/directory_rows.html", **ctx)
    return render_template("admin/directory.html", **ctx)


@bp.route("/directory/archive")
@login_required
@staff_required
def directory_archive():
    org_id = request.args.get("org", type=int)
    q = (request.args.get("q") or "").strip()
    contacts = staff_directory_query(org_id=org_id, q=q or None, archived=True).all()
    orgs = Organization.query.order_by(Organization.name).all()
    ctx = dict(
        contacts=contacts,
        organizations=orgs,
        filter_org=org_id,
        search_q=q,
    )
    if request.args.get("partial") == "1":
        return render_template("admin/directory_archive_rows.html", **ctx)
    return render_template("admin/directory_archive.html", **ctx)


@bp.route("/directory/import", methods=["GET"])
@login_required
@staff_required
def directory_import():
    org_id = request.args.get("org", type=int)
    return render_template("admin/directory_import.html", **_directory_form_context(org_id))


@bp.route("/directory/new", methods=["GET", "POST"])
@login_required
@staff_required
def directory_new():
    org_id = request.args.get("org", type=int) if request.method == "GET" else request.form.get("organization_id", type=int)
    if request.method == "POST":
        try:
            data = _parse_directory_contact_form(request.form)
        except (ValueError, KeyError) as exc:
            flash(str(exc) if str(exc) else "Заполните обязательные поля.", "danger")
            ctx = _directory_form_context(org_id)
            return render_template("admin/directory_new.html", **ctx)
        if not data["full_name"]:
            flash("Укажите ФИО.", "danger")
            ctx = _directory_form_context(org_id)
            return render_template("admin/directory_new.html", **ctx)
        dup = find_active_contact_by_mobile(data["phone_mobile"])
        if dup:
            flash(
                f"Контакт с таким мобильным уже есть: {dup.full_name}.",
                "danger",
            )
            ctx = _directory_form_context(org_id)
            return render_template("admin/directory_new.html", **ctx)
        contact = PhoneDirectoryContact(**data, author_id=current_user.id)
        db.session.add(contact)
        db.session.commit()
        log_audit(current_user.id, "directory_create", "phone_contact", contact.id, data["full_name"])
        db.session.commit()
        flash("Контакт добавлен.", "success")
        return redirect(url_for("admin.directory_edit", cid=contact.id))
    return render_template("admin/directory_new.html", **_directory_form_context(org_id))


@bp.route("/directory/departments", methods=["POST"])
@login_required
@staff_required
def directory_department_create():
    org_id = int(request.form["organization_id"])
    name = request.form["name"].strip()
    if not name:
        flash("Укажите название подразделения.", "danger")
        return redirect(url_for("admin.directory_import"))
    dept = PhoneDirectoryDepartment(organization_id=org_id, name=name)
    db.session.add(dept)
    db.session.commit()
    flash("Подразделение добавлено.", "success")
    return redirect(url_for("admin.directory_import", org=org_id))


@bp.route("/directory/import/vcf", methods=["POST"])
@login_required
@staff_required
def directory_import_vcf():
    org_id = request.form.get("organization_id", type=int)
    default_department = (request.form.get("default_department") or "Импорт").strip()
    upload = request.files.get("vcf_file")
    if not org_id or not upload or not upload.filename:
        flash("Выберите организацию и файл .vcf.", "danger")
        return redirect(url_for("admin.directory_import"))
    raw = upload.read(2 * 1024 * 1024)
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    parsed = parse_vcf_text(text)
    if not parsed:
        flash("В файле не найдено контактов vCard.", "warning")
        return redirect(url_for("admin.directory_import"))
    created = 0
    skipped_dup = 0
    for item in parsed:
        mobile = (item.phone_mobile or "").strip() or "—"
        if mobile != "—" and find_active_contact_by_mobile(mobile):
            skipped_dup += 1
            continue
        db.session.add(
            PhoneDirectoryContact(
                organization_id=org_id,
                department=repair_quoted_printable_text(item.department or default_department),
                full_name=repair_quoted_printable_text(item.full_name),
                position=repair_quoted_printable_text(item.position) if item.position else None,
                phone_internal=item.phone_internal,
                phone_extension=item.phone_extension,
                phone_mobile=mobile,
                email=item.email,
                is_published=True,
                author_id=current_user.id,
            )
        )
        created += 1
    db.session.commit()
    log_audit(
        current_user.id,
        "directory_import",
        "phone_contact",
        None,
        f"org={org_id}; count={created}; skipped_dup={skipped_dup}; file={upload.filename}",
    )
    db.session.commit()
    msg = f"Импортировано контактов: {created}."
    if skipped_dup:
        msg += f" Пропущено (такой мобильный уже есть): {skipped_dup}."
    flash(msg, "success")
    return redirect(url_for("admin.directory", org=org_id))


@bp.route("/directory/create", methods=["POST"])
@login_required
@staff_required
def directory_create_legacy():
    """Старые формы с action=/directory/create."""
    return directory_new()


def _directory_resolve_org_id(name: str | None, default_org_id: int) -> int:
    if not name or not name.strip():
        return default_org_id
    needle = name.strip()
    org = Organization.query.filter(Organization.name.ilike(needle)).first()
    if org:
        return org.id
    org = Organization.query.filter(Organization.name.ilike(f"%{needle}%")).first()
    return org.id if org else default_org_id


@bp.route("/directory/import-csv", methods=["POST"])
@login_required
@staff_required
def directory_import_csv():
    org_id = request.form.get("organization_id", type=int)
    default_department = (request.form.get("default_department") or "Импорт").strip()
    upload = request.files.get("csv_file")
    if not org_id or not upload or not upload.filename:
        flash("Выберите организацию по умолчанию и файл CSV.", "danger")
        return redirect(url_for("admin.directory_import"))
    raw = upload.read(5 * 1024 * 1024)
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    try:
        rows = parse_directory_csv(text, default_department=default_department)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.directory_import"))
    if not rows:
        flash("В CSV не найдено строк с ФИО.", "warning")
        return redirect(url_for("admin.directory_import"))
    created = 0
    skipped_dup = 0
    for row in rows:
        mobile = (row.phone_mobile or "").strip() or "—"
        if mobile != "—" and find_active_contact_by_mobile(mobile):
            skipped_dup += 1
            continue
        target_org = _directory_resolve_org_id(row.organization_name, org_id)
        work_main, work_ext = split_work_phone(row.phone_internal)
        db.session.add(
            PhoneDirectoryContact(
                organization_id=target_org,
                department=row.department,
                full_name=row.full_name,
                position=row.position,
                phone_internal=work_main,
                phone_extension=work_ext,
                phone_mobile=mobile,
                email=row.email,
                is_published=True,
                author_id=current_user.id,
            )
        )
        created += 1
    db.session.commit()
    log_audit(
        current_user.id,
        "directory_import_csv",
        "phone_contact",
        None,
        f"default_org={org_id}; count={created}; skipped_dup={skipped_dup}; file={upload.filename}",
    )
    db.session.commit()
    msg = f"Импортировано из CSV: {created}."
    if skipped_dup:
        msg += f" Пропущено (такой мобильный уже есть): {skipped_dup}."
    flash(msg, "success")
    return redirect(url_for("admin.directory", org=org_id))


def _directory_vcard_text(contact: PhoneDirectoryContact) -> str:
    org_name = contact.organization.name if contact.organization else ""
    return build_vcard(
        full_name=contact.full_name,
        position=contact.position,
        organization=org_name,
        department=contact.department or None,
        phone_internal=contact.phone_internal,
        phone_extension=contact.phone_extension,
        phone_mobile=contact.phone_mobile,
        email=contact.email,
    )


def _directory_export_contacts():
    """Same filter as GET /directory list."""
    org_raw = (request.args.get("org") or "").strip()
    org_id = int(org_raw) if org_raw.isdigit() else None
    q = (request.args.get("q") or "").strip() or None
    return staff_directory_query(org_id=org_id, q=q).all()


def _directory_vcard_entries(contacts: list[PhoneDirectoryContact]) -> list[tuple[str, str]]:
    """(archive_filename, vcard_text) for each exportable contact."""
    entries: list[tuple[str, str]] = []
    for i, contact in enumerate(contacts, 1):
        if not (contact.full_name or "").strip():
            continue
        try:
            text = _directory_vcard_text(contact).strip("\r\n")
        except ValueError:
            continue
        entries.append((f"{i:03d}_{safe_vcf_filename(contact.full_name, contact.id)}", text))
    return entries


def _directory_vcard_bundle(entries: list[tuple[str, str]]) -> str:
    return "\r\n\r\n".join(text for _, text in entries) + ("\r\n" if entries else "")


def _directory_vcard_zip(entries: list[tuple[str, str]]):
    import zipfile
    from io import BytesIO

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in entries:
            zf.writestr(name, text.encode("utf-8"))
    buf.seek(0)
    return buf


@bp.route("/directory/export.vcf")
@login_required
@staff_required
def directory_export_vcf():
    org_raw = (request.args.get("org") or "").strip()
    org_id = int(org_raw) if org_raw.isdigit() else None
    q = (request.args.get("q") or "").strip()
    items = _directory_export_contacts()
    if not items:
        flash("Нет контактов для выгрузки.", "warning")
        return redirect(url_for("admin.directory", org=org_id or "", q=q))
    from io import BytesIO

    entries = _directory_vcard_entries(items)
    card_count = len(entries)
    if card_count == 0:
        flash("Нет контактов для выгрузки.", "warning")
        return redirect(url_for("admin.directory", org=org_id or "", q=q))

    if card_count > 1:
        buf = _directory_vcard_zip(entries)
        resp = send_file(
            buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"spravochnik_{card_count}_kontaktov.zip",
        )
    else:
        body = _directory_vcard_bundle(entries)
        buf = BytesIO(body.encode("utf-8"))
        buf.seek(0)
        resp = send_file(
            buf,
            mimetype="text/vcard; charset=utf-8",
            as_attachment=True,
            download_name=entries[0][0],
        )
    resp.headers["X-Contact-Count"] = str(card_count)
    return resp


@bp.route("/directory/<int:cid>")
@login_required
@staff_required
def directory_detail(cid):
    contact = db.session.get(PhoneDirectoryContact, cid) or abort(404)
    if not contact.is_active:
        abort(404)
    vcard = _directory_vcard_text(contact)
    return render_template("admin/directory_detail.html", contact=contact, vcard=vcard)


@bp.route("/directory/<int:cid>/qr.svg")
@login_required
@staff_required
def directory_qr(cid):
    from flask import Response

    from servicesystem.services.contact_qr import vcard_qr_svg

    contact = db.session.get(PhoneDirectoryContact, cid) or abort(404)
    if not contact.is_active:
        abort(404)
    vcard = _directory_vcard_text(contact)
    svg = vcard_qr_svg(vcard)
    response = Response(svg, mimetype="image/svg+xml; charset=utf-8")
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


@bp.route("/directory/<int:cid>/vcf")
@login_required
@staff_required
def directory_vcf(cid):
    contact = db.session.get(PhoneDirectoryContact, cid) or abort(404)
    if not contact.is_active:
        abort(404)
    from io import BytesIO

    vcard = _directory_vcard_text(contact)
    buf = BytesIO(vcard.encode("utf-8"))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="text/vcard; charset=utf-8",
        as_attachment=True,
        download_name=safe_vcf_filename(contact.full_name, contact.id),
    )


@bp.route("/directory/<int:cid>/restore", methods=["POST"])
@login_required
@staff_required
def directory_restore(cid):
    contact = db.session.get(PhoneDirectoryContact, cid) or abort(404)
    if contact.is_active:
        flash("Контакт уже в активном справочнике.", "info")
        return redirect(url_for("admin.directory"))
    contact.is_active = True
    db.session.commit()
    log_audit(
        current_user.id,
        "directory_restore",
        "phone_contact",
        cid,
        contact.full_name,
    )
    db.session.commit()
    flash("Контакт восстановлен в справочник.", "success")
    org = request.args.get("org", type=int)
    q = (request.args.get("q") or "").strip()
    return redirect(url_for("admin.directory_archive", org=org, q=q or None))


@bp.route("/directory/<int:cid>/delete", methods=["POST"])
@login_required
@staff_required
def directory_delete(cid):
    """Безвозвратное удаление только из архива (is_active=False)."""
    contact = db.session.get(PhoneDirectoryContact, cid) or abort(404)
    if contact.is_active:
        flash("Сначала перенесите контакт в архив, затем удалите.", "warning")
        return redirect(url_for("admin.directory_edit", cid=cid))
    name = contact.full_name
    org = request.args.get("org", type=int)
    q = (request.args.get("q") or "").strip()
    db.session.delete(contact)
    db.session.commit()
    log_audit(
        current_user.id,
        "directory_delete",
        "phone_contact",
        cid,
        name,
    )
    db.session.commit()
    flash(f"Контакт «{name}» удалён из архива.", "success")
    return redirect(url_for("admin.directory_archive", org=org, q=q or None))


@bp.route("/directory/<int:cid>/edit", methods=["GET", "POST"])
@login_required
@staff_required
def directory_edit(cid):
    contact = db.session.get(PhoneDirectoryContact, cid) or abort(404)
    if not contact.is_active:
        abort(404)
    orgs = Organization.query.order_by(Organization.name).all()
    departments = _directory_departments_for_org(contact.organization_id)
    if request.method == "POST":
        if request.form.get("action") == "archive":
            contact.is_active = False
            db.session.commit()
            log_audit(
                current_user.id,
                "directory_archive",
                "phone_contact",
                cid,
                contact.full_name,
            )
            db.session.commit()
            flash("Контакт перенесён в архив.", "success")
            return redirect(url_for("admin.directory"))
        try:
            data = _parse_directory_contact_form(request.form)
        except (ValueError, KeyError) as exc:
            flash(str(exc) if str(exc) else "Проверьте поля формы.", "danger")
            return redirect(url_for("admin.directory_edit", cid=cid))
        if not data["full_name"]:
            flash("Укажите ФИО.", "danger")
            return redirect(url_for("admin.directory_edit", cid=cid))
        dup = find_active_contact_by_mobile(data["phone_mobile"], exclude_contact_id=cid)
        if dup:
            flash(
                f"Контакт с таким мобильным уже есть: {dup.full_name}.",
                "danger",
            )
            return redirect(url_for("admin.directory_edit", cid=cid))
        before = snapshot_contact(contact)
        for key, val in data.items():
            setattr(contact, key, val)
        log_directory_field_changes(current_user.id, contact.id, before, snapshot_contact(contact))
        sync_contact_to_user(contact)
        db.session.commit()
        flash("Контакт обновлён.", "success")
        return redirect(url_for("admin.directory_edit", cid=cid))
    return render_template(
        "admin/directory_edit.html",
        contact=contact,
        organizations=orgs,
        departments=departments,
    )


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
        content_md=_form_cms_md("content_md"),
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
        try:
            video_file, video_url = _save_uploaded_video(f)
        except ValueError as err:
            flash(str(err), "danger")
            return redirect(url_for("admin.videos"))
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
    from sqlalchemy import or_

    q = AuditLog.query
    user_id = request.args.get("user_id", type=int)
    action = request.args.get("action", "").strip()
    search = (request.args.get("q") or "").strip()
    if user_id:
        q = q.filter_by(user_id=user_id)
    if action:
        q = q.filter(AuditLog.action == action)
    if search:
        term = f"%{search}%"
        q = q.outerjoin(User, AuditLog.user_id == User.id).filter(
            or_(
                AuditLog.action.ilike(term),
                AuditLog.resource_type.ilike(term),
                AuditLog.details.ilike(term),
                User.full_name.ilike(term),
                User.email.ilike(term),
            )
        )
    logs = q.order_by(AuditLog.created_at.desc()).limit(500).all()
    users = User.query.order_by(User.full_name).all()
    actions = [r[0] for r in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
    ctx = dict(
        logs=logs,
        users=users,
        actions=actions,
        filter_user=user_id,
        filter_action=action,
        search_q=search,
    )
    if request.args.get("partial") == "1":
        return render_template("admin/audit_rows.html", **ctx)
    return render_template("admin/audit.html", **ctx)


@bp.route("/organizations/create", methods=["POST"])
@login_required
@admin_required
def org_create():
    name = (request.form.get("name") or "").strip()
    short_name = (request.form.get("short_name") or "").strip() or None
    if not name:
        flash("Укажите название организации.", "danger")
        return redirect(url_for("admin.contracts"))
    if _organization_name_taken(name):
        flash("Организация с таким названием уже есть.", "warning")
        return redirect(url_for("admin.contracts"))
    org = Organization(name=name, short_name=short_name)
    db.session.add(org)
    db.session.commit()
    log_audit(current_user.id, "organization_create", "organization", org.id, name)
    db.session.commit()
    flash("Организация добавлена.", "success")
    return redirect(url_for("admin.contracts"))


@bp.route("/organizations/<int:oid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def org_edit(oid):
    org = db.session.get(Organization, oid) or abort(404)
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        short_name = (request.form.get("short_name") or "").strip() or None
        if not name:
            flash("Укажите название организации.", "danger")
            return render_template("admin/org_edit.html", org=org)
        if _organization_name_taken(name, exclude_id=oid):
            flash("Организация с таким названием уже есть.", "warning")
            return render_template("admin/org_edit.html", org=org)
        before = f"{org.name} ({org.short_name or '—'})"
        org.name = name
        org.short_name = short_name
        db.session.commit()
        log_audit(
            current_user.id,
            "organization_update",
            "organization",
            oid,
            f"{before} → {name} ({short_name or '—'})",
        )
        db.session.commit()
        flash("Организация обновлена.", "success")
        return redirect(url_for("admin.contracts"))
    return render_template("admin/org_edit.html", org=org)


@bp.route("/organizations/<int:oid>/delete", methods=["POST"])
@login_required
@admin_required
def org_delete(oid):
    org = db.session.get(Organization, oid) or abort(404)
    blockers = _organization_delete_blockers(org)
    if blockers:
        flash(
            "Нельзя удалить организацию — есть привязки: " + ", ".join(blockers) + ".",
            "danger",
        )
        return redirect(url_for("admin.contracts"))
    name = org.name
    db.session.delete(org)
    db.session.commit()
    log_audit(current_user.id, "organization_delete", "organization", oid, name)
    db.session.commit()
    flash(f"Организация «{name}» удалена.", "success")
    return redirect(url_for("admin.contracts"))
