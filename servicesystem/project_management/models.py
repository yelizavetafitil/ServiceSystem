"""Данные: Проект → Отчётный этап → Задачи (ТЗ раздел 1)."""
from __future__ import annotations

from datetime import datetime, timezone

from servicesystem.extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


# Kanban / lifecycle (ТЗ 2.3); rejected/archived — закрытие без удаления из БД
TASK_KANBAN_COLUMNS = ("todo", "in_progress", "review", "done", "rejected", "archived")
# blocks = предшественник→последователь (FS); blocked_by — устаревший синоним (обратное направление)
TASK_LINK_TYPES = ("blocks", "blocked_by", "related")


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    planned_start = db.Column(db.Date)
    deadline = db.Column(db.Date)
    skip_weekends = db.Column(db.Boolean, default=False)  # сб/вс — не ставить задачи
    skip_public_holidays = db.Column(db.Boolean, default=False)  # госпраздники РБ (в т.ч. 7.11)
    curator_auditor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    customer_curator_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    customer_curator_active_until = db.Column(db.Date)
    is_support_project = db.Column(db.Boolean, default=False)
    is_template = db.Column(db.Boolean, default=False)
    template_source_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    contract = db.relationship("Contract", backref=db.backref("projects", lazy="dynamic"))
    curator_auditor = db.relationship("User", foreign_keys=[curator_auditor_id])
    customer_curator = db.relationship("User", foreign_keys=[customer_curator_id])
    stages = db.relationship(
        "ProjectStage",
        back_populates="project",
        lazy="dynamic",
        order_by="ProjectStage.sort_order",
    )
    tasks = db.relationship("ProjectTask", back_populates="project", lazy="dynamic")
    members = db.relationship("ProjectMember", back_populates="project", lazy="dynamic")


class ProjectMember(db.Model):
    __tablename__ = "project_members"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(32), nullable=False, default="executor")

    project = db.relationship("Project", back_populates="members")
    user = db.relationship("User")

    __table_args__ = (db.UniqueConstraint("project_id", "user_id", name="uq_project_member"),)


class ProjectStage(db.Model):
    __tablename__ = "project_stages"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    deadline = db.Column(db.Date)
    cost = db.Column(db.Numeric(14, 2))  # стоимость этапа
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    sort_order = db.Column(db.Integer, default=0)
    released_at = db.Column(db.DateTime(timezone=True))
    release_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    project = db.relationship("Project", back_populates="stages")
    responsible = db.relationship("User", foreign_keys=[responsible_id])
    tasks = db.relationship("ProjectTask", back_populates="stage", lazy="dynamic")
    attachments = db.relationship(
        "ProjectStageAttachment",
        back_populates="stage",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class ProjectTask(db.Model):
    __tablename__ = "project_tasks"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), index=True)
    stage_id = db.Column(db.Integer, db.ForeignKey("project_stages.id"), index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id"), index=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), unique=True, index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.Integer, nullable=False, default=2)
    kanban_status = db.Column(db.String(32), nullable=False, default="todo")
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    start_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    kanban_sort = db.Column(db.Integer, default=0)
    gantt_sort = db.Column(db.Integer, default=0)  # ручной порядок строк на диаграмме Ганта
    overdue_days = db.Column(db.Integer, default=0)
    is_critical_path = db.Column(db.Boolean, default=False)
    timer_running_since = db.Column(db.DateTime(timezone=True))
    time_spent_seconds = db.Column(db.Integer, default=0)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    completed_at = db.Column(db.DateTime(timezone=True))

    project = db.relationship("Project", back_populates="tasks")
    stage = db.relationship("ProjectStage", back_populates="tasks")
    parent = db.relationship("ProjectTask", remote_side="ProjectTask.id", backref="subtasks")
    ticket = db.relationship("Ticket", backref=db.backref("project_task", uselist=False))
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    collaborators = db.relationship(
        "ProjectTaskCollaborator",
        back_populates="task",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    links_out = db.relationship(
        "ProjectTaskLink",
        foreign_keys="ProjectTaskLink.from_task_id",
        back_populates="from_task",
        cascade="all, delete-orphan",
    )
    attachments = db.relationship(
        "ProjectTaskAttachment",
        back_populates="task",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    custom_values = db.relationship(
        "ProjectTaskCustomValue",
        back_populates="task",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    comments = db.relationship(
        "ProjectTaskComment",
        back_populates="task",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="ProjectTaskComment.created_at",
    )
    time_logs = db.relationship(
        "ProjectTimeLog",
        back_populates="task",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    checklist_items = db.relationship(
        "ProjectTaskChecklistItem",
        back_populates="task",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="ProjectTaskChecklistItem.sort_order, ProjectTaskChecklistItem.id",
    )


class ProjectTaskCollaborator(db.Model):
    __tablename__ = "project_task_collaborators"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    task = db.relationship("ProjectTask", back_populates="collaborators")
    user = db.relationship("User")

    __table_args__ = (db.UniqueConstraint("task_id", "user_id", name="uq_task_collaborator"),)


class ProjectTaskLink(db.Model):
    __tablename__ = "project_task_links"

    id = db.Column(db.Integer, primary_key=True)
    from_task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id"), nullable=False)
    to_task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id"), nullable=False)
    link_type = db.Column(db.String(32), nullable=False)

    from_task = db.relationship("ProjectTask", foreign_keys=[from_task_id], back_populates="links_out")
    to_task = db.relationship(
        "ProjectTask",
        foreign_keys=[to_task_id],
        backref=db.backref(
            "links_in",
            lazy="dynamic",
            foreign_keys="ProjectTaskLink.to_task_id",
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )

    __table_args__ = (
        db.UniqueConstraint("from_task_id", "to_task_id", "link_type", name="uq_task_link"),
    )


class ProjectTaskAttachment(db.Model):
    __tablename__ = "project_task_attachments"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id"), nullable=False)
    original_name = db.Column(db.String(512), nullable=False)
    stored_name = db.Column(db.String(512), nullable=False)
    mime_type = db.Column(db.String(128))
    size_bytes = db.Column(db.BigInteger, default=0)
    verified_at = db.Column(db.DateTime(timezone=True))
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    uploaded_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    task = db.relationship("ProjectTask", back_populates="attachments")
    verified_by = db.relationship("User", foreign_keys=[verified_by_id])
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_id])


class ProjectCustomField(db.Model):
    __tablename__ = "project_custom_fields"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    name = db.Column(db.String(128), nullable=False)
    field_type = db.Column(db.String(32), nullable=False, default="text")
    visibility = db.Column(db.String(32), default="all")
    options_json = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0)

    project = db.relationship("Project", backref=db.backref("custom_fields", lazy="dynamic"))


class ProjectTaskCustomValue(db.Model):
    __tablename__ = "project_task_custom_values"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id"), nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey("project_custom_fields.id"), nullable=False)
    value_text = db.Column(db.Text)

    task = db.relationship("ProjectTask", back_populates="custom_values")
    field = db.relationship("ProjectCustomField")

    __table_args__ = (db.UniqueConstraint("task_id", "field_id", name="uq_task_custom_value"),)


class ProjectTaskComment(db.Model):
    __tablename__ = "project_task_comments"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    task = db.relationship("ProjectTask", back_populates="comments")
    user = db.relationship("User")


class ProjectTimeLog(db.Model):
    __tablename__ = "project_time_logs"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    seconds = db.Column(db.Integer, default=0)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    task = db.relationship("ProjectTask", back_populates="time_logs")
    user = db.relationship("User")


class ProjectTaskChecklistItem(db.Model):
    """Чек-лист внутри карточки задачи (исполнитель ведёт сам)."""

    __tablename__ = "project_task_checklist_items"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id"), nullable=False, index=True)
    title = db.Column(db.String(512), nullable=False)
    is_done = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    task = db.relationship("ProjectTask", back_populates="checklist_items")
    created_by = db.relationship("User", foreign_keys=[created_by_id])


class ProjectStageAttachment(db.Model):
    __tablename__ = "project_stage_attachments"

    id = db.Column(db.Integer, primary_key=True)
    stage_id = db.Column(db.Integer, db.ForeignKey("project_stages.id"), nullable=False)
    original_name = db.Column(db.String(512), nullable=False)
    stored_name = db.Column(db.String(512), nullable=False)
    mime_type = db.Column(db.String(128))
    size_bytes = db.Column(db.BigInteger, default=0)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    uploaded_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    stage = db.relationship("ProjectStage", back_populates="attachments")
    uploaded_by = db.relationship("User")


class ProjectCalendarEvent(db.Model):
    """События ARM-календаря (ТЗ 3.2)."""

    __tablename__ = "project_calendar_events"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    starts_at = db.Column(db.DateTime(timezone=True))
    ends_at = db.Column(db.DateTime(timezone=True))
    title = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    task = db.relationship(
        "ProjectTask",
        backref=db.backref(
            "calendar_events",
            lazy="dynamic",
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )
    user = db.relationship("User")

    __table_args__ = (db.UniqueConstraint("task_id", "user_id", name="uq_task_user_calendar"),)


class ProjectCalendarFeed(db.Model):
    """CalDAV / внешние календари (ТЗ 3.3)."""

    __tablename__ = "project_calendar_feeds"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider = db.Column(db.String(64), default="caldav")
    feed_url = db.Column(db.String(1024))
    caldav_username = db.Column(db.String(255))
    caldav_password = db.Column(db.String(255))
    sync_enabled = db.Column(db.Boolean, default=False)
    email_reminders = db.Column(db.Boolean, default=True)
    reminder_minutes = db.Column(db.Integer, default=60)
    last_sync_at = db.Column(db.DateTime(timezone=True))
    last_sync_message = db.Column(db.String(512))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    user = db.relationship("User")
