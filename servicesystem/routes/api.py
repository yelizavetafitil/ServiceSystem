"""REST API for LLM/RAG integration (TZ section 4)."""
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from flask_login import current_user

from servicesystem.extensions import db
from servicesystem.models import ContractContentAccess, Ticket, Tutorial, VideoTutorial

bp = Blueprint("api", __name__)


def _chapter_payload(c, video):
    base = video.video_url or ""
    return {
        "id": c.id,
        "title": c.title,
        "start_sec": c.start_sec,
        "start_label": f"{c.start_sec // 60}:{c.start_sec % 60:02d}",
        "description": c.description,
        "seek_hint": f"Перейти к фрагменту «{c.title}» на {c.start_sec} сек.",
        "deep_link": f"{base}?start={c.start_sec}" if base else None,
    }


def _tutorial_payload(t):
    return {
        "type": "tutorial",
        "id": t.id,
        "title": t.title,
        "slug": t.slug,
        "category": t.category,
        "tags": [x.strip() for x in (t.tags or "").split(",") if x.strip()],
        "content_format": "markdown",
        "content_md": t.content_md,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "url": f"/cabinet/tutorials/{t.slug}",
    }


def _video_payload(v):
    return {
        "type": "video",
        "id": v.id,
        "title": v.title,
        "slug": v.slug,
        "category": v.category,
        "description": v.description,
        "video_url": v.video_url,
        "duration_sec": v.duration_sec,
        "chapters": [_chapter_payload(c, v) for c in v.chapters.all()],
        "url": f"/cabinet/videos/{v.slug}",
    }


def _ticket_payload(t, include_history=False):
    is_customer = (
        current_user.is_authenticated
        and getattr(current_user, "is_customer", False)
        and not getattr(g, "llm_service", False)
    )
    status_labels = current_app.config.get(
        "CUSTOMER_TICKET_STATUSES" if is_customer else "TICKET_STATUSES", {}
    )
    data = {
        "id": t.id,
        "number": t.number,
        "status": t.status,
        "status_label": status_labels.get(t.status, t.status),
        "subject": t.subject,
        "description_md": t.description_md,
        "description_format": "markdown",
        "response_md": t.response_text_md if (not is_customer or t.status == "resolved") else None,
        "response_format": "markdown" if t.response_text_md and (not is_customer or t.status == "resolved") else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "contract_id": t.contract_id,
        "object_category": t.object_category.name if t.object_category else None,
        "incident_category": t.incident_category.name if t.incident_category else None,
        "timer_total_seconds": t.timer_total_seconds,
        "author": {
            "full_name": t.author.full_name if t.author else None,
            "organization": t.author.organization.name if t.author and t.author.organization else None,
        },
        "url": f"/tickets/{t.id}",
    }
    if not is_customer:
        data.update({
            "priority": t.priority,
            "timer1_seconds": t.timer1_total_seconds or 0,
            "timer2_seconds": t.timer2_total_seconds or 0,
            "reaction_deadline": t.reaction_deadline.isoformat() if t.reaction_deadline else None,
            "resolution_deadline": t.resolution_deadline.isoformat() if t.resolution_deadline else None,
        })
        if include_history:
            data["history"] = [{
                "action": h.action,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "details": h.details,
                "user": h.user.full_name if h.user else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            } for h in t.history.all()]
    elif include_history:
        # Заказчику — только вехи создания/закрытия, без назначения и таймеров
        data["history"] = [
            {
                "action": "created",
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "label": "Заявка создана",
            }
        ]
        if t.status == "rejected":
            rej = next((h for h in t.history.all() if h.action == "rejected"), None)
            data["history"].append({
                "action": "rejected",
                "created_at": rej.created_at.isoformat() if rej and rej.created_at else None,
                "label": "Заявка отклонена",
            })
        elif t.resolved_at:
            data["history"].append({
                "action": "closed",
                "created_at": t.resolved_at.isoformat(),
                "label": "Заявка закрыта",
                "timer_total_seconds": t.timer_total_seconds,
            })
    return data


def api_auth_required(fn):
    """Session login or LLM service API key (TZ 4.1)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key") or ""
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
        configured = current_app.config.get("LLM_API_KEY")
        if configured and key and key == configured:
            g.llm_service = True
            return fn(*args, **kwargs)
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized", "hint": "Login session or X-API-Key required"}), 401
        g.llm_service = False
        return fn(*args, **kwargs)
    return wrapper


def _ticket_query():
    if getattr(g, "llm_service", False):
        return Ticket.query
    q = Ticket.query
    if current_user.is_customer:
        q = q.filter_by(author_id=current_user.id)
    elif current_user.is_auditor:
        q = q.filter((Ticket.auditor_id == current_user.id) | (Ticket.status == "new"))
    elif current_user.is_executor:
        q = q.filter_by(executor_id=current_user.id)
    return q


def _allowed_ids(content_type):
    if getattr(g, "llm_service", False):
        return None
    if current_user.is_staff:
        return None
    if not current_user.contract_id:
        return set()
    rows = ContractContentAccess.query.filter_by(
        contract_id=current_user.contract_id, content_type=content_type
    ).all()
    return {r.content_id for r in rows}


def _filter_tutorials(items, search=None):
    allowed = _allowed_ids("tutorial")
    if allowed is not None:
        items = [t for t in items if t.id in allowed]
    if search:
        s = search.lower()
        items = [
            t for t in items
            if s in t.title.lower()
            or s in (t.content_md or "").lower()
            or s in (t.tags or "").lower()
            or s in (t.category or "").lower()
        ]
    return items


OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "ServiceSystem API",
        "description": (
            "REST API для интеграции с LLM/RAG-ассистентом (ТЗ п. 4.1). "
            "База знаний отдаёт Markdown; видео — тайм-коды с описаниями глав (п. 4.3)."
        ),
        "version": "1.0.0",
    },
    "servers": [{"url": "/api/v1"}],
    "components": {
        "securitySchemes": {
            "sessionCookie": {
                "type": "apiKey",
                "in": "cookie",
                "name": "ss_session",
                "description": "Сессия после входа в личный кабинет",
            },
            "apiKey": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "Сервисный ключ LLM (env LLM_API_KEY)",
            },
        },
        "schemas": {
            "Tutorial": {
                "type": "object",
                "properties": {
                    "content_format": {"type": "string", "enum": ["markdown"]},
                    "content_md": {"type": "string", "description": "Индексируемый текст для RAG (п. 4.2)"},
                },
            },
            "VideoChapter": {
                "type": "object",
                "properties": {
                    "start_sec": {"type": "integer"},
                    "description": {"type": "string", "description": "Описание главы для ИИ (п. 4.3)"},
                },
            },
        },
    },
    "paths": {
        "/docs": {"get": {"summary": "OpenAPI JSON", "tags": ["meta"]}},
        "/docs/ui": {"get": {"summary": "Swagger UI", "tags": ["meta"]}},
        "/tickets": {"get": {"summary": "Список заявок", "tags": ["tickets"]}},
        "/tickets/{id}": {"get": {"summary": "Заявка с историей", "tags": ["tickets"]}},
        "/knowledge": {"get": {"summary": "База знаний (Markdown)", "tags": ["knowledge"]}},
        "/knowledge/{slug}": {"get": {"summary": "Статья по slug", "tags": ["knowledge"]}},
        "/videos": {"get": {"summary": "Видео с тайм-кодами", "tags": ["videos"]}},
        "/videos/{slug}": {"get": {"summary": "Видео по slug", "tags": ["videos"]}},
    },
}


@bp.route("/docs")
def api_docs():
    return jsonify(OPENAPI_SPEC)


@bp.route("/docs/ui")
def api_docs_ui():
    return """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ServiceSystem API</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url:'/api/v1/docs',dom_id:'#swagger-ui'})</script>
</body></html>
"""


@bp.route("/tickets")
@api_auth_required
def api_tickets():
    q = _ticket_query()
    status = request.args.get("status")
    if status:
        q = q.filter_by(status=status)
    limit = min(int(request.args.get("limit", 50)), 200)
    items = q.order_by(Ticket.created_at.desc()).limit(limit).all()
    return jsonify([_ticket_payload(t) for t in items])


@bp.route("/tickets/<int:tid>")
@api_auth_required
def api_ticket_detail(tid):
    t = db.session.get(Ticket, tid)
    if not t:
        return jsonify({"error": "not found"}), 404
    if not getattr(g, "llm_service", False):
        allowed = _ticket_query().filter_by(id=tid).first()
        if not allowed and not current_user.is_admin:
            return jsonify({"error": "forbidden"}), 403
    return jsonify(_ticket_payload(t, include_history=True))


@bp.route("/knowledge")
@api_auth_required
def api_knowledge():
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    qs = Tutorial.query.filter_by(is_published=True).order_by(Tutorial.title)
    if category:
        qs = qs.filter_by(category=category)
    tutorials = _filter_tutorials(qs.all(), search or None)
    return jsonify({
        "count": len(tutorials),
        "content_format": "markdown",
        "items": [_tutorial_payload(t) for t in tutorials],
    })


@bp.route("/knowledge/<slug>")
@api_auth_required
def api_knowledge_detail(slug):
    t = Tutorial.query.filter_by(slug=slug, is_published=True).first()
    if not t:
        return jsonify({"error": "not found"}), 404
    allowed = _allowed_ids("tutorial")
    if allowed is not None and t.id not in allowed:
        return jsonify({"error": "forbidden"}), 403
    return jsonify(_tutorial_payload(t))


@bp.route("/videos")
@api_auth_required
def api_videos():
    allowed = _allowed_ids("video")
    items = VideoTutorial.query.filter_by(is_published=True).order_by(VideoTutorial.title).all()
    if allowed is not None:
        items = [v for v in items if v.id in allowed]
    return jsonify({
        "count": len(items),
        "items": [_video_payload(v) for v in items],
    })


@bp.route("/videos/<slug>")
@api_auth_required
def api_video_detail(slug):
    v = VideoTutorial.query.filter_by(slug=slug, is_published=True).first()
    if not v:
        return jsonify({"error": "not found"}), 404
    allowed = _allowed_ids("video")
    if allowed is not None and v.id not in allowed:
        return jsonify({"error": "forbidden"}), 403
    return jsonify(_video_payload(v))
