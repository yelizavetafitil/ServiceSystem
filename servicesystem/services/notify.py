"""Email notifications (stub with logging; configure SMTP via env)."""
import logging
import smtplib
from email.mime.text import MIMEText

from flask import current_app

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    cfg = current_app.config
    if not cfg.get("MAIL_ENABLED"):
        log.info("EMAIL [%s] %s: %s", to, subject, body[:200])
        return True
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = cfg["MAIL_DEFAULT_SENDER"]
        msg["To"] = to
        with smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"]) as s:
            if cfg.get("MAIL_USERNAME"):
                s.starttls()
                s.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            s.send_message(msg)
        return True
    except Exception as exc:
        log.warning("Email send failed: %s", exc)
        return False


def notify_ticket_created(ticket, author, auditor):
    if author and author.email:
        send_email(
            author.email,
            f"Заявка {ticket.number} принята",
            f"Ваша заявка «{ticket.subject}» зарегистрирована.\nНомер: {ticket.number}\n"
            f"Реакция до: {ticket.reaction_deadline.strftime('%d.%m.%Y %H:%M') if ticket.reaction_deadline else '—'}",
        )
    if auditor and auditor.email:
        send_email(
            auditor.email,
            f"Новая заявка {ticket.number}",
            f"Поступила заявка от {author.full_name} ({author.organization.name if author.organization else ''}).\n"
            f"Тема: {ticket.subject}\nПриоритет: {ticket.priority}",
        )


def notify_ticket_resolved(ticket, author):
    if author and author.email:
        send_email(
            author.email,
            f"Ответ по заявке {ticket.number}",
            f"По вашей заявке «{ticket.subject}» опубликован официальный ответ.\n"
            f"Войдите в личный кабинет для просмотра.",
        )


def notify_submitted_for_review(ticket, auditor):
    if auditor and auditor.email:
        send_email(
            auditor.email,
            f"Заявка {ticket.number} на проверке",
            f"Исполнитель передал заявку «{ticket.subject}» на проверку.",
        )
