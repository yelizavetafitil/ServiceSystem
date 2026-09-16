import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from servicesystem.decorators import upload_access_required
from servicesystem.extensions import csrf, db
from servicesystem.models import TicketAttachment, TicketResponseFile, UploadSession
from servicesystem.services.audit import unique_filename
from servicesystem.services.files import validate_upload
from servicesystem.services.storage import get_storage

bp = Blueprint("uploads", __name__, url_prefix="/uploads")


def _session_expired(sess: UploadSession) -> bool:
    ttl = current_app.config.get("UPLOAD_SESSION_TTL_MINUTES", 5)
    if not sess.updated_at:
        return False
    updated = sess.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated > timedelta(minutes=ttl)


def _validate_upload_session(sess: UploadSession | None):
    if not sess or sess.user_id != current_user.id:
        return jsonify({"error": "invalid session"}), 400
    if _session_expired(sess):
        return jsonify({"error": "session_expired", "hint": "Resume window is 5 minutes (TZ 5.2.2)"}), 410
    return None


@bp.route("/init", methods=["POST"])
@login_required
@upload_access_required
def init_upload():
    data = request.get_json(force=True)
    original_name = data.get("filename", "file")
    total_size = int(data.get("total_size", 0))
    context = data.get("context", "ticket")
    err = validate_upload(original_name, total_size)
    if err:
        return jsonify({"error": err}), 400
    stored = unique_filename(original_name)
    subdir = "tickets" if context == "ticket" else "responses"
    rel = f"{subdir}/{stored}"
    storage = get_storage()
    storage.ensure_dir(subdir)
    storage.write(rel, b"", offset=0)

    session_id = uuid.uuid4().hex
    sess = UploadSession(
        id=session_id,
        user_id=current_user.id,
        original_name=original_name,
        stored_name=stored,
        total_size=total_size,
        mime_type=data.get("mime_type"),
        context=context,
    )
    db.session.add(sess)
    db.session.commit()
    return jsonify({"session_id": session_id, "chunk_size": current_app.config["CHUNK_SIZE"]})


@bp.route("/status/<session_id>")
@login_required
def upload_status(session_id):
    sess = db.session.get(UploadSession, session_id)
    err = _validate_upload_session(sess)
    if err:
        return err
    return jsonify({"received": sess.received_bytes, "total": sess.total_size, "completed": sess.completed})


@bp.route("/chunk/<session_id>", methods=["POST"])
@login_required
@csrf.exempt
def upload_chunk(session_id):
    sess = db.session.get(UploadSession, session_id)
    err = _validate_upload_session(sess)
    if err:
        return err
    chunk = request.get_data()
    offset = int(request.headers.get("X-Offset", sess.received_bytes))
    subdir = "tickets" if sess.context == "ticket" else "responses"
    rel = f"{subdir}/{sess.stored_name}"

    storage = get_storage()
    storage.write(rel, chunk, offset=offset)
    sess.received_bytes = offset + len(chunk)
    if sess.received_bytes >= sess.total_size:
        sess.completed = True
    db.session.commit()
    return jsonify({"received": sess.received_bytes, "completed": sess.completed})


@bp.route("/finalize/<session_id>", methods=["POST"])
@login_required
def finalize_upload(session_id):
    sess = db.session.get(UploadSession, session_id)
    err = _validate_upload_session(sess)
    if err:
        return err
    if not sess.completed:
        return jsonify({"error": "not complete"}), 400
    data = request.get_json(force=True) or {}
    ticket_id = data.get("ticket_id")
    if sess.context == "ticket":
        att = TicketAttachment(
            ticket_id=ticket_id,
            original_name=sess.original_name,
            stored_name=sess.stored_name,
            mime_type=sess.mime_type,
            size_bytes=sess.received_bytes,
        )
        db.session.add(att)
        db.session.flush()
        result = {"attachment_id": att.id}
    else:
        rf = TicketResponseFile(
            ticket_id=ticket_id,
            original_name=sess.original_name,
            stored_name=sess.stored_name,
            mime_type=sess.mime_type,
            size_bytes=sess.received_bytes,
            uploaded_by_id=current_user.id,
        )
        db.session.add(rf)
        db.session.flush()
        result = {"file_id": rf.id}
    db.session.commit()
    return jsonify(result)
