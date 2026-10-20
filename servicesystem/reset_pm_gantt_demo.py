"""Очистка проектов (кроме техподдержки) и создание демо для проверки Ганта/WBS/FS."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import or_

from servicesystem.app_factory import create_app
from servicesystem.extensions import db
from servicesystem.models import Contract, User
from servicesystem.project_management.models import (
    Project,
    ProjectCalendarEvent,
    ProjectCustomField,
    ProjectMember,
    ProjectStage,
    ProjectStageAttachment,
    ProjectTask,
    ProjectTaskAttachment,
    ProjectTaskCollaborator,
    ProjectTaskComment,
    ProjectTaskCustomValue,
    ProjectTaskLink,
    ProjectTimeLog,
)
from servicesystem.project_management.services import (
    reschedule_project_tasks_to_workdays,
    update_customer_curator_window,
)


def _wipe_project(pid: int) -> None:
    task_ids = [
        tid for (tid,) in db.session.query(ProjectTask.id).filter(ProjectTask.project_id == pid).all()
    ]
    stage_ids = [
        sid for (sid,) in db.session.query(ProjectStage.id).filter(ProjectStage.project_id == pid).all()
    ]
    if stage_ids:
        ProjectStageAttachment.query.filter(ProjectStageAttachment.stage_id.in_(stage_ids)).delete(
            synchronize_session=False
        )
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
        ProjectTask.query.filter(ProjectTask.project_id == pid).update(
            {ProjectTask.parent_id: None}, synchronize_session=False
        )
        ProjectTask.query.filter(ProjectTask.project_id == pid).delete(synchronize_session=False)
    ProjectStage.query.filter_by(project_id=pid).delete(synchronize_session=False)
    ProjectMember.query.filter_by(project_id=pid).delete(synchronize_session=False)
    ProjectCustomField.query.filter_by(project_id=pid).delete(synchronize_session=False)
    row = db.session.get(Project, pid)
    if row:
        db.session.delete(row)


def wipe_non_support() -> int:
    """Удалить шаблоны, обычные проекты и задачи без проекта. Техподдержку оставить."""
    Project.query.filter(Project.template_source_id.isnot(None)).update(
        {Project.template_source_id: None}, synchronize_session=False
    )
    db.session.flush()
    ids = [
        pid
        for (pid,) in db.session.query(Project.id)
        .filter(or_(Project.is_support_project.is_(False), Project.is_support_project.is_(None)))
        .all()
    ]
    for pid in ids:
        _wipe_project(pid)

    orphan_ids = [
        tid for (tid,) in db.session.query(ProjectTask.id).filter(ProjectTask.project_id.is_(None)).all()
    ]
    if orphan_ids:
        ProjectCalendarEvent.query.filter(ProjectCalendarEvent.task_id.in_(orphan_ids)).delete(
            synchronize_session=False
        )
        ProjectTaskLink.query.filter(
            or_(
                ProjectTaskLink.from_task_id.in_(orphan_ids),
                ProjectTaskLink.to_task_id.in_(orphan_ids),
            )
        ).delete(synchronize_session=False)
        ProjectTaskCollaborator.query.filter(ProjectTaskCollaborator.task_id.in_(orphan_ids)).delete(
            synchronize_session=False
        )
        ProjectTaskAttachment.query.filter(ProjectTaskAttachment.task_id.in_(orphan_ids)).delete(
            synchronize_session=False
        )
        ProjectTaskComment.query.filter(ProjectTaskComment.task_id.in_(orphan_ids)).delete(
            synchronize_session=False
        )
        ProjectTaskCustomValue.query.filter(ProjectTaskCustomValue.task_id.in_(orphan_ids)).delete(
            synchronize_session=False
        )
        ProjectTimeLog.query.filter(ProjectTimeLog.task_id.in_(orphan_ids)).delete(
            synchronize_session=False
        )
        ProjectTask.query.filter(ProjectTask.id.in_(orphan_ids)).update(
            {ProjectTask.parent_id: None}, synchronize_session=False
        )
        ProjectTask.query.filter(ProjectTask.id.in_(orphan_ids)).delete(synchronize_session=False)

    db.session.commit()
    return len(ids)


def _task(
    *,
    project_id: int,
    title: str,
    auditor_id: int,
    assignee_id: int,
    start: date,
    due: date,
    stage_id: int | None = None,
    parent_id: int | None = None,
    status: str = "todo",
    priority: int = 2,
    gantt_sort: int = 0,
    description: str | None = None,
) -> ProjectTask:
    t = ProjectTask(
        project_id=project_id,
        stage_id=stage_id,
        parent_id=parent_id,
        title=title,
        description=description or f"Демо: {title}",
        priority=priority,
        kanban_status=status,
        assignee_id=assignee_id,
        start_date=start,
        due_date=due,
        gantt_sort=gantt_sort,
        created_by_id=auditor_id,
    )
    db.session.add(t)
    db.session.flush()
    return t


def seed_demo() -> Project:
    auditor = User.query.filter_by(email="auditor@belnipi.by").first()
    executor = User.query.filter_by(email="executor@belnipi.by").first()
    executor2 = User.query.filter_by(email="executor2@belnipi.by").first()
    contract = Contract.query.order_by(Contract.id).first()
    if not (auditor and executor and contract):
        raise RuntimeError("Need auditor@, executor@ and a contract in DB")

    today = date.today()
    # Рамка проекта: ~2 месяца, с пропуском выходных
    p_start = today - timedelta(days=3)
    p_end = today + timedelta(days=55)

    proj = Project(
        name="Демо Ганта — реконструкция теплосети",
        contract_id=contract.id,
        description=(
            "Демонстрационный проект: WBS (родители/подзадачи), FS-стрелки, "
            "границы дат родителя и проекта, пропуск выходных и праздников РБ."
        ),
        planned_start=p_start,
        deadline=p_end,
        skip_weekends=True,
        skip_public_holidays=True,
        curator_auditor_id=auditor.id,
        is_support_project=False,
        is_template=False,
        is_active=True,
    )
    db.session.add(proj)
    db.session.flush()
    update_customer_curator_window(proj)

    db.session.add(ProjectMember(project_id=proj.id, user_id=executor.id, role="executor"))
    if executor2:
        db.session.add(ProjectMember(project_id=proj.id, user_id=executor2.id, role="executor"))

    stages: list[ProjectStage] = []
    for i, (title, days) in enumerate(
        (
            ("Этап 1 — Подготовка", 18),
            ("Этап 2 — Проектирование", 40),
            ("Этап 3 — Согласование и сдача", 55),
        )
    ):
        st = ProjectStage(
            project_id=proj.id,
            title=title,
            deadline=p_start + timedelta(days=days),
            responsible_id=executor.id if i % 2 == 0 else auditor.id,
            sort_order=i,
            cost=50000 + i * 25000,
        )
        db.session.add(st)
        stages.append(st)
    db.session.flush()

    db.session.add(
        ProjectCustomField(
            project_id=proj.id,
            name="Бюджет этапа",
            field_type="budget",
            visibility="auditor",
            sort_order=0,
        )
    )

    e1, e2 = executor.id, (executor2 or executor).id
    a = auditor.id
    s0, s1, s2 = stages[0].id, stages[1].id, stages[2].id
    sort = 0

    def gs() -> int:
        nonlocal sort
        sort += 10
        return sort

    # --- Этап 1: родитель + подзадачи ---
    prep = _task(
        project_id=proj.id,
        stage_id=s0,
        title="1. Подготовка исходных данных",
        auditor_id=a,
        assignee_id=e1,
        start=p_start,
        due=p_start + timedelta(days=12),
        status="in_progress",
        priority=3,
        gantt_sort=gs(),
    )
    survey = _task(
        project_id=proj.id,
        stage_id=s0,
        parent_id=prep.id,
        title="1.1 Обследование участка",
        auditor_id=a,
        assignee_id=e1,
        start=p_start,
        due=p_start + timedelta(days=5),
        status="done",
        priority=2,
        gantt_sort=gs(),
    )
    collect = _task(
        project_id=proj.id,
        stage_id=s0,
        parent_id=prep.id,
        title="1.2 Сбор схем и паспортов",
        auditor_id=a,
        assignee_id=e2,
        start=p_start + timedelta(days=5),
        due=p_start + timedelta(days=12),
        status="in_progress",
        priority=2,
        gantt_sort=gs(),
    )

    # --- Этап 2: дерево с вложенностью 3 уровня ---
    design = _task(
        project_id=proj.id,
        stage_id=s1,
        title="2. Проектирование модели",
        auditor_id=a,
        assignee_id=e1,
        start=p_start + timedelta(days=12),
        due=p_start + timedelta(days=38),
        status="todo",
        priority=3,
        gantt_sort=gs(),
    )
    topo = _task(
        project_id=proj.id,
        stage_id=s1,
        parent_id=design.id,
        title="2.1 Построение топологии",
        auditor_id=a,
        assignee_id=e1,
        start=p_start + timedelta(days=12),
        due=p_start + timedelta(days=20),
        status="todo",
        priority=2,
        gantt_sort=gs(),
    )
    hydro = _task(
        project_id=proj.id,
        stage_id=s1,
        parent_id=design.id,
        title="2.2 Гидравлический расчёт",
        auditor_id=a,
        assignee_id=e1,
        start=p_start + timedelta(days=20),
        due=p_start + timedelta(days=32),
        status="todo",
        priority=3,
        gantt_sort=gs(),
    )
    nodes_a = _task(
        project_id=proj.id,
        stage_id=s1,
        parent_id=hydro.id,
        title="2.2.1 Узлы 1–20",
        auditor_id=a,
        assignee_id=e1,
        start=p_start + timedelta(days=20),
        due=p_start + timedelta(days=26),
        status="todo",
        priority=2,
        gantt_sort=gs(),
    )
    nodes_b = _task(
        project_id=proj.id,
        stage_id=s1,
        parent_id=hydro.id,
        title="2.2.2 Узлы 21–40",
        auditor_id=a,
        assignee_id=e2,
        start=p_start + timedelta(days=26),
        due=p_start + timedelta(days=32),
        status="todo",
        priority=2,
        gantt_sort=gs(),
    )
    drawings = _task(
        project_id=proj.id,
        stage_id=s1,
        parent_id=design.id,
        title="2.3 Выпуск чертежей",
        auditor_id=a,
        assignee_id=e2,
        start=p_start + timedelta(days=32),
        due=p_start + timedelta(days=38),
        status="todo",
        priority=2,
        gantt_sort=gs(),
    )

    # --- Этап 3 ---
    delivery = _task(
        project_id=proj.id,
        stage_id=s2,
        title="3. Согласование и сдача",
        auditor_id=a,
        assignee_id=a,
        start=p_start + timedelta(days=38),
        due=p_end,
        status="todo",
        priority=3,
        gantt_sort=gs(),
    )
    review = _task(
        project_id=proj.id,
        stage_id=s2,
        parent_id=delivery.id,
        title="3.1 Внутренняя проверка ГИП",
        auditor_id=a,
        assignee_id=a,
        start=p_start + timedelta(days=38),
        due=p_start + timedelta(days=45),
        status="todo",
        priority=2,
        gantt_sort=gs(),
    )
    handover = _task(
        project_id=proj.id,
        stage_id=s2,
        parent_id=delivery.id,
        title="3.2 Сдача заказчику",
        auditor_id=a,
        assignee_id=e1,
        start=p_start + timedelta(days=45),
        due=p_end,
        status="todo",
        priority=3,
        gantt_sort=gs(),
    )

    # FS (blocks): только между «соседями», не parent↔child
    fs_pairs = [
        (survey, collect),  # 1.1 → 1.2
        (collect, topo),  # подготовка → топология
        (topo, hydro),  # 2.1 → 2.2
        (nodes_a, nodes_b),  # 2.2.1 → 2.2.2
        (hydro, drawings),  # 2.2 → 2.3
        (drawings, review),  # чертежи → проверка
        (review, handover),  # 3.1 → 3.2
    ]
    for fr, to in fs_pairs:
        db.session.add(ProjectTaskLink(from_task_id=fr.id, to_task_id=to.id, link_type="blocks"))

    # related: параллельная связь для проверки другого цвета стрелки
    db.session.add(ProjectTaskLink(from_task_id=survey.id, to_task_id=topo.id, link_type="related"))

    if executor2:
        db.session.add(ProjectTaskCollaborator(task_id=hydro.id, user_id=executor2.id))

    db.session.flush()
    # Выходные/праздники + окна родителя (подзадачи не выходят за родителя)
    reschedule_project_tasks_to_workdays(proj)
    db.session.commit()
    return proj


def main() -> None:
    app = create_app()
    with app.app_context():
        removed = wipe_non_support()
        proj = seed_demo()
        tasks = ProjectTask.query.filter_by(project_id=proj.id).count()
        links = ProjectTaskLink.query.join(
            ProjectTask, ProjectTaskLink.from_task_id == ProjectTask.id
        ).filter(ProjectTask.project_id == proj.id).count()
        support = Project.query.filter_by(is_support_project=True).count()
        print(f"Removed non-support projects: {removed}")
        print(f"Support projects kept: {support}")
        print(f"Demo project id={proj.id} name={proj.name!r}")
        print(f"Tasks={tasks} links={links}")
        print(f"skip_weekends={proj.skip_weekends} skip_holidays={proj.skip_public_holidays}")
        print(f"Gantt: /projects/{proj.id}/gantt")


if __name__ == "__main__":
    main()
