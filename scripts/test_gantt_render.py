"""Smoke: render Gantt template (catch 500 causes)."""
from datetime import date

from flask import render_template

from servicesystem.app_factory import create_app
from servicesystem.models import User
from servicesystem.project_management.models import ProjectTask
from servicesystem.project_management.routes import KANBAN_LABELS, _gantt_layout, projects_ui_context
from servicesystem.project_management.models import TASK_KANBAN_COLUMNS


def main():
    app = create_app()
    with app.app_context():
        tasks = ProjectTask.query.all()
        user = User.query.filter_by(email="auditor@belnipi.by").first() or User.query.first()
        for scale in ("day", "week", "month", "quarter"):
            gantt = _gantt_layout(tasks, scale, user=user)
            ctx = {
                "view": "gantt",
                "projects": [],
                "filter_project": None,
                "tasks": tasks,
                "kanban_labels": KANBAN_LABELS,
                "columns": TASK_KANBAN_COLUMNS,
                "today": date.today(),
                "gantt_scale": scale,
                "gantt_group": "project",
                "cal_mode": "month",
                **projects_ui_context(),
            }
            html = render_template("projects/gantt.html", **ctx, **gantt)
            print(scale, "OK", len(html))

    with app.test_client() as client:
        with app.app_context():
            user = User.query.filter_by(email="auditor@belnipi.by").first() or User.query.first()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True
        for path in (
            "/projects/tasks/166?arm_view=gantt",
            "/projects/arm?view=gantt",
            "/projects/tasks/new?project=1",
        ):
            r = client.get(path)
            ok = r.status_code == 200 and b"Internal Server Error" not in r.data
            print(path, "OK" if ok else f"FAIL {r.status_code}")


if __name__ == "__main__":
    main()
