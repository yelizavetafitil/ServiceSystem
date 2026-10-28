"""Структура туториалов: разделы / уроки, slug, разбиение Markdown."""
from __future__ import annotations

import re
from unicodedata import normalize

from servicesystem.extensions import db
from servicesystem.models import Tutorial, TutorialLesson, TutorialSection


def slugify_lesson(title: str, fallback: str = "lesson") -> str:
    text = (title or "").strip().lower()
    text = normalize("NFKD", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return (text[:120] or fallback)


def unique_lesson_slug(section: TutorialSection, title: str, exclude_id: int | None = None) -> str:
    """Slug уникален в рамках всего туториала (URL /tutorials/<slug>/<lesson_slug>)."""
    base = slugify_lesson(title)
    slug = base
    n = 2
    tutorial_id = section.tutorial_id
    while True:
        q = (
            TutorialLesson.query.join(TutorialSection)
            .filter(TutorialSection.tutorial_id == tutorial_id, TutorialLesson.slug == slug)
        )
        if exclude_id:
            q = q.filter(TutorialLesson.id != exclude_id)
        if q.first() is None:
            return slug
        slug = f"{base}-{n}"[:120]
        n += 1


def next_section_sort(tutorial: Tutorial) -> int:
    last = (
        TutorialSection.query.filter_by(tutorial_id=tutorial.id)
        .order_by(TutorialSection.sort_order.desc())
        .first()
    )
    return (last.sort_order + 1) if last else 0


def next_lesson_sort(section: TutorialSection) -> int:
    last = (
        TutorialLesson.query.filter_by(section_id=section.id)
        .order_by(TutorialLesson.sort_order.desc())
        .first()
    )
    return (last.sort_order + 1) if last else 0


def swap_sort(a_order: int, b_order: int, a, b) -> None:
    a.sort_order, b.sort_order = b_order, a_order


def move_section(section: TutorialSection, direction: int) -> None:
    """direction: -1 вверх, +1 вниз."""
    siblings = (
        TutorialSection.query.filter_by(tutorial_id=section.tutorial_id)
        .order_by(TutorialSection.sort_order, TutorialSection.id)
        .all()
    )
    idx = next((i for i, s in enumerate(siblings) if s.id == section.id), None)
    if idx is None:
        return
    j = idx + direction
    if j < 0 or j >= len(siblings):
        return
    siblings[idx].sort_order, siblings[j].sort_order = siblings[j].sort_order, siblings[idx].sort_order


def move_lesson(lesson: TutorialLesson, direction: int) -> None:
    siblings = (
        TutorialLesson.query.filter_by(section_id=lesson.section_id)
        .order_by(TutorialLesson.sort_order, TutorialLesson.id)
        .all()
    )
    idx = next((i for i, s in enumerate(siblings) if s.id == lesson.id), None)
    if idx is None:
        return
    j = idx + direction
    if j < 0 or j >= len(siblings):
        return
    siblings[idx].sort_order, siblings[j].sort_order = siblings[j].sort_order, siblings[idx].sort_order


_H1 = re.compile(r"^#\s+(.+)$", re.M)
_H2 = re.compile(r"^##\s+(.+)$", re.M)


def split_markdown_into_structure(tutorial: Tutorial, markdown: str) -> int:
    """Разбить content_md по # (разделы) и ## (уроки). Возвращает число созданных уроков.

    Существующие разделы не удаляет — добавляет в конец. Если заголовков нет —
    один раздел «Содержание» и один урок со всем текстом.
    """
    text = (markdown or "").strip()
    if not text:
        return 0

    # Уже есть структура — не дублируем без очистки
    lines = text.splitlines()
    chunks: list[tuple[str, str, list[str]]] = []  # section_title, lesson_title, body lines
    cur_sec = "Содержание"
    cur_les = "Введение"
    buf: list[str] = []

    def flush():
        nonlocal buf
        body = "\n".join(buf).strip()
        if body or cur_les:
            chunks.append((cur_sec, cur_les, buf[:]))
        buf = []

    has_heading = False
    for line in lines:
        m1 = re.match(r"^#\s+(.+)$", line)
        m2 = re.match(r"^##\s+(.+)$", line)
        if m1 and not line.startswith("##"):
            has_heading = True
            flush()
            cur_sec = m1.group(1).strip() or "Раздел"
            cur_les = "Обзор"
            buf = []
        elif m2:
            has_heading = True
            flush()
            cur_les = m2.group(1).strip() or "Урок"
            buf = []
        else:
            buf.append(line)
    flush()

    if not has_heading:
        chunks = [("Содержание", tutorial.title or "Материал", lines)]

    # Схлопываем: подряд одинаковые (sec, les) — не нужно; создаём секции по смене cur_sec
    created = 0
    sec_map: dict[str, TutorialSection] = {}
    base_sort = next_section_sort(tutorial)

    for sec_title, les_title, body_lines in chunks:
        body = "\n".join(body_lines).strip()
        if not body and not les_title:
            continue
        if sec_title not in sec_map:
            sec = TutorialSection(
                tutorial_id=tutorial.id,
                title=sec_title[:512],
                sort_order=base_sort + len(sec_map),
            )
            db.session.add(sec)
            db.session.flush()
            sec_map[sec_title] = sec
        sec = sec_map[sec_title]
        lesson = TutorialLesson(
            section_id=sec.id,
            title=(les_title or "Урок")[:512],
            slug=unique_lesson_slug(sec, les_title or "lesson"),
            content_md=body or "",
            sort_order=next_lesson_sort(sec),
        )
        db.session.add(lesson)
        db.session.flush()
        created += 1
    return created


def find_lesson_in_tutorial(tutorial: Tutorial, lesson_slug: str) -> TutorialLesson | None:
    for sec in tutorial.sections.order_by(TutorialSection.sort_order, TutorialSection.id):
        les = (
            TutorialLesson.query.filter_by(section_id=sec.id, slug=lesson_slug).first()
        )
        if les:
            return les
    return None
