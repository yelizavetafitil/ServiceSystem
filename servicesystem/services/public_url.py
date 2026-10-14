"""Публичный базовый URL приложения (подписки ICS, ссылки для календарей)."""
from __future__ import annotations

from flask import current_app, has_request_context, url_for


def app_external_url(endpoint: str, **values) -> str:
    """Абсолютный URL: PUBLIC_BASE_URL + путь, иначе url_for(_external=True)."""
    path = url_for(endpoint, _external=False, **values)
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}{path}"
    if has_request_context():
        return url_for(endpoint, _external=True, **values)
    return path
