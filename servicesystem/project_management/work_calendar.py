"""Рабочий календарь проекта: выходные и государственные праздники РБ."""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from servicesystem.project_management.models import Project

# Фиксированные госпраздники РБ (месяц, день). 7 ноября — по требованию ГИП.
_BY_PUBLIC_HOLIDAYS: frozenset[tuple[int, int]] = frozenset(
    {
        (1, 1),   # Новый год
        (1, 2),   # Новый год
        (1, 7),   # Рождество (православное)
        (3, 8),   # День женщин
        (5, 1),   # Праздник труда
        (5, 9),   # День Победы
        (7, 3),   # День Независимости
        (11, 7),  # День Октябрьской революции
        (12, 25), # Рождество (католическое)
    }
)


def project_uses_work_calendar(project: Project | None) -> bool:
    if not project:
        return False
    return bool(getattr(project, "skip_weekends", False) or getattr(project, "skip_public_holidays", False))


def is_public_holiday(d: date) -> bool:
    return (d.month, d.day) in _BY_PUBLIC_HOLIDAYS


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # сб=5, вс=6


def is_non_working_day(d: date, project: Project | None) -> bool:
    if not project:
        return False
    if getattr(project, "skip_weekends", False) and is_weekend(d):
        return True
    if getattr(project, "skip_public_holidays", False) and is_public_holiday(d):
        return True
    return False


def is_working_day(d: date, project: Project | None) -> bool:
    return not is_non_working_day(d, project)


def snap_to_workday(d: date, project: Project | None) -> date:
    """Первый рабочий день в этот день или позже."""
    if not project_uses_work_calendar(project):
        return d
    guard = 0
    while is_non_working_day(d, project) and guard < 800:
        d += timedelta(days=1)
        guard += 1
    return d


def add_workday_steps(start: date, steps: int, project: Project | None) -> date:
    """Аналог start + timedelta(days=steps), считая только рабочие дни после start."""
    if steps <= 0 or not project_uses_work_calendar(project):
        return start + timedelta(days=max(0, steps))
    d = start
    added = 0
    guard = 0
    while added < steps and guard < 4000:
        d += timedelta(days=1)
        guard += 1
        if is_working_day(d, project):
            added += 1
    return d


def sub_workday_steps(end: date, steps: int, project: Project | None) -> date:
    """На `steps` рабочих дней раньше end (результат — рабочий день)."""
    if steps <= 0 or not project_uses_work_calendar(project):
        return end - timedelta(days=max(0, steps))
    d = end
    removed = 0
    guard = 0
    while removed < steps and guard < 4000:
        d -= timedelta(days=1)
        guard += 1
        if is_working_day(d, project):
            removed += 1
    return d


def workday_steps(start: date, end: date, project: Project | None) -> int:
    """Аналог (end - start).days с учётом только рабочих дней между ними."""
    if end <= start:
        return 0
    if not project_uses_work_calendar(project):
        return (end - start).days
    steps = 0
    d = start
    guard = 0
    while d < end and guard < 4000:
        d += timedelta(days=1)
        guard += 1
        if is_working_day(d, project):
            steps += 1
    return steps


def count_workdays_inclusive(start: date, end: date, project: Project | None) -> int:
    """Число рабочих дней в [start, end] включительно (трудодни)."""
    if end < start:
        return 0
    if not project_uses_work_calendar(project):
        return (end - start).days + 1
    n = 0
    d = start
    guard = 0
    while d <= end and guard < 4000:
        if is_working_day(d, project):
            n += 1
        d += timedelta(days=1)
        guard += 1
    return n
