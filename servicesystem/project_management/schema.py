"""Схема БД модуля проектов на существующих инсталляциях (без Alembic)."""
from __future__ import annotations

from sqlalchemy import text

from servicesystem.extensions import db

# create_all не добавляет колонки в уже существующие таблицы — только IF NOT EXISTS.
PROJECT_SCHEMA_PATCHES: tuple[str, ...] = (
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS description TEXT",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS planned_start DATE",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS deadline DATE",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS skip_weekends BOOLEAN DEFAULT FALSE",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS skip_public_holidays BOOLEAN DEFAULT FALSE",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS curator_auditor_id INTEGER",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS customer_curator_id INTEGER",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS customer_curator_active_until DATE",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_support_project BOOLEAN DEFAULT FALSE",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_template BOOLEAN DEFAULT FALSE",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS template_source_id INTEGER",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS stage_id INTEGER",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS parent_id INTEGER",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS ticket_id INTEGER",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS start_date DATE",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS kanban_sort INTEGER DEFAULT 0",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS gantt_sort INTEGER DEFAULT 0",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS overdue_days INTEGER DEFAULT 0",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS is_critical_path BOOLEAN DEFAULT FALSE",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS timer_running_since TIMESTAMPTZ",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS time_spent_seconds INTEGER DEFAULT 0",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
    "ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS created_by_id INTEGER",
    "ALTER TABLE project_stages ADD COLUMN IF NOT EXISTS released_at TIMESTAMPTZ",
    "ALTER TABLE project_stages ADD COLUMN IF NOT EXISTS release_notes TEXT",
    "ALTER TABLE project_stages ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0",
    "ALTER TABLE project_stages ADD COLUMN IF NOT EXISTS cost NUMERIC(14, 2)",
    "ALTER TABLE project_task_attachments ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ",
    "ALTER TABLE project_task_attachments ADD COLUMN IF NOT EXISTS verified_by_id INTEGER",
    "ALTER TABLE project_task_attachments ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMPTZ DEFAULT NOW()",
    "ALTER TABLE project_task_attachments ADD COLUMN IF NOT EXISTS size_bytes BIGINT DEFAULT 0",
    "ALTER TABLE project_calendar_feeds ADD COLUMN IF NOT EXISTS email_reminders BOOLEAN DEFAULT TRUE",
    "ALTER TABLE project_calendar_feeds ADD COLUMN IF NOT EXISTS reminder_minutes INTEGER DEFAULT 60",
    "ALTER TABLE project_calendar_feeds ADD COLUMN IF NOT EXISTS caldav_username VARCHAR(255)",
    "ALTER TABLE project_calendar_feeds ADD COLUMN IF NOT EXISTS caldav_password VARCHAR(255)",
    "ALTER TABLE project_calendar_feeds ADD COLUMN IF NOT EXISTS last_sync_message VARCHAR(512)",
    "ALTER TABLE project_calendar_feeds ADD COLUMN IF NOT EXISTS last_sync_at TIMESTAMPTZ",
    "ALTER TABLE project_calendar_feeds ADD COLUMN IF NOT EXISTS sync_enabled BOOLEAN DEFAULT FALSE",
)


PROJECT_SCHEMA_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS project_task_checklist_items (
      id SERIAL PRIMARY KEY,
      task_id INTEGER NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
      title VARCHAR(512) NOT NULL,
      is_done BOOLEAN NOT NULL DEFAULT FALSE,
      sort_order INTEGER DEFAULT 0,
      created_by_id INTEGER REFERENCES users(id),
      created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_project_task_checklist_items_task_id ON project_task_checklist_items (task_id)",
)


def apply_project_schema_patches() -> None:
    for sql in PROJECT_SCHEMA_PATCHES + PROJECT_SCHEMA_DDL:
        try:
            db.session.execute(text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()
    # Старые задачи: заполнить gantt_sort по id внутри проекта (стабильный порядок создания)
    try:
        db.session.execute(
            text(
                """
                UPDATE project_tasks t
                SET gantt_sort = s.rn
                FROM (
                  SELECT id, ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY id) AS rn
                  FROM project_tasks
                ) s
                WHERE t.id = s.id
                  AND (t.gantt_sort IS NULL OR t.gantt_sort = 0)
                """
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()


def ensure_project_tables() -> None:
    import servicesystem.project_management.models  # noqa: F401

    db.create_all()
    apply_project_schema_patches()
