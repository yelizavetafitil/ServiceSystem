"""CalDAV / ICS двусторонняя синхронизация (ТЗ 3.3)."""
from __future__ import annotations

import base64
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

from servicesystem.extensions import db
from servicesystem.project_management.models import ProjectCalendarEvent, ProjectCalendarFeed, ProjectTask
from servicesystem.project_management.services import build_ics_for_user, sync_calendar_events_for_task

_UID_TASK_RE = re.compile(r"project-task-(\d+)-(\d+)@servicesystem", re.I)


def _parse_ics_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    raw = raw.replace("Z", "")[:8]
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        return None


def parse_ics_events(ics_text: str) -> list[dict]:
    """Разбор VEVENT из ICS."""
    text = ics_text.replace("\r\n", "\n").replace("\r", "\n")
    chunks = re.split(r"BEGIN:VEVENT", text, flags=re.I)
    out: list[dict] = []
    for chunk in chunks[1:]:
        block = chunk.split("END:VEVENT", 1)[0]
        uid_m = re.search(r"^UID:(.+)$", block, re.M | re.I)
        ds_m = re.search(r"^DTSTART[^:]*:(.+)$", block, re.M | re.I)
        de_m = re.search(r"^DTEND[^:]*:(.+)$", block, re.M | re.I)
        if not uid_m:
            continue
        uid = uid_m.group(1).strip()
        ds_raw = ds_m.group(1).strip() if ds_m else ""
        de_raw = de_m.group(1).strip() if de_m else ""
        start_d = _parse_ics_date(ds_raw)
        end_d = _parse_ics_date(de_raw) or start_d
        if end_d and start_d and de_raw and "T" not in de_raw.upper() and end_d > start_d:
            end_d = end_d - timedelta(days=1)
        if not start_d:
            continue
        out.append({"uid": uid, "start": start_d, "end": end_d or start_d})
    return out


def _http_request(url: str, method: str = "GET", data: bytes | None = None, auth: tuple[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "ServiceSystem-Projects/1.0")
    if data:
        req.add_header("Content-Type", "text/calendar; charset=utf-8")
    if auth and auth[0]:
        token = base64.b64encode(f"{auth[0]}:{auth[1] or ''}".encode()).decode("ascii")
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read()


def _normalize_feed_url(url: str) -> str:
    u = (url or "").strip()
    if u.lower().startswith("webcal://"):
        u = "https://" + u[9:]
    return u


def pull_external_ics(feed: ProjectCalendarFeed) -> str:
    if not feed.feed_url:
        raise ValueError("no_feed_url")
    url = _normalize_feed_url(feed.feed_url)
    auth = (feed.caldav_username or "", feed.caldav_password or "") if feed.caldav_username else None
    return _http_request(url, auth=auth).decode("utf-8", errors="replace")


def apply_ics_to_tasks(ics_text: str, user_id: int) -> int:
    """Импорт: обновление start/due задач пользователя по UID."""
    updated = 0
    for ev in parse_ics_events(ics_text):
        m = _UID_TASK_RE.match(ev["uid"])
        if not m:
            continue
        task_id, ev_user = int(m.group(1)), int(m.group(2))
        if ev_user != user_id:
            continue
        task = db.session.get(ProjectTask, task_id)
        if not task:
            continue
        task.start_date = ev["start"]
        task.due_date = ev["end"]
        sync_calendar_events_for_task(task)
        updated += 1
    return updated


def _event_ics_body(ev: ProjectCalendarEvent) -> bytes:
    uid = f"project-task-{ev.task_id}-{ev.user_id}@servicesystem"
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//ServiceSystem//Projects//RU\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTART:{ev.starts_at.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTEND:{ev.ends_at.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"SUMMARY:{ev.title}\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode("utf-8")


def push_task_to_user_feeds(task: ProjectTask) -> int:
    """Экспорт одной задачи в CalDAV всех участников с включённой синхронизацией."""
    user_ids: set[int] = set()
    if task.assignee_id:
        user_ids.add(task.assignee_id)
    for c in task.collaborators:
        user_ids.add(c.user_id)
    pushed = 0
    for uid in user_ids:
        feed = ProjectCalendarFeed.query.filter_by(user_id=uid, sync_enabled=True).first()
        if not feed or not feed.feed_url:
            continue
        ev = ProjectCalendarEvent.query.filter_by(task_id=task.id, user_id=uid).first()
        if not ev or not ev.starts_at or not ev.ends_at:
            continue
        base = _normalize_feed_url(feed.feed_url).rstrip("/")
        auth = (feed.caldav_username or "", feed.caldav_password or "") if feed.caldav_username else None
        uid_str = f"project-task-{ev.task_id}-{ev.user_id}@servicesystem"
        try:
            _http_request(f"{base}/{uid_str}.ics", method="PUT", data=_event_ics_body(ev), auth=auth)
            pushed += 1
        except urllib.error.HTTPError:
            continue
    return pushed


def push_events_to_caldav(feed: ProjectCalendarFeed, user_id: int) -> int:
    """Экспорт: PUT каждого события на CalDAV-коллекцию."""
    if not feed.feed_url or not feed.sync_enabled:
        return 0
    base = _normalize_feed_url(feed.feed_url).rstrip("/")
    auth = (feed.caldav_username or "", feed.caldav_password or "") if feed.caldav_username else None
    pushed = 0
    events = ProjectCalendarEvent.query.filter_by(user_id=user_id).all()
    for ev in events:
        if not ev.starts_at or not ev.ends_at:
            continue
        uid = f"project-task-{ev.task_id}-{ev.user_id}@servicesystem"
        target = f"{base}/{uid}.ics"
        try:
            _http_request(target, method="PUT", data=_event_ics_body(ev), auth=auth)
            pushed += 1
        except urllib.error.HTTPError:
            continue
    return pushed


def try_push_task_to_caldav(task: ProjectTask) -> None:
    """Фоновый экспорт после сохранения задачи (ошибки сети не прерывают UI)."""
    try:
        push_task_to_user_feeds(task)
    except Exception:
        pass


def sync_caldav_feed(user, feed: ProjectCalendarFeed | None) -> dict:
    """Двусторонняя синхронизация: pull ICS → задачи, push события → CalDAV."""
    if not feed or not feed.sync_enabled:
        return {"ok": False, "error": "sync_disabled"}
    result = {"ok": True, "pulled": 0, "pushed": 0, "updated_tasks": 0}
    try:
        if feed.feed_url:
            ics = pull_external_ics(feed)
            result["updated_tasks"] = apply_ics_to_tasks(ics, user.id)
            result["pulled"] = 1
        result["pushed"] = push_events_to_caldav(feed, user.id)
        feed.last_sync_at = datetime.now(timezone.utc)
        msg = f"Импорт: {result['updated_tasks']} задач; экспорт: {result['pushed']} событий"
        feed.last_sync_message = msg
        result["message"] = msg
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        msg = str(exc)[:500]
        if feed:
            feed.last_sync_message = f"Ошибка: {msg}"
            db.session.commit()
        return {"ok": False, "error": msg}
    return result
