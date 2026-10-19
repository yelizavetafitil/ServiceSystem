"""Карточка задачи: файлы, таймер, связи, комментарии (ТЗ 1.5–1.8)."""
from __future__ import annotations

import mimetypes

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from servicesystem.extensions import db
from servicesystem.models import User
from servicesystem.project_management.models import (
    ProjectCustomField,
    ProjectCalendarFeed,
    ProjectStage,
    ProjectTask,
    ProjectTaskAttachment,
    ProjectTaskComment,
    ProjectTaskCustomValue,
    ProjectTaskLink,
    TASK_LINK_TYPES,
)
from servicesystem.project_management.dates import parse_optional_date
from servicesystem.project_management.routes import KANBAN_LABELS, bp
from servicesystem.project_management.services import (
    add_manual_time,
    build_ics_for_user,
    delete_project_task,
    delete_task_attachment,
    save_task_attachment,
    task_attachment_path,
    user_can_delete_task_attachment,
    task_is_completion_blocked,
    timer_start,
    timer_stop,
    user_can_edit_task,
    user_can_view_task,
    user_can_view_custom_field,
    sync_calendar_events_for_task,
)
from servicesystem.services.storage import get_storage


@bp.route("/tasks/<int:tid>", methods=["POST"])
@login_required
def task_update(tid):
    task = db.session.get(ProjectTask, tid) or abort(404)
    if not user_can_edit_task(current_user, task):
        abort(403)
    action = request.form.get("action", "save")
    if action == "delete":
        if not (current_user.is_admin or current_user.is_auditor):
            abort(403)
        if task.ticket_id:
            flash("Задача-зеркало заявки не удаляется здесь — закройте или удалите заявку.", "warning")
            return redirect(url_for("tickets.detail", tid=task.ticket_id))
        project_id = task.project_id
        try:
            delete_project_task(task)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("task delete failed tid=%s", tid)
            flash("Не удалось удалить задачу (связи или календарь). Попробуйте ещё раз.", "danger")
            return redirect(url_for("projects.task_detail", tid=tid))
        flash("Задача удалена.", "success")
        if project_id:
            return redirect(url_for("projects.arm", view="gantt", project=project_id))
        return redirect(url_for("projects.arm"))
    if action == "complete":
        if task_is_completion_blocked(task):
            flash("Задача заблокирована связями — сначала завершите блокирующие.", "danger")
            return redirect(url_for("projects.task_detail", tid=tid))
        task.kanban_status = "done"
        from datetime import datetime, timezone

        task.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        flash("Задача выполнена.", "success")
        return redirect(url_for("projects.task_detail", tid=tid))
    if action == "timer_start":
        timer_start(task, current_user.id)
        db.session.commit()
        return redirect(url_for("projects.task_detail", tid=tid))
    if action == "timer_stop":
        timer_stop(task, current_user.id)
        db.session.commit()
        return redirect(url_for("projects.task_detail", tid=tid))
    if action == "time_manual":
        hrs = float(request.form.get("hours") or 0)
        add_manual_time(task, current_user.id, hrs, request.form.get("note"))
        db.session.commit()
        flash("Время учтено.", "success")
        return redirect(url_for("projects.task_detail", tid=tid))
    if action == "comment":
        body = (request.form.get("body") or "").strip()
        if body:
            db.session.add(
                ProjectTaskComment(task_id=task.id, user_id=current_user.id, body=body)
            )
            db.session.commit()
        return redirect(url_for("projects.task_detail", tid=tid, tab="comments"))
    if action == "upload":
        f = request.files.get("file")
        if f and f.filename:
            try:
                att = save_task_attachment(task, f, current_user.id)
                db.session.add(att)
                db.session.commit()
                flash("Файл загружен.", "success")
                return redirect(
                    url_for("projects.task_detail", tid=tid, tab="files", preview=att.id)
                )
            except ValueError:
                flash("Файл превышает 100 Мб.", "danger")
        return redirect(url_for("projects.task_detail", tid=tid, tab="files"))
    if action == "link_add":
        other_id = request.form.get("other_task_id", type=int)
        link_type = request.form.get("link_type") or "related"
        other = db.session.get(ProjectTask, other_id) if other_id else None
        # predecessor / blocked_by → другая задача предшествует текущей (blocks: other → current)
        if link_type in ("predecessor", "blocked_by"):
            from_id, to_id, store_type = other_id, task.id, "blocks"
        elif link_type == "blocks":
            from_id, to_id, store_type = task.id, other_id, "blocks"
        elif link_type == "related":
            from_id, to_id, store_type = task.id, other_id, "related"
        else:
            from_id = to_id = store_type = None
        if not other_id or not other:
            flash("Выберите задачу для связи.", "warning")
        elif other_id == task.id:
            flash("Нельзя связать задачу саму с собой.", "warning")
        elif other.project_id != task.project_id:
            flash("Связь возможна только внутри одного проекта.", "warning")
        elif store_type is None or store_type not in TASK_LINK_TYPES:
            flash("Неверный тип связи.", "warning")
        else:
            exists = ProjectTaskLink.query.filter_by(
                from_task_id=from_id, to_task_id=to_id, link_type=store_type
            ).first()
            if exists:
                flash("Такая связь уже есть.", "warning")
            else:
                db.session.add(
                    ProjectTaskLink(from_task_id=from_id, to_task_id=to_id, link_type=store_type)
                )
                if store_type == "blocks":
                    from servicesystem.project_management.services import cascade_fs_schedule

                    succ = db.session.get(ProjectTask, to_id)
                    if succ:
                        cascade_fs_schedule(succ)
                db.session.commit()
                flash("Связь добавлена.", "success")
        return redirect(url_for("projects.task_detail", tid=tid, tab="links"))
    if action == "link_remove":
        lid = request.form.get("link_id", type=int)
        link = db.session.get(ProjectTaskLink, lid) if lid else None
        if link and (link.from_task_id == task.id or link.to_task_id == task.id):
            db.session.delete(link)
            db.session.commit()
            flash("Связь удалена.", "success")
        return redirect(url_for("projects.task_detail", tid=tid, tab="links"))
    if action == "custom_save":
        proj = task.project
        if proj:
            for field in proj.custom_fields:
                if not user_can_view_custom_field(current_user, field):
                    continue
                key = f"cf_{field.id}"
                val = request.form.get(key)
                row = ProjectTaskCustomValue.query.filter_by(task_id=task.id, field_id=field.id).first()
                if not row:
                    row = ProjectTaskCustomValue(task_id=task.id, field_id=field.id)
                    db.session.add(row)
                row.value_text = val
        db.session.commit()
        flash("Доп. поля сохранены.", "success")
        return redirect(url_for("projects.task_detail", tid=tid, tab="custom"))

    task.title = request.form["title"].strip()
    task.description = (request.form.get("description") or "").strip() or None
    task.priority = int(request.form.get("priority") or 2)
    task.kanban_status = request.form.get("kanban_status") or task.kanban_status
    assignee_id = request.form.get("assignee_id", type=int) or None
    from servicesystem.project_management.services import is_project_member

    if assignee_id and not is_project_member(task.project_id, assignee_id):
        flash("Исполнитель должен быть участником проекта.", "warning")
        return redirect(url_for("projects.task_detail", tid=tid))
    task.assignee_id = assignee_id
    task.due_date = parse_optional_date(request.form.get("due_date"))
    task.start_date = parse_optional_date(request.form.get("start_date"))
    stage_id = request.form.get("stage_id", type=int)
    if stage_id:
        st = db.session.get(ProjectStage, stage_id)
        if st and st.project_id == task.project_id:
            task.stage_id = stage_id
        else:
            flash("Этап не принадлежит проекту задачи.", "warning")
    elif "stage_id" in request.form:
        task.stage_id = None
    if current_user.is_auditor or current_user.is_admin:
        from servicesystem.project_management.models import ProjectTaskCollaborator

        ProjectTaskCollaborator.query.filter_by(task_id=task.id).delete()
        for uid in request.form.getlist("collaborator_ids"):
            if is_project_member(task.project_id, int(uid)):
                db.session.add(ProjectTaskCollaborator(task_id=task.id, user_id=int(uid)))
    sync_calendar_events_for_task(task)
    from servicesystem.project_management.services import cascade_fs_from_task

    cascade_fs_from_task(task)
    db.session.commit()
    from servicesystem.project_management.caldav_sync import try_push_task_to_caldav

    try_push_task_to_caldav(task)
    flash("Сохранено.", "success")
    return redirect(url_for("projects.task_detail", tid=tid))


@bp.route("/tasks/<int:tid>/files/<int:aid>")
@login_required
def task_file_view(tid, aid):
    task = db.session.get(ProjectTask, tid) or abort(404)
    att = db.session.get(ProjectTaskAttachment, aid) or abort(404)
    if att.task_id != task.id or not user_can_view_task(current_user, task):
        abort(403)
    path = get_storage().read_path(task_attachment_path(att))
    inline = request.args.get("download") != "1"
    mime = att.mime_type or mimetypes.guess_type(att.original_name or "")[0] or "application/octet-stream"
    return send_file(path, mimetype=mime, as_attachment=not inline, download_name=att.original_name)


@bp.route("/tasks/<int:tid>/files/<int:aid>/delete", methods=["POST"])
@login_required
def task_file_delete(tid, aid):
    task = db.session.get(ProjectTask, tid) or abort(404)
    att = db.session.get(ProjectTaskAttachment, aid) or abort(404)
    if att.task_id != task.id or not user_can_delete_task_attachment(current_user, task, att):
        abort(403)
    delete_task_attachment(att)
    db.session.commit()
    flash("Файл удалён.", "success")
    return redirect(url_for("projects.task_detail", tid=tid, tab="files"))


@bp.route("/tasks/<int:tid>/files/<int:aid>/verify", methods=["POST"])
@login_required
def task_file_verify(tid, aid):
    if not (current_user.is_auditor or current_user.is_admin):
        abort(403)
    task = db.session.get(ProjectTask, tid) or abort(404)
    att = db.session.get(ProjectTaskAttachment, aid) or abort(404)
    if att.task_id != task.id:
        abort(404)
    from datetime import datetime, timezone

    att.verified_at = datetime.now(timezone.utc)
    att.verified_by_id = current_user.id
    db.session.commit()
    flash("Файл верифицирован.", "success")
    return redirect(url_for("projects.task_detail", tid=tid, tab="files"))


@bp.route("/settings/calendar", methods=["GET", "POST"])
@login_required
def calendar_settings():
    if not current_user.is_staff:
        abort(403)
    from servicesystem.project_management.caldav_sync import sync_caldav_feed

    feed = ProjectCalendarFeed.query.filter_by(user_id=current_user.id).first()
    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "sync_now":
            if not feed:
                flash("Сначала сохраните настройки календаря.", "warning")
                return redirect(url_for("projects.calendar_settings"))
            result = sync_caldav_feed(current_user, feed)
            if result.get("ok"):
                flash(result.get("message") or feed.last_sync_message or "Синхронизация выполнена.", "success")
            else:
                flash(f"Синхронизация: {result.get('error', 'ошибка')}", "danger")
            return redirect(url_for("projects.calendar_settings"))
        if not feed:
            feed = ProjectCalendarFeed(user_id=current_user.id)
            db.session.add(feed)
        feed.provider = request.form.get("provider") or "caldav"
        feed.feed_url = (request.form.get("feed_url") or "").strip() or None
        feed.caldav_username = (request.form.get("caldav_username") or "").strip() or None
        pwd = (request.form.get("caldav_password") or "").strip()
        if pwd:
            feed.caldav_password = pwd
        feed.sync_enabled = request.form.get("sync_enabled") == "1"
        feed.email_reminders = request.form.get("email_reminders") == "1"
        feed.reminder_minutes = int(request.form.get("reminder_minutes") or 60)
        db.session.commit()
        flash("Настройки календаря сохранены.", "success")
        return redirect(url_for("projects.calendar_settings"))
    from servicesystem.services.public_url import app_external_url

    export_url = app_external_url("projects.calendar_export_ics")
    return render_template(
        "projects/calendar_settings.html",
        feed=feed,
        export_url=export_url,
    )


@bp.route("/calendar/export.ics")
@login_required
def calendar_export_ics():
    if not current_user.is_staff:
        abort(403)
    from flask import Response

    body = build_ics_for_user(current_user)
    return Response(body, mimetype="text/calendar", headers={"Content-Disposition": "attachment; filename=projects.ics"})


@bp.route("/api/tasks/<int:tid>/dates", methods=["POST"])
@login_required
def api_task_dates(tid):
    task = db.session.get(ProjectTask, tid) or abort(404)
    if not user_can_edit_task(current_user, task):
        abort(403)
    data = request.get_json(silent=True) or {}
    if data.get("start_date"):
        task.start_date = parse_optional_date(data["start_date"])
    if data.get("due_date"):
        task.due_date = parse_optional_date(data["due_date"])
    sync_calendar_events_for_task(task)
    db.session.commit()
    from servicesystem.project_management.caldav_sync import try_push_task_to_caldav

    try_push_task_to_caldav(task)
    return jsonify({"ok": True})
