import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


def _database_uri() -> str:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://servicesystem:servicesystem@localhost:5432/servicesystem",
    )
    if url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg2://" + url.split("://", 1)[1]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me-in-production")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    APP_NAME = os.environ.get("APP_NAME", "Сервис ЭМСТПН")
    ORG_NAME = os.environ.get("ORG_NAME", 'РУП «Белнипиэнергопром»')

    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/app/data/uploads")
    MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
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

    FORCE_HTTPS = os.environ.get("FORCE_HTTPS", "0") == "1"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "auto")
    UPLOAD_SESSION_TTL_MINUTES = int(os.environ.get("UPLOAD_SESSION_TTL_MINUTES", "5"))
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")
    S3_BUCKET = os.environ.get("S3_BUCKET", "")
    S3_PREFIX = os.environ.get("S3_PREFIX", "servicesystem")
    S3_ENDPOINT = os.environ.get("S3_ENDPOINT")
    S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
    S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")

    # LLM/RAG service integration (TZ 4.1)
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")

    ALLOWED_UPLOAD_EXTENSIONS = frozenset({
        ".zpkg", ".zip", ".rar", ".7z", ".pdf",
        ".log", ".txt", ".png", ".jpg", ".jpeg",
    })

    SLA_PRIORITIES = {
        1: {
            "name": "Низший",
            "color": "#64748b",
            "reaction_hours": 8,
            "resolution_days": 8,
            "description": "Предложение, пожелание или простой вопрос",
            "criteria": "Работа с системой продолжается в штатном режиме. Запрос на доработку или разъяснение ошибок/документации.",
        },
        2: {
            "name": "Обычный",
            "color": "#2563eb",
            "reaction_hours": 8,
            "resolution_days": 8,
            "description": "Стандартное обращение. Единичные сбои или вопрос по корректности работы",
            "criteria": "Система в целом работает; проблемы у незначительного числа пользователей. Работа может продолжаться в штатном режиме.",
        },
        3: {
            "name": "Высокий",
            "color": "#d97706",
            "reaction_hours": 4,
            "resolution_days": 4,
            "description": "Серьёзное обращение. Часть функционала недоступна",
            "criteria": "Частичная неработоспособность; для решения задач требуются обходные пути или существенно больше времени (>2×).",
        },
        4: {
            "name": "Самый высший",
            "color": "#dc2626",
            "reaction_hours": 2,
            "resolution_hours": 12,
            "description": "Критическое обращение. Система не функционирует",
            "criteria": "Полная или частичная неработоспособность без альтернатив; восстановление из резервной копии невозможно.",
        },
    }

    HISTORY_ACTION_LABELS = {
        "created": "Создание заявки",
        "priority_change": "Изменение уровня критичности",
        "assign_executor": "Назначение исполнителя",
        "submitted_for_review": "Передано на проверку (Т2→Т1)",
        "marked_ready": "Готов к выдаче (Т1 остановлен)",
        "approved": "Решено — ответ отправлен заказчику",
        "rejected": "Заявка отклонена",
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
