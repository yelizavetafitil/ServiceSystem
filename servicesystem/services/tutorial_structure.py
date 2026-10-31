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


def next_lesson_sort(section: TutorialSection, parent_id: int | None = None) -> int:
    q = TutorialLesson.query.filter_by(section_id=section.id, parent_id=parent_id)
    last = q.order_by(TutorialLesson.sort_order.desc()).first()
    return (last.sort_order + 1) if last else 0


def is_placeholder_overview(lesson: TutorialLesson) -> bool:
    title = (lesson.title or "").strip().casefold()
    body = (lesson.content_md or "").strip()
    return title == "обзор" and not body


def section_page_slug(section: TutorialSection | int) -> str:
    sid = section.id if isinstance(section, TutorialSection) else int(section)
    return f"_section_{sid}"


def parse_section_page_slug(slug: str | None) -> int | None:
    if not slug or not slug.startswith("_section_"):
        return None
    try:
        return int(slug[len("_section_") :])
    except ValueError:
        return None


def section_visible_lessons(sec: TutorialSection) -> list[TutorialLesson]:
    rows = (
        TutorialLesson.query.filter_by(section_id=sec.id)
        .order_by(TutorialLesson.sort_order, TutorialLesson.id)
        .all()
    )
    return [les for les in rows if not is_placeholder_overview(les)]


def tutorial_reading_sequence(tutorial: Tutorial) -> list[tuple[str, TutorialSection | TutorialLesson]]:
    """Порядок чтения: страница раздела, затем подразделы."""
    out: list[tuple[str, TutorialSection | TutorialLesson]] = []
    for sec in tutorial.sections.order_by(TutorialSection.sort_order, TutorialSection.id):
        out.append(("section", sec))
        visible = section_visible_lessons(sec)
        out.extend(("lesson", les) for les in flatten_lesson_tree(build_lesson_tree(visible)))
    return out


def build_lesson_tree(lessons: list[TutorialLesson]) -> list[tuple[TutorialLesson, list]]:
    ids = {les.id for les in lessons}
    by_parent: dict[int | None, list[TutorialLesson]] = {}
    for les in lessons:
        parent_id = les.parent_id if les.parent_id in ids else None
        by_parent.setdefault(parent_id, []).append(les)

    def walk(parent_id: int | None) -> list[tuple[TutorialLesson, list]]:
        nodes = by_parent.get(parent_id) or []
        return [(les, walk(les.id)) for les in nodes]

    return walk(None)


def flatten_lesson_tree(tree: list[tuple[TutorialLesson, list]]) -> list[TutorialLesson]:
    out: list[TutorialLesson] = []
    for les, children in tree:
        out.append(les)
        out.extend(flatten_lesson_tree(children))
    return out


def flatten_sections_lessons(tutorial: Tutorial) -> list[TutorialLesson]:
    out: list[TutorialLesson] = []
    for sec in tutorial.sections.order_by(TutorialSection.sort_order, TutorialSection.id):
        rows = (
            TutorialLesson.query.filter_by(section_id=sec.id)
            .order_by(TutorialLesson.sort_order, TutorialLesson.id)
            .all()
        )
        visible = [les for les in rows if not is_placeholder_overview(les)]
        out.extend(flatten_lesson_tree(build_lesson_tree(visible)))
    return out


def section_nav_lessons(
    section_index: int,
    sec: TutorialSection,
    current_lesson_id: int | None,
    current_section_id: int | None = None,
) -> dict:
    visible = section_visible_lessons(sec)
    tree = build_lesson_tree(visible)
    items: list[dict] = []

    def walk(nodes: list[tuple[TutorialLesson, list]], prefix: str, depth: int) -> None:
        for i, (les, children) in enumerate(nodes, start=1):
            num = f"{prefix}.{i}" if prefix else f"{section_index}.{i}"
            items.append(
                {
                    "num": num,
                    "lesson": les,
                    "depth": depth,
                    "active": current_lesson_id is not None and les.id == current_lesson_id,
                }
            )
            walk(children, num, depth + 1)

    walk(tree, "", 0)
    if not items and visible:
        for i, les in enumerate(visible, start=1):
            items.append(
                {
                    "num": f"{section_index}.{i}",
                    "lesson": les,
                    "depth": 0,
                    "active": current_lesson_id is not None and les.id == current_lesson_id,
                }
            )
    section_active = current_section_id is not None and sec.id == current_section_id
    if not section_active:
        section_active = any(it["active"] for it in items)
    return {
        "num": section_index,
        "title": sec.title,
        "section_slug": section_page_slug(sec),
        "lessons": items,
        "first_lesson": visible[0] if visible else None,
        "section_active": section_active,
    }


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
        TutorialLesson.query.filter_by(section_id=lesson.section_id, parent_id=lesson.parent_id)
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
    cur_les: str | None = "Введение"
    cur_parent: str | None = None
    buf: list[str] = []

    def flush():
        nonlocal buf
        body = "\n".join(buf).strip()
        if body and cur_les:
            chunks.append((cur_sec, cur_les, cur_parent, buf[:]))
        buf = []

    has_heading = False
    for line in lines:
        m1 = re.match(r"^#\s+(.+)$", line)
        m2 = re.match(r"^##\s+(.+)$", line)
        m3 = re.match(r"^###\s+(.+)$", line)
        if m1 and not line.startswith("##"):
            has_heading = True
            flush()
            cur_sec = m1.group(1).strip() or "Раздел"
            cur_les = None
            cur_parent = None
            buf = []
        elif m2:
            has_heading = True
            flush()
            cur_les = m2.group(1).strip() or "Урок"
            cur_parent = None
            buf = []
        elif m3:
            has_heading = True
            flush()
            cur_parent = cur_les
            cur_les = m3.group(1).strip() or "Подраздел"
            buf = []
        else:
            if cur_les is None and line.strip():
                cur_les = cur_sec
            buf.append(line)
    flush()

    if not has_heading:
        chunks = [("Содержание", tutorial.title or "Материал", None, lines)]

    created = 0
    sec_map: dict[str, TutorialSection] = {}
    les_map: dict[tuple[int, str], TutorialLesson] = {}
    base_sort = next_section_sort(tutorial)

    for sec_title, les_title, parent_title, body_lines in chunks:
        body = "\n".join(body_lines).strip()
        if not body or not les_title:
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
        parent_id = None
        if parent_title:
            parent = les_map.get((sec.id, parent_title))
            if parent:
                parent_id = parent.id
        lesson = TutorialLesson(
            section_id=sec.id,
            parent_id=parent_id,
            title=(les_title or "Урок")[:512],
            slug=unique_lesson_slug(sec, les_title or "lesson"),
            content_md=body or "",
            sort_order=next_lesson_sort(sec, parent_id),
        )
        db.session.add(lesson)
        db.session.flush()
        if not parent_id:
            les_map[(sec.id, les_title)] = lesson
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
