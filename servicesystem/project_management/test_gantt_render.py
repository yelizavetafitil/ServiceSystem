"""Smoke: render Gantt template. Run: python -m servicesystem.project_management.test_gantt_render"""
from datetime import date

from flask import render_template
from flask_login import login_user

from servicesystem.app_factory import create_app
from servicesystem.models import User
from servicesystem.project_management.models import ProjectTask, TASK_KANBAN_COLUMNS
from servicesystem.project_management.routes import KANBAN_LABELS, _gantt_layout, projects_ui_context


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
            ctx.update(gantt)
            with app.test_request_context("/projects/arm?view=gantt"):
                login_user(user)
                html = render_template("projects/gantt.html", **ctx)
            print(scale, "OK", len(html))


if __name__ == "__main__":
    main()
