"""Cross-cutting ticket status transitions and SLA timers (TZ 3.7)."""
from datetime import datetime, timezone

from servicesystem.services.sla import format_duration, start_timer1, start_timer2, stop_timer1, stop_timer2


def _timer_snapshot(ticket) -> str:
    return (
        f"T1={format_duration(ticket.timer1_total_seconds)}; "
        f"T2={format_duration(ticket.timer2_total_seconds)}"
    )


def on_ticket_created(ticket) -> str:
    """3.7.1 «Новый»: отсчёт Таймера №1 (реакция)."""
    ticket.status = "new"
    start_timer1(ticket)
    return f"Статус «Новый». Запущен Таймер №1 (реакция). {_timer_snapshot(ticket)}"


def on_assign_executor(ticket) -> str:
    """3.7.2 «В работе»: Т1 останавливается, запускается Т2 (исполнение)."""
    ticket.status = "in_progress"
    stop_timer1(ticket)
    start_timer2(ticket)
    return f"Статус «В работе». Таймер №1 остановлен, запущен Таймер №2. {_timer_snapshot(ticket)}"


def on_submit_for_review(ticket) -> str:
    """3.7.3 «На проверке»: Т2 останавливается, снова запускается Т1."""
    ticket.status = "on_review"
    stop_timer2(ticket)
    start_timer1(ticket)
    return f"Статус «На проверке». Таймер №2 остановлен, запущен Таймер №1. {_timer_snapshot(ticket)}"


def on_mark_ready(ticket) -> str:
    """Промежуточный статус «Готов к выдаче» — фиксируем фазу согласования."""
    ticket.status = "ready"
    stop_timer1(ticket)
    return f"Статус «Готов к выдаче». Таймер №1 остановлен. {_timer_snapshot(ticket)}"


def on_resolve(ticket) -> str:
    """3.7.4 «Решено»: оба таймера остановлены, итоги фиксируются для заказчика."""
    ticket.status = "resolved"
    stop_timer1(ticket)
    stop_timer2(ticket)
    ticket.resolved_at = datetime.now(timezone.utc)
    total = (ticket.timer1_total_seconds or 0) + (ticket.timer2_total_seconds or 0)
    return (
        f"Статус «Решено». Таймер №1: {format_duration(ticket.timer1_total_seconds)}, "
        f"Таймер №2: {format_duration(ticket.timer2_total_seconds)}, "
        f"сумма: {format_duration(total)}"
    )


def on_reject(ticket) -> str:
    ticket.status = "rejected"
    stop_timer1(ticket)
    stop_timer2(ticket)
    return f"Статус «Отклонено». {_timer_snapshot(ticket)}"


def timer_total_seconds(ticket) -> int:
    return (ticket.timer1_total_seconds or 0) + (ticket.timer2_total_seconds or 0)
