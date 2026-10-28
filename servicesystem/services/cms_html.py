"""Markdown → safe HTML for CMS articles (preview and published must match)."""
from __future__ import annotations

import re

import bleach
import markdown as md_lib

_CMS_ALLOWED_TAGS = bleach.sanitizer.ALLOWED_TAGS.union({
    "p", "h1", "h2", "h3", "h4", "pre", "code", "ul", "ol", "li", "strong", "em", "u", "del", "sub", "sup",
    "mark", "kbd", "label", "input",
    "br", "hr", "table", "thead", "tbody", "tr", "th", "td", "img", "blockquote", "div",
})

_CMS_ALLOWED_ATTRS = {
    "a": ["href", "title", "rel"],
    "code": ["class"],
    "img": ["src", "alt", "title", "width", "height", "align"],
    "th": ["rowspan", "colspan", "align"],
    "td": ["rowspan", "colspan", "align"],
    "table": ["class"],
    "div": ["class"],
    "ul": ["class"],
    "li": ["class"],
    "input": ["type", "disabled", "checked"],
}

_TASK_LINE = re.compile(r"^(\s*)-\s+\[([ xX])\]\s+(.*)$")
_MD_EXTENSIONS = ["fenced_code", "tables", "extra", "md_in_html"]


def _inline_md_fragment(text: str) -> str:
    """Одна строка markdown → без обёртки <p>."""
    if not (text or "").strip():
        return ""
    html = md_lib.markdown(text.strip(), extensions=["extra"]).strip()
    if html.startswith("<p>") and html.endswith("</p>"):
        return html[3:-4]
    return html


def _convert_task_lists(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _TASK_LINE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        items: list[str] = []
        while i < len(lines):
            m2 = _TASK_LINE.match(lines[i])
            if not m2:
                break
            checked = m2.group(2).lower() == "x"
            body = _inline_md_fragment(m2.group(3))
            cls = "cms-task is-done" if checked else "cms-task"
            chk = " checked disabled" if checked else " disabled"
            items.append(f'<li class="{cls}"><label><input type="checkbox"{chk}> {body}</label></li>')
            i += 1
        out.append('<ul class="cms-checklist">' + "".join(items) + "</ul>")
    return "\n".join(out)


def _preprocess_cms_markdown(text: str) -> str:
    """Нормализация до markdown: center/u, лишние <br> (ТЗ постгарантийные ошибки CMS)."""
    t = text or ""
    t = re.sub(r"<center\b[^>]*>(.*?)</center>", r'<div class="cms-center">\1</div>', t, flags=re.I | re.S)
    t = re.sub(r"(?:<br\s*/?>\s*){2,}", "<br>\n", t, flags=re.I)
    t = _convert_task_lists(t)
    t = re.sub(
        r'(<div\s+class="[^"]*cms-callout[^"]*")(?![^>]*\bmarkdown=)([^>]*)>',
        r'\1 markdown="1"\2>',
        t,
        flags=re.I,
    )
    return t


def _collapse_br_tags(html: str) -> str:
    return re.sub(r"(?:<br\s*/?>\s*){2,}", "<br>", html, flags=re.I)


def render_cms_markdown(text: str) -> str:
    if not text:
        return ""
    src = _preprocess_cms_markdown(text)
    html = md_lib.markdown(src, extensions=_MD_EXTENSIONS)
    html = _collapse_br_tags(html)
    return bleach.clean(html, tags=_CMS_ALLOWED_TAGS, attributes=_CMS_ALLOWED_ATTRS)
