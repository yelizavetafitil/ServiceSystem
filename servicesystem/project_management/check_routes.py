"""Быстрая проверка HTTP маршрутов модуля проектов."""
from __future__ import annotations

from servicesystem.app_factory import create_app
from servicesystem.extensions import db
from servicesystem.models import User
from servicesystem.project_management.models import Project, ProjectTask


def _login(client, email: str):
    user = User.query.filter_by(email=email).first()
    assert user, email
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


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

        for role in ("admin@belnipi.by", "auditor@belnipi.by", "executor@belnipi.by"):
            _login(client, role)
            for path in base_paths:
                r = client.get(path)
                if r.status_code >= 500:
                    errors.append(f"{role} {path} -> {r.status_code}")
                elif r.status_code == 403 and role == "executor@belnipi.by" and "/manage" in path:
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
