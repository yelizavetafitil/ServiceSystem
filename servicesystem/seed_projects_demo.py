"""Дозаполнение демо-данных модуля проектов (монтируется в Docker)."""
from __future__ import annotations

from datetime import date, timedelta

from servicesystem.app_factory import create_app
from servicesystem.extensions import db
from servicesystem.models import Contract, Ticket, User
from servicesystem.project_management.models import (
    Project,
    ProjectCustomField,
    ProjectMember,
    ProjectStage,
    ProjectTask,
    ProjectTaskCollaborator,
    ProjectTaskLink,
)
from servicesystem.project_management.services import on_ticket_sync_hook, update_customer_curator_window


def ensure_template_tasks() -> int:
    """Типовые задачи и поле в шаблоне (ТЗ 4.3) для проверки «Развернуть»."""
    tpl = Project.query.filter_by(is_template=True).order_by(Project.id).first()
    if not tpl:
        return 0
    added = 0
    if not tpl.custom_fields.count():
        db.session.add(
            ProjectCustomField(
                project_id=tpl.id,
                name="Бюджет этапа",
                field_type="budget",
                visibility="auditor",
                sort_order=0,
            )
        )
        added += 1
    if ProjectTask.query.filter_by(project_id=tpl.id).first():
        return added
    auditor = User.query.filter_by(email="auditor@belnipi.by").first()
    executor = User.query.filter_by(email="executor@belnipi.by").first()
    if not (auditor and executor):
        return added
    today = date.today()
    stages = list(tpl.stages.order_by(ProjectStage.sort_order))
    sid0 = stages[0].id if stages else None
    sid1 = stages[1].id if len(stages) > 1 else sid0
    sid2 = stages[2].id if len(stages) > 2 else sid1
    cfg = [
        ("Шаблон: согласование исходных данных", sid0, 3),
        ("Шаблон: построение модели", sid1, 2),
        ("Шаблон: гидравлический расчёт", sid1, 2),
        ("Шаблон: сдача отчётного этапа", sid2, 2),
    ]
    created: list[ProjectTask] = []
    for i, (title, stage_id, prio) in enumerate(cfg):
        t = ProjectTask(
            project_id=tpl.id,
            stage_id=stage_id,
            title=title,
            priority=prio,
            kanban_status="todo",
            assignee_id=executor.id,
            start_date=today,
            due_date=today + timedelta(days=7 + i * 5),
            created_by_id=auditor.id,
        )
        db.session.add(t)
        db.session.flush()
        created.append(t)
        added += 1
    if len(created) >= 2:
        db.session.add(
            ProjectTaskLink(
                from_task_id=created[0].id,
                to_task_id=created[1].id,
                link_type="blocks",
            )
        )
        added += 1
    return added


def enrich_gantt_samples() -> int:
    """Задачи с разными датами для проверки масштабов Gantt."""
    if ProjectTask.query.filter(ProjectTask.title.like("Ганта:%")).first():
        return 0
    auditor = User.query.filter_by(email="auditor@belnipi.by").first()
    executor = User.query.filter_by(email="executor@belnipi.by").first()
    proj = Project.query.filter_by(name="Разработка ЭМСТПН — Брестэнерго").first()
    if not (auditor and executor and proj):
        return 0
    today = date.today()
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    month_end = next_month - timedelta(days=1)
    q_start = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)
    samples = [
        ("Ганта: только сегодня", today, today, 2),
        ("Ганта: эта неделя (короткая)", today, today + timedelta(days=2), 2),
        ("Ганта: весь месяц", month_start, month_end, 2),
        ("Ганта: длинный этап", today - timedelta(days=5), today + timedelta(days=25), 3),
        ("Ганта: следующий месяц", next_month, next_month + timedelta(days=20), 2),
        ("Ганта: начало квартала", q_start, q_start + timedelta(days=14), 1),
    ]
    created_gantt: list[ProjectTask] = []
    for title, s, e, prio in samples:
        t = ProjectTask(
            project_id=proj.id,
            title=title,
            description="Демо для шкалы Gantt",
            priority=prio,
            kanban_status="todo",
            assignee_id=executor.id,
            start_date=s,
            due_date=e,
            created_by_id=auditor.id,
        )
        db.session.add(t)
        db.session.flush()
        created_gantt.append(t)
    if len(created_gantt) >= 4:
        db.session.add(
            ProjectTaskLink(
                from_task_id=created_gantt[1].id,
                to_task_id=created_gantt[3].id,
                link_type="blocks",
            )
        )
        db.session.add(
            ProjectTaskLink(
                from_task_id=created_gantt[2].id,
                to_task_id=created_gantt[5].id,
                link_type="related",
            )
        )
    topo = ProjectTask.query.filter(ProjectTask.title.like("Согласование топологии%")).first()
    pipe = ProjectTask.query.filter(ProjectTask.title.like("Расчёт давления%")).first()
    if topo and pipe and not ProjectTaskLink.query.filter_by(from_task_id=topo.id, to_task_id=pipe.id).first():
        db.session.add(ProjectTaskLink(from_task_id=topo.id, to_task_id=pipe.id, link_type="blocks"))
    return len(samples)


def ensure_gantt_demo_links() -> int:
    """Связи для проверки стрелок на диаграмме Ганта."""
    added = 0
    topo = ProjectTask.query.filter(ProjectTask.title.like("Согласование топологии%")).first()
    pipe = ProjectTask.query.filter(ProjectTask.title.like("Расчёт давления%")).first()
    if topo and pipe and not ProjectTaskLink.query.filter_by(
        from_task_id=topo.id, to_task_id=pipe.id, link_type="blocks"
    ).first():
        db.session.add(ProjectTaskLink(from_task_id=topo.id, to_task_id=pipe.id, link_type="blocks"))
        added += 1
    gantt = (
        ProjectTask.query.filter(ProjectTask.title.like("Ганта:%"))
        .order_by(ProjectTask.id)
        .all()
    )
    if len(gantt) >= 4:
        pairs = ((1, 3, "blocks"), (2, 5, "related"))
        for a, b, lt in pairs:
            if a >= len(gantt) or b >= len(gantt):
                continue
            fr, to = gantt[a].id, gantt[b].id
            if not ProjectTaskLink.query.filter_by(from_task_id=fr, to_task_id=to, link_type=lt).first():
                db.session.add(ProjectTaskLink(from_task_id=fr, to_task_id=to, link_type=lt))
                added += 1
    return added


def apply() -> int:
    tpl_added = ensure_template_tasks()
    if tpl_added:
        db.session.commit()
    added = enrich_gantt_samples()
    added += ensure_gantt_demo_links()
    if added:
        db.session.commit()
    if Project.query.filter_by(is_template=False).first():
        return Project.query.count()

    auditor = User.query.filter_by(email="auditor@belnipi.by").first()
    executor = User.query.filter_by(email="executor@belnipi.by").first()
    executor2 = User.query.filter_by(email="executor2@belnipi.by").first()
    customers = User.query.filter(User.role.in_(("customer", "customer_curator"))).order_by(User.id).all()
    contracts = Contract.query.order_by(Contract.id).all()
    if not (auditor and executor and contracts and customers):
        raise RuntimeError("Need auditor, executor, contracts and customers in DB (run seed.py --force in image)")

    today = date.today()
    curator = customers[1] if len(customers) > 1 else customers[0]
    curator.role = "customer_curator"
    brest = contracts[0]

    tpl = Project(
        name="Шаблон: типовой проект ЭМСТПН",
        description="Этапы разработки и актуализации модели",
        is_template=True,
        planned_start=today,
        deadline=today + timedelta(days=180),
        curator_auditor_id=auditor.id,
    )
    db.session.add(tpl)
    db.session.flush()
    for i, title in enumerate(("Сбор исходных данных", "Построение топологии", "Гидравлический расчёт", "Сдача этапа")):
        db.session.add(ProjectStage(project_id=tpl.id, title=title, sort_order=i, deadline=today + timedelta(days=30 * (i + 1))))

    proj = Project(
        name="Разработка ЭМСТПН — Брестэнерго",
        contract_id=brest.id,
        description="Проект по договору 060-194-25",
        planned_start=today - timedelta(days=14),
        deadline=today + timedelta(days=90),
        curator_auditor_id=auditor.id,
        customer_curator_id=curator.id,
    )
    db.session.add(proj)
    db.session.flush()
    update_customer_curator_window(proj)
    db.session.add(ProjectMember(project_id=proj.id, user_id=executor.id, role="executor"))
    if executor2:
        db.session.add(ProjectMember(project_id=proj.id, user_id=executor2.id, role="executor"))

    stages = []
    for i, (title, days) in enumerate(
        (
            ("Этап 1 — Исходные данные", 30),
            ("Этап 2 — Модель и расчёт", 60),
            ("Этап 3 — Сдача заказчику", 90),
        )
    ):
        st = ProjectStage(
            project_id=proj.id,
            title=title,
            deadline=today + timedelta(days=days),
            responsible_id=executor.id if i % 2 == 0 else auditor.id,
            sort_order=i,
        )
        db.session.add(st)
        stages.append(st)
    db.session.flush()

    db.session.add(ProjectCustomField(project_id=proj.id, name="Бюджет этапа", field_type="budget", visibility="auditor", sort_order=0))
    db.session.add(ProjectCustomField(project_id=proj.id, name="Ссылка на модель", field_type="url", visibility="all", sort_order=1))

    created = []
    for title, status, prio, assignee, stage_id in (
        ("Согласование топологии участка №14", "todo", 3, executor.id, stages[0].id),
        ("Расчёт давления магистрали", "in_progress", 2, executor.id, stages[1].id),
        ("Проверка отчёта ГИП", "review", 2, auditor.id, stages[1].id),
        ("Подготовка исполнительной документации", "todo", 2, (executor2 or executor).id, stages[2].id),
    ):
        t = ProjectTask(
            project_id=proj.id,
            stage_id=stage_id,
            title=title,
            description=f"Демо: {title}",
            priority=prio,
            kanban_status=status,
            assignee_id=assignee,
            start_date=today - timedelta(days=3),
            due_date=today + timedelta(days=7 + len(created)),
            created_by_id=auditor.id,
        )
        db.session.add(t)
        db.session.flush()
        created.append(t)

    if executor2:
        db.session.add(
            ProjectTask(
                project_id=proj.id,
                parent_id=created[1].id,
                title="Чек-лист: узлы 1–20",
                priority=2,
                kanban_status="in_progress",
                assignee_id=executor2.id,
                due_date=today + timedelta(days=5),
                created_by_id=executor.id,
            )
        )
        db.session.add(ProjectTaskCollaborator(task_id=created[1].id, user_id=executor2.id))

    db.session.add(ProjectTaskLink(from_task_id=created[0].id, to_task_id=created[1].id, link_type="blocks"))
    db.session.add(
        ProjectTask(
            title="Внутренняя задача без проекта",
            priority=1,
            kanban_status="todo",
            assignee_id=executor.id,
            due_date=today + timedelta(days=2),
            created_by_id=auditor.id,
        )
    )

    for t in Ticket.query.all():
        on_ticket_sync_hook(t)

    db.session.commit()
    return Project.query.count()


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        n = apply()
        print(f"Projects in DB: {n}")
