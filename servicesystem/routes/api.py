from flask import Blueprint, jsonify, request
from flask_login import login_required

from servicesystem.extensions import db
from servicesystem.models import Ticket, Tutorial, VideoTutorial

bp = Blueprint("api", __name__)


@bp.route("/tickets")
@login_required
def api_tickets():
    """REST API for future LLM integration."""
    q = Ticket.query
    status = request.args.get("status")
    if status:
        q = q.filter_by(status=status)
    limit = min(int(request.args.get("limit", 50)), 200)
    items = q.order_by(Ticket.created_at.desc()).limit(limit).all()
    return jsonify([{
        "id": t.id,
        "number": t.number,
        "status": t.status,
        "priority": t.priority,
        "subject": t.subject,
        "description_md": t.description_md,
        "response_md": t.response_text_md,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "contract_id": t.contract_id,
    } for t in items])


@bp.route("/tickets/<int:tid>")
@login_required
def api_ticket_detail(tid):
    t = db.session.get(Ticket, tid)
    if not t:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "id": t.id,
        "number": t.number,
        "status": t.status,
        "priority": t.priority,
        "subject": t.subject,
        "description_md": t.description_md,
        "response_md": t.response_text_md,
        "history": [{
            "action": h.action,
            "old_value": h.old_value,
            "new_value": h.new_value,
            "details": h.details,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        } for h in t.history.all()],
    })


@bp.route("/knowledge")
@login_required
def api_knowledge():
    """Knowledge base for RAG / LLM."""
    search = request.args.get("q", "").lower()
    tutorials = Tutorial.query.filter_by(is_published=True).all()
    if search:
        tutorials = [t for t in tutorials if search in t.title.lower() or search in (t.content_md or "").lower()]
    return jsonify([{
        "type": "tutorial",
        "id": t.id,
        "title": t.title,
        "slug": t.slug,
        "category": t.category,
        "tags": t.tags,
        "content_md": t.content_md,
    } for t in tutorials])


@bp.route("/videos")
@login_required
def api_videos():
    items = VideoTutorial.query.filter_by(is_published=True).all()
    return jsonify([{
        "type": "video",
        "id": v.id,
        "title": v.title,
        "slug": v.slug,
        "video_url": v.video_url,
        "chapters": [{
            "title": c.title,
            "start_sec": c.start_sec,
            "description": c.description,
        } for c in v.chapters.all()],
    } for v in items])
