import os
import uuid

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from servicesystem.decorators import upload_access_required
from servicesystem.extensions import db
from servicesystem.models import TicketAttachment, TicketResponseFile, UploadSession
from servicesystem.services.audit import ensure_upload_dir, unique_filename

bp = Blueprint("uploads", __name__, url_prefix="/uploads")


@bp.route("/init", methods=["POST"])
@login_required
@upload_access_required
def init_upload():
    data = request.get_json(force=True)
    original_name = data.get("filename", "file")
    total_size = int(data.get("total_size", 0))
    context = data.get("context", "ticket")
    stored = unique_filename(original_name)
    subdir = "tickets" if context == "ticket" else "responses"
    ensure_upload_dir(current_app.config["UPLOAD_FOLDER"], subdir)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir, stored)
    open(path, "wb").close()

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
    if not sess or sess.user_id != current_user.id:
        return jsonify({"error": "invalid"}), 400
    return jsonify({"received": sess.received_bytes, "total": sess.total_size, "completed": sess.completed})


@bp.route("/chunk/<session_id>", methods=["POST"])
@login_required
def upload_chunk(session_id):
    sess = db.session.get(UploadSession, session_id)
    if not sess or sess.user_id != current_user.id:
        return jsonify({"error": "invalid session"}), 400
    chunk = request.get_data()
    offset = int(request.headers.get("X-Offset", sess.received_bytes))
    subdir = "tickets" if sess.context == "ticket" else "responses"
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir, sess.stored_name)
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(chunk)
    sess.received_bytes = offset + len(chunk)
    if sess.received_bytes >= sess.total_size:
        sess.completed = True
    db.session.commit()
    return jsonify({"received": sess.received_bytes, "completed": sess.completed})


@bp.route("/finalize/<session_id>", methods=["POST"])
@login_required
def finalize_upload(session_id):
    sess = db.session.get(UploadSession, session_id)
    if not sess or not sess.completed:
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
