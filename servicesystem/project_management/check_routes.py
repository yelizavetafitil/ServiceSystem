"""Быстрая проверка HTTP маршрутов модуля проектов."""
from __future__ import annotations

import uuid

from servicesystem.app_factory import create_app
from servicesystem.extensions import db
from servicesystem.models import User
from sqlalchemy import or_

from servicesystem.project_management.models import (
    Project,
    ProjectCalendarEvent,
    ProjectCustomField,
    ProjectMember,
    ProjectStage,
    ProjectTask,
    ProjectTaskLink,
)


def _login(client, email: str):
    user = User.query.filter_by(email=email).first()
    assert user, email
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
    return user


def _delete_project_cascade(proj: Project) -> None:
    from servicesystem.project_management.models import (
        ProjectTaskAttachment,
        ProjectTaskCollaborator,
        ProjectTaskComment,
        ProjectTaskCustomValue,
        ProjectTimeLog,
    )

    pid = proj.id
    task_ids = [
        tid for (tid,) in db.session.query(ProjectTask.id).filter(ProjectTask.project_id == pid).all()
    ]
    if task_ids:
        ProjectCalendarEvent.query.filter(ProjectCalendarEvent.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
        ProjectTaskLink.query.filter(
            or_(
                ProjectTaskLink.from_task_id.in_(task_ids),
                ProjectTaskLink.to_task_id.in_(task_ids),
            )
        ).delete(synchronize_session=False)
        ProjectTaskCollaborator.query.filter(ProjectTaskCollaborator.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
        ProjectTaskAttachment.query.filter(ProjectTaskAttachment.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
        ProjectTaskComment.query.filter(ProjectTaskComment.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
        ProjectTaskCustomValue.query.filter(ProjectTaskCustomValue.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
        ProjectTimeLog.query.filter(ProjectTimeLog.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
        ProjectTask.query.filter(ProjectTask.project_id == pid).delete(synchronize_session=False)
    ProjectStage.query.filter_by(project_id=pid).delete(synchronize_session=False)
    ProjectMember.query.filter_by(project_id=pid).delete(synchronize_session=False)
    ProjectCustomField.query.filter_by(project_id=pid).delete(synchronize_session=False)
    row = db.session.get(Project, pid)
    if row:
        db.session.delete(row)
    db.session.commit()


def _smoke_create_project_and_task(client, auditor: User) -> list[str]:
    """POST создание проекта и задачи (без CSRF — только test client)."""
    app = client.application
    prev_csrf = app.config.get("WTF_CSRF_ENABLED", True)
    app.config["WTF_CSRF_ENABLED"] = False
    errors: list[str] = []
    proj: Project | None = None
    name: str | None = None
    try:
        name = f"__check_routes_{uuid.uuid4().hex[:12]}"
        r = client.post(
            "/projects/manage/new",
            data={
                "create_mode": "blank",
                "name": name,
                "curator_auditor_id": str(auditor.id),
            },
        )
        if r.status_code >= 500:
            errors.append(f"POST /projects/manage/new -> {r.status_code}")
            return errors
        proj = Project.query.filter_by(name=name).first()
        if not proj:
            errors.append("POST /projects/manage/new: проект не создан")
            return errors
        r_edit = client.get(f"/projects/manage/{proj.id}")
        if r_edit.status_code >= 500:
            errors.append(f"GET /projects/manage/{proj.id} after create -> {r_edit.status_code}")

        r_task = client.post(
            "/projects/tasks/new",
            data={
                "project_id": str(proj.id),
                "title": "__check_routes_task",
                "priority": "2",
            },
        )
        if r_task.status_code >= 500:
            errors.append(f"POST /projects/tasks/new -> {r_task.status_code}")
        task = ProjectTask.query.filter_by(project_id=proj.id, title="__check_routes_task").first()
        if not task:
            errors.append("POST /projects/tasks/new: задача не создана")
        else:
            r_detail = client.get(f"/projects/tasks/{task.id}")
            if r_detail.status_code >= 500:
                errors.append(f"GET /projects/tasks/{task.id} after create -> {r_detail.status_code}")

        tpl = Project.query.filter_by(is_template=True, is_active=True).order_by(Project.id).first()
        if tpl:
            tpl_name = f"__check_tpl_{uuid.uuid4().hex[:10]}"
            r_tpl = client.post(
                "/projects/manage/new",
                data={
                    "create_mode": "from_template",
                    "template_id": str(tpl.id),
                    "name": tpl_name,
                    "curator_auditor_id": str(auditor.id),
                },
            )
            if r_tpl.status_code >= 500:
                errors.append(f"POST from_template -> {r_tpl.status_code}")
            else:
                tpl_proj = Project.query.filter_by(name=tpl_name).first()
                if not tpl_proj:
                    errors.append("POST from_template: проект не создан")
                else:
                    r_tpl_edit = client.get(f"/projects/manage/{tpl_proj.id}")
                    if r_tpl_edit.status_code >= 500:
                        errors.append(f"GET manage after from_template -> {r_tpl_edit.status_code}")
                    try:
                        _delete_project_cascade(tpl_proj)
                    except Exception:
                        db.session.rollback()
    finally:
        app.config["WTF_CSRF_ENABLED"] = prev_csrf
        # всегда удаляем blank-проект smoke (раньше при from_template обнуляли proj)
        leftover = Project.query.filter_by(name=name).first() if name else None
        if leftover:
            try:
                _delete_project_cascade(leftover)
            except Exception:
                db.session.rollback()
    return errors


def main() -> int:
    app = create_app()
    errors: list[str] = []
    with app.app_context():
        client = app.test_client()
        base_paths = [
            "/projects/arm?view=kanban",
            "/projects/arm?view=gantt",
            "/projects/arm?view=week",
            "/projects/arm?view=calendar",
            "/projects/manage",
            "/projects/manage/new",
            "/projects/tasks/new",
            "/projects/settings/calendar",
            "/projects/calendar/export.ics",
        ]
        for p in Project.query.filter_by(is_template=False).limit(3):
            base_paths.append(f"/projects/manage/{p.id}")
        for t in ProjectTask.query.limit(15):
            base_paths.append(f"/projects/tasks/{t.id}")
            for tab in ("main", "files", "links", "comments", "custom", "time"):
                base_paths.append(f"/projects/tasks/{t.id}?tab={tab}")

        from servicesystem.project_management.services import user_can_reschedule_gantt

        auditor = User.query.filter_by(email="auditor@belnipi.by").first()
        assert auditor
        executor = User.query.filter_by(email="executor@belnipi.by").first()
        if executor and user_can_reschedule_gantt(executor):
            errors.append("executor must not reschedule gantt")
        if not user_can_reschedule_gantt(auditor):
            errors.append("auditor must be able to reschedule gantt")

        _login(client, auditor.email)
        errors.extend(_smoke_create_project_and_task(client, auditor))

        for role in ("admin@belnipi.by", "auditor@belnipi.by", "executor@belnipi.by"):
            _login(client, role)
            for path in base_paths:
                r = client.get(path)
                if r.status_code >= 500:
                    errors.append(f"{role} {path} -> {r.status_code}")
                elif r.status_code == 403 and role == "executor@belnipi.by" and "/manage" in path:
                    continue
                elif (
                    role == "executor@belnipi.by"
                    and "view=gantt" in path
                    and r.status_code in (302, 200)
                ):
                    # исполнитель с Ганта уходит на канбан — ок
                    continue
                elif r.status_code >= 400 and not (r.status_code == 403 and "manage" in path):
                    if r.status_code == 404 and "/tasks/" in path:
                        continue
                    errors.append(f"{role} {path} -> {r.status_code}")

    if errors:
        print("FAILURES:")
        for e in errors[:30]:
            print(" ", e)
        return 1
    print("OK:", len(base_paths), "paths x 3 roles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
