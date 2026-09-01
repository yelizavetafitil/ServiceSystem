import os
from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from servicesystem.config import Config
from servicesystem.decorators import contract_access_required, role_required, staff_required, write_access_required
from servicesystem.extensions import db
from servicesystem.models import (
    IncidentCategory,
    ObjectCategory,
    Ticket,
    TicketAttachment,
    TicketHistory,
    TicketResponseFile,
    User,
)
from servicesystem.services.audit import log_audit, log_ticket_history
from servicesystem.services.notify import notify_submitted_for_review, notify_ticket_created, notify_ticket_resolved
from servicesystem.services.sla import (
    compute_deadlines,
    format_duration,
    sla_status,
    start_timer1,
    start_timer2,
    stop_timer1,
    stop_timer2,
)

bp = Blueprint("tickets", __name__, url_prefix="/tickets")


def _next_ticket_number():
    year = datetime.now().year
    prefix = f"T-{year}-"
    last = Ticket.query.filter(Ticket.number.like(f"{prefix}%")).order_by(Ticket.id.desc()).first()
    seq = 1
    if last:
        try:
            seq = int(last.number.split("-")[-1]) + 1
        except ValueError:
            seq = Ticket.query.count() + 1
    return f"{prefix}{seq:05d}"


def _can_view(ticket: Ticket) -> bool:
    if current_user.is_admin:
        return True
    if current_user.is_auditor:
        return ticket.auditor_id == current_user.id or ticket.status == "new"
    if current_user.is_executor:
        return ticket.executor_id == current_user.id
    return ticket.author_id == current_user.id


@bp.route("/")
@login_required
def list_tickets():
    q = Ticket.query
    if current_user.is_customer:
        q = q.filter_by(author_id=current_user.id)
    elif current_user.is_auditor:
        q = q.filter((Ticket.auditor_id == current_user.id) | (Ticket.status == "new"))
    elif current_user.is_executor:
        q = q.filter_by(executor_id=current_user.id)
    tickets = q.order_by(Ticket.created_at.desc()).all()
    return render_template("tickets/list.html", tickets=tickets)


@bp.route("/staff")
@login_required
@staff_required
def staff_queue():
    q = Ticket.query
    if current_user.is_auditor:
        q = q.filter((Ticket.auditor_id == current_user.id) | (Ticket.status == "new"))
    elif current_user.is_executor:
        q = q.filter_by(executor_id=current_user.id)
    tickets = q.filter(Ticket.status.in_(["new", "in_progress", "on_review", "ready"])).order_by(Ticket.priority.desc(), Ticket.created_at).all()
    return render_template("tickets/staff_queue.html", tickets=tickets)


@bp.route("/new", methods=["GET", "POST"])
@login_required
@contract_access_required
@write_access_required
@role_required("customer")
def create():
    contract = current_user.contract
    objects = ObjectCategory.query.filter_by(is_active=True).order_by(ObjectCategory.sort_order).all()
    if request.method == "POST":
        obj_id = int(request.form["object_category_id"])
        inc_id = int(request.form["incident_category_id"])
        priority = int(request.form["priority"])
        subject = request.form["subject"][:120]
        description = request.form["description"]
        reaction, resolution = compute_deadlines(priority)
        auditor = User.query.filter_by(role="auditor", is_active=True).first()
        ticket = Ticket(
            number=_next_ticket_number(),
            contract_id=contract.id,
            author_id=current_user.id,
            auditor_id=auditor.id if auditor else None,
            object_category_id=obj_id,
            incident_category_id=inc_id,
            priority=priority,
            subject=subject,
            description_md=description,
            status="new",
            reaction_deadline=reaction,
            resolution_deadline=resolution,
        )
        start_timer1(ticket)
        db.session.add(ticket)
        db.session.flush()
        attachment_ids = request.form.get("attachment_ids", "")
        if attachment_ids:
            for aid in attachment_ids.split(","):
                aid = aid.strip()
                if aid:
                    att = db.session.get(TicketAttachment, int(aid))
                    if att and att.ticket_id is None:
                        att.ticket_id = ticket.id
        meta = (
            f"ФИО: {current_user.full_name}; Должность: {current_user.position}; "
            f"Орг: {current_user.organization.name if current_user.organization else '—'}; "
            f"Email: {current_user.email}; Тел: {current_user.phone or '—'}"
        )
        log_ticket_history(ticket.id, current_user.id, "created", details=f"priority={priority}; {meta}")
        log_audit(current_user.id, "ticket_create", "ticket", ticket.id, meta)
        auditor = db.session.get(User, ticket.auditor_id) if ticket.auditor_id else None
        notify_ticket_created(ticket, current_user, auditor)
        db.session.commit()
        flash(f"Заявка {ticket.number} создана.", "success")
        return redirect(url_for("tickets.detail", tid=ticket.id))
    return render_template("tickets/create.html", contract=contract, objects=objects)


@bp.route("/api/incidents/<int:object_id>")
@login_required
def api_incidents(object_id):
    items = IncidentCategory.query.filter_by(object_category_id=object_id, is_active=True).order_by(IncidentCategory.sort_order).all()
    return jsonify([{"id": i.id, "name": i.name} for i in items])


@bp.route("/<int:tid>")
@login_required
def detail(tid):
    ticket = db.session.get(Ticket, tid) or abort(404)
    if not _can_view(ticket):
        abort(403)
    history = ticket.history.all()
    executors = User.query.filter_by(role="executor", is_active=True).all() if current_user.is_auditor else []
    import markdown
    desc_html = markdown.markdown(ticket.description_md or "", extensions=["fenced_code"])
    resp_html = markdown.markdown(ticket.response_text_md or "", extensions=["fenced_code"]) if ticket.response_text_md else None
    return render_template(
        "tickets/detail.html",
        ticket=ticket,
        history=history,
        executors=executors,
        desc_html=desc_html,
        resp_html=resp_html,
        format_duration=format_duration,
        sla_status=sla_status,
    )


@bp.route("/<int:tid>/respond", methods=["POST"])
@login_required
@staff_required
def respond(tid):
    ticket = db.session.get(Ticket, tid) or abort(404)
    if not _can_view(ticket):
        abort(403)
    response_text = request.form.get("response_text", "")
    ticket.response_text_md = response_text

    response_file_ids = request.form.get("response_file_ids", "")
    if response_file_ids:
        for fid in response_file_ids.split(","):
            fid = fid.strip()
            if fid:
                rf = db.session.get(TicketResponseFile, int(fid))
                if rf and rf.ticket_id is None:
                    rf.ticket_id = ticket.id

    if current_user.is_executor:
        ticket.status = "on_review"
        stop_timer2(ticket)
        start_timer1(ticket)
        log_ticket_history(ticket.id, current_user.id, "submitted_for_review")
        if ticket.auditor:
            notify_submitted_for_review(ticket, ticket.auditor)
        flash("Ответ передан на проверку аудитору.", "success")

    elif current_user.is_auditor:
        action = request.form.get("auditor_action")
        status_choice = request.form.get("status_choice")
        if action == "approve" or status_choice == "ready":
            ticket.status = "resolved"
            stop_timer1(ticket)
            ticket.resolved_at = datetime.now(timezone.utc)
            log_ticket_history(ticket.id, current_user.id, "approved", details="Ответ отправлен заказчику")
            if ticket.author:
                notify_ticket_resolved(ticket, ticket.author)
            flash("Ответ утверждён и отправлен заказчику.", "success")
        elif action == "reject" or status_choice == "rejected":
            ticket.status = "rejected"
            stop_timer1(ticket)
            log_ticket_history(ticket.id, current_user.id, "rejected")
            flash("Заявка отклонена.", "warning")
        elif action == "assign":
            exec_id = int(request.form.get("executor_id", 0))
            if exec_id:
                old = ticket.executor_id
                ticket.executor_id = exec_id
                ticket.status = "in_progress"
                stop_timer1(ticket)
                start_timer2(ticket)
                log_ticket_history(ticket.id, current_user.id, "assign_executor", str(old), str(exec_id))

    db.session.commit()
    return redirect(url_for("tickets.detail", tid=tid))


@bp.route("/<int:tid>/priority", methods=["POST"])
@login_required
@role_required("auditor", "admin")
def change_priority(tid):
    ticket = db.session.get(Ticket, tid) or abort(404)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Укажите причину изменения уровня критичности.", "danger")
        return redirect(url_for("tickets.detail", tid=tid))
    new_priority = int(request.form["priority"])
    old_priority = ticket.priority
    old_reaction = ticket.reaction_deadline.isoformat() if ticket.reaction_deadline else ""
    old_resolution = ticket.resolution_deadline.isoformat() if ticket.resolution_deadline else ""
    reaction, resolution = compute_deadlines(new_priority, ticket.created_at)
    ticket.priority = new_priority
    ticket.priority_changed = True
    ticket.priority_change_reason = reason
    ticket.reaction_deadline = reaction
    ticket.resolution_deadline = resolution
    log_ticket_history(
        ticket.id,
        current_user.id,
        "priority_change",
        old_value=f"{old_priority}|{old_reaction}|{old_resolution}",
        new_value=f"{new_priority}|{reaction.isoformat()}|{resolution.isoformat()}",
        details=reason,
    )
    db.session.commit()
    flash("Приоритет изменён.", "success")
    return redirect(url_for("tickets.detail", tid=tid))


@bp.route("/<int:tid>/download/<int:aid>")
@login_required
def download_attachment(tid, aid):
    ticket = db.session.get(Ticket, tid) or abort(404)
    if not _can_view(ticket):
        abort(403)
    att = db.session.get(TicketAttachment, aid)
    if not att or att.ticket_id != tid:
        abort(404)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "tickets", att.stored_name)
    return send_file(path, as_attachment=True, download_name=att.original_name)


@bp.route("/<int:tid>/response-file/<int:fid>")
@login_required
def download_response_file(tid, fid):
    ticket = db.session.get(Ticket, tid) or abort(404)
    if not _can_view(ticket):
        abort(403)
    f = db.session.get(TicketResponseFile, fid)
    if not f or f.ticket_id != tid:
        abort(404)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "responses", f.stored_name)
    return send_file(path, as_attachment=True, download_name=f.original_name)
