from datetime import datetime, timedelta, timezone

from servicesystem.config import Config


def _working_hours_delta(hours: int, start: datetime | None = None) -> datetime:
    """Approximate working hours deadline (Mon-Fri 9-18)."""
    if start is None:
        start = datetime.now(timezone.utc)
    current = start
    remaining = hours
    while remaining > 0:
        current += timedelta(hours=1)
        if current.weekday() < 5 and 9 <= current.hour < 18:
            remaining -= 1
    return current


def _working_days_delta(days: int, start: datetime | None = None) -> datetime:
    if start is None:
        start = datetime.now(timezone.utc)
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def compute_deadlines(priority: int, created_at: datetime | None = None):
    cfg = Config.SLA_PRIORITIES.get(priority, Config.SLA_PRIORITIES[2])
    reaction = _working_hours_delta(cfg["reaction_hours"], created_at)
    if "resolution_hours" in cfg:
        resolution = _working_hours_delta(cfg["resolution_hours"], created_at)
    else:
        resolution = _working_days_delta(cfg["resolution_days"], created_at)
    return reaction, resolution


def start_timer1(ticket):
    now = datetime.now(timezone.utc)
    if ticket.timer1_started_at and not ticket.timer1_stopped_at:
        return
    ticket.timer1_started_at = now
    ticket.timer1_stopped_at = None


def stop_timer1(ticket):
    now = datetime.now(timezone.utc)
    if ticket.timer1_started_at and not ticket.timer1_stopped_at:
        elapsed = int((now - ticket.timer1_started_at).total_seconds())
        ticket.timer1_total_seconds = (ticket.timer1_total_seconds or 0) + elapsed
        ticket.timer1_stopped_at = now


def start_timer2(ticket):
    now = datetime.now(timezone.utc)
    if ticket.timer2_started_at and not ticket.timer2_stopped_at:
        return
    ticket.timer2_started_at = now
    ticket.timer2_stopped_at = None


def stop_timer2(ticket):
    now = datetime.now(timezone.utc)
    if ticket.timer2_started_at and not ticket.timer2_stopped_at:
        elapsed = int((now - ticket.timer2_started_at).total_seconds())
        ticket.timer2_total_seconds = (ticket.timer2_total_seconds or 0) + elapsed
        ticket.timer2_stopped_at = now


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} ч")
    if m:
        parts.append(f"{m} мин")
    if not parts:
        parts.append(f"{s} сек")
    return " ".join(parts)


def sla_status(deadline: datetime | None) -> str:
    if not deadline:
        return "unknown"
    now = datetime.now(timezone.utc)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    diff = (deadline - now).total_seconds()
    if diff < 0:
        return "overdue"
    if diff < 3600 * 4:
        return "warning"
    return "ok"


def priority_label(priority: int) -> str:
    cfg = Config.SLA_PRIORITIES.get(priority, Config.SLA_PRIORITIES[2])
    return cfg["name"]


def format_deadline(dt: datetime | None) -> str:
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%d.%m.%Y %H:%M")


def format_priority_snapshot(value: str | None) -> str:
    """Format stored priority|reaction|resolution snapshot for history display."""
    if not value:
        return "—"
    parts = value.split("|", 2)
    if len(parts) < 3:
        return value
    try:
        prio = int(parts[0])
    except ValueError:
        return value
    name = priority_label(prio)
    reaction = format_deadline(datetime.fromisoformat(parts[1])) if parts[1] else "—"
    resolution = format_deadline(datetime.fromisoformat(parts[2])) if parts[2] else "—"
    return f"{name} — реакция до {reaction}, устранение до {resolution}"


def sla_resolution_label(priority: int) -> str:
    cfg = Config.SLA_PRIORITIES.get(priority, Config.SLA_PRIORITIES[2])
    if "resolution_hours" in cfg:
        return f"{cfg['resolution_hours']} раб. ч"
    return f"{cfg['resolution_days']} раб. дн"
