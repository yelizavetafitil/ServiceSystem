"""Проверка основных GET-страниц на 500 для ключевых ролей."""
from __future__ import annotations

from servicesystem.app_factory import create_app
from servicesystem.models import Contract, Organization, Ticket, User
from servicesystem.project_management.models import Project, ProjectTask


def _login(client, email: str) -> User:
    user = User.query.filter_by(email=email).first()
    assert user, email
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
    return user


def main() -> int:
    app = create_app()
    errors: list[str] = []
    with app.app_context():
        # Отдельный client на роль — без «залипания» сессии Flask-Login
        roles = [
            ("admin@belnipi.by", "admin"),
            ("auditor@belnipi.by", "auditor"),
            ("executor@belnipi.by", "executor"),
        ]
        curator_email = None
        customer_email = None
        curator = User.query.filter_by(role="customer_curator").first()
        customer = User.query.filter_by(role="customer").first()
        if curator:
            curator_email = curator.email
        if customer:
            customer_email = customer.email

        common = [
            "/",
            "/cabinet/",
            "/tickets/",
            "/tickets/staff",
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
        for p in Project.query.filter_by(is_template=False).limit(5):
            common.append(f"/projects/manage/{p.id}")
        for t in ProjectTask.query.limit(10):
            common.append(f"/projects/tasks/{t.id}")
            common.append(f"/projects/tasks/{t.id}?tab=links")
            common.append(f"/projects/tasks/{t.id}?tab=files")
        for t in Ticket.query.order_by(Ticket.id.desc()).limit(8):
            common.append(f"/tickets/{t.id}")

        admin_extra = ["/admin/", "/admin/contracts", "/admin/users"]
        if Organization.query.first():
            admin_extra.append(f"/admin/organizations")
        if Contract.query.first():
            admin_extra.append(f"/admin/contracts/{Contract.query.first().id}")

        customer_paths = ["/", "/cabinet/", "/tickets/", "/tickets/new"]
        for t in Ticket.query.limit(5):
            customer_paths.append(f"/tickets/{t.id}")

        for email, role in roles:
            client = app.test_client()
            _login(client, email)
            paths = list(common)
            if role == "admin":
                paths.extend(admin_extra)
            for path in paths:
                r = client.get(path)
                if r.status_code >= 500:
                    errors.append(f"{role} GET {path} -> {r.status_code}")
                elif r.status_code == 403 and role == "executor" and (
                    "/manage" in path or path.startswith("/admin")
                ):
                    continue
                elif r.status_code >= 400 and role != "executor":
                    if r.status_code == 404:
                        continue
                    if role == "executor" and "/manage" in path:
                        continue
                    # auditor/admin should mostly get 200/302
                    if r.status_code == 403 and path.startswith("/admin") and role != "admin":
                        continue
                    if r.status_code >= 400:
                        errors.append(f"{role} GET {path} -> {r.status_code}")

    # Куратор / заказчик / assign — отдельные app, иначе Flask-Login «залипает» в одном контексте
    if curator_email:
        app_c = create_app()
        with app_c.app_context():
            client = app_c.test_client()
            _login(client, curator_email)
            for path in ["/tickets/new", "/cabinet/", "/projects/arm?view=kanban", "/projects/arm?view=gantt"]:
                r = client.get(path)
                if r.status_code >= 500 or (path == "/tickets/new" and r.status_code >= 400):
                    errors.append(f"curator GET {path} -> {r.status_code}")

    if customer_email:
        app_cu = create_app()
        with app_cu.app_context():
            client = app_cu.test_client()
            _login(client, customer_email)
            for path in ["/", "/cabinet/", "/tickets/", "/tickets/new"]:
                r = client.get(path)
                if r.status_code >= 500:
                    errors.append(f"customer GET {path} -> {r.status_code}")

    app_p = create_app()
    with app_p.app_context():
        app_p.config["WTF_CSRF_ENABLED"] = False
        client = app_p.test_client()
        _login(client, "auditor@belnipi.by")
        ex = User.query.filter_by(role="executor", is_active=True).first()
        src = Ticket.query.first()
        if src and ex:
            import uuid

            nt = Ticket(
                number="T-CHK-" + uuid.uuid4().hex[:5],
                contract_id=src.contract_id,
                author_id=src.author_id,
                auditor_id=src.auditor_id,
                object_category_id=src.object_category_id,
                incident_category_id=src.incident_category_id,
                priority=2,
                subject="page-check assign",
                description_md="d",
                status="new",
            )
            from servicesystem.extensions import db

            db.session.add(nt)
            db.session.commit()
            tid = nt.id
            r = client.post(
                f"/tickets/{tid}/respond",
                data={"auditor_action": "assign", "executor_id": str(ex.id), "response_text": ""},
            )
            if r.status_code >= 500:
                errors.append(f"POST /tickets/{tid}/respond assign -> {r.status_code}")
            elif r.status_code not in (200, 302, 303):
                errors.append(f"POST assign -> {r.status_code}")
            # cleanup task+ticket (history immutable — leave history rows)
            from servicesystem.project_management.models import ProjectCalendarEvent

            pt = ProjectTask.query.filter_by(ticket_id=tid).first()
            if pt:
                ProjectCalendarEvent.query.filter_by(task_id=pt.id).delete()
                db.session.delete(pt)
            trow = db.session.get(Ticket, tid)
            if trow:
                db.session.delete(trow)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

    if errors:
        print("FAILURES:", len(errors))
        for e in errors[:40]:
            print(" ", e)
        return 1
    print("OK: pages checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
