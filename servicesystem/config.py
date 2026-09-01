import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql://servicesystem:servicesystem@localhost:5432/servicesystem",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    APP_NAME = os.environ.get("APP_NAME", "Сервис ЭМСТПН")
    ORG_NAME = os.environ.get("ORG_NAME", 'РУП «Белнипиэнергопром»')

    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/app/data/uploads")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "1024")) * 1024 * 1024
    CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE_MB", "8")) * 1024 * 1024

    SESSION_COOKIE_NAME = "ss_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=60)

    MAIL_ENABLED = os.environ.get("MAIL_ENABLED", "0") == "1"
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "support@belnipi.by")

    MAINTENANCE_MESSAGE = os.environ.get("MAINTENANCE_MESSAGE", "")
    MAINTENANCE_AT = os.environ.get("MAINTENANCE_AT", "")

    SLA_PRIORITIES = {
        1: {"name": "Низший", "color": "#64748b", "reaction_hours": 8, "resolution_days": 8},
        2: {"name": "Обычный", "color": "#2563eb", "reaction_hours": 8, "resolution_days": 8},
        3: {"name": "Высокий", "color": "#d97706", "reaction_hours": 4, "resolution_days": 4},
        4: {"name": "Самый высший", "color": "#dc2626", "reaction_hours": 2, "resolution_hours": 12},
    }

    CONTRACT_STATUSES = {
        "active_warranty": "Активен (Гарантия)",
        "active_post_warranty": "Активен (Постгарантийное обслуживание / SLA)",
        "suspended": "Приостановлен (Ожидание оплаты)",
        "terminated": "Расторгнут / Заблокирован",
    }

    TICKET_STATUSES = {
        "new": "Новый",
        "in_progress": "В работе",
        "on_review": "На проверке",
        "ready": "Готов к выдаче",
        "rejected": "Отклонено",
        "resolved": "Решено",
    }

    ROLES = {
        "customer": "Заказчик",
        "executor": "Исполнитель",
        "auditor": "Аудитор",
        "admin": "Администратор",
    }
