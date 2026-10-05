"""Upload file validation per TZ 3.4."""
import os

from flask import current_app


def allowed_filename(filename: str) -> bool:
    if not filename:
        return False
    name = filename.lower().strip()
    allowed = current_app.config.get("ALLOWED_UPLOAD_EXTENSIONS", set())
    for ext in sorted(allowed, key=len, reverse=True):
        if name.endswith(ext.lower()):
            return True
    base, ext = os.path.splitext(name)
    if ext.lstrip(".") in {e.lstrip(".") for e in allowed if not e.startswith(".")}:
        return True
    return False


def validate_upload(filename: str, total_size: int) -> str | None:
    """Return error message or None if valid."""
    max_size = current_app.config.get("MAX_CONTENT_LENGTH", 1024 * 1024 * 1024)
    if total_size <= 0:
        return "Некорректный размер файла"
    if total_size > max_size:
        return f"Файл превышает лимит {max_size // (1024 * 1024)} МБ"
    if not allowed_filename(filename):
        exts = ", ".join(sorted(current_app.config.get("ALLOWED_UPLOAD_EXTENSIONS", [])))
        return f"Недопустимый формат файла. Разрешены: {exts}"
    return None
