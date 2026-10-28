"""Markdown → safe HTML for CMS articles (preview and published must match)."""
from __future__ import annotations

import html as html_lib
import re

import bleach
import markdown as md_lib

_CMS_ALLOWED_TAGS = bleach.sanitizer.ALLOWED_TAGS.union({
    "p", "h1", "h2", "h3", "h4", "pre", "code", "ul", "ol", "li", "strong", "em", "u", "del", "sub", "sup",
    "mark", "kbd", "label", "input", "span",
    "br", "hr", "table", "thead", "tbody", "tr", "th", "td", "img", "blockquote", "div",
})

_CMS_ALLOWED_ATTRS = {
    "a": ["href", "title", "rel"],
    "code": ["class"],
    "img": ["src", "alt", "title", "width", "height", "align", "class"],
    "th": ["rowspan", "colspan", "align"],
    "td": ["rowspan", "colspan", "align"],
    "table": ["class"],
    "div": ["class"],
    "p": ["align"],
    "ul": ["class"],
    "li": ["class"],
    "input": ["type", "disabled", "checked"],
    "span": ["data-cms-br"],
}

_TASK_LINE = re.compile(r"^(\s*)-\s+\[([ xX])\]\s+(.*)$")
_CENTER_OPEN = re.compile(r"<center\b[^>]*>", re.I)
_CENTER_CLOSE = re.compile(r"</center\s*>", re.I)
_MD_EXTENSIONS = ["fenced_code", "tables", "extra", "md_in_html"]


def _inline_md_fragment(text: str) -> str:
    if not (text or "").strip():
        return ""
    frag = md_lib.markdown(text.strip(), extensions=["extra"]).strip()
    if frag.startswith("<p>") and frag.endswith("</p>"):
        return frag[3:-4]
    return frag


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


def _deindent_center_blocks(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    in_center = False
    for line in lines:
        stripped = line.lstrip()
        if _CENTER_OPEN.search(stripped):
            in_center = True
        if in_center:
            out.append(stripped if stripped else "")
            if _CENTER_CLOSE.search(stripped):
                in_center = False
            continue
        out.append(line)
    return "\n".join(out)


def _align_div(align: str, inner: str) -> str:
    align = align.lower()
    if align not in ("left", "center", "right", "justify"):
        align = "center"
    extra = " cms-center" if align == "center" else ""
    body = (inner or "").strip()
    return f'<div class="cms-align cms-align-{align}{extra}" markdown="1">\n\n{body}\n\n</div>'


def _normalize_center_tags(text: str) -> str:
    t = html_lib.unescape(text or "")
    t = re.sub(r"<\s*center\b", "<center", t, flags=re.I)
    t = re.sub(r"</\s*center\s*>", "</center>", t, flags=re.I)
    t = _deindent_center_blocks(t)

    def _to_div(match: re.Match[str]) -> str:
        return _align_div("center", match.group(1))

    t = re.sub(r"<center\b[^>]*>(.*?)</center>", _to_div, t, flags=re.I | re.S)
    return t


def _collapse_br_in_source(text: str) -> str:
    t = re.sub(r"(?:<br\s*/?>\s*){2,}", "<br>\n", text, flags=re.I)
    t = re.sub(r"[ \t]{2,}$", "", t, flags=re.M)
    return t


def _shield_br_tags(text: str) -> str:
    return re.sub(r"<br\s*/?>", f'<span data-cms-br="1"></span>', text, flags=re.I)


def _unshield_br_tags(html: str) -> str:
    html = re.sub(r'<span\s+data-cms-br="1"\s*></span>', "<br>", html, flags=re.I)
    html = re.sub(r"<span\s+data-cms-br='1'\s*></span>", "<br>", html, flags=re.I)
    return html


def _normalize_align_in_source(text: str) -> str:
    """<p align> / <img align> → блок cms-align-*."""
    t = text
    for align in ("left", "center", "right", "justify"):
        def wrap_p(match: re.Match[str], a=align) -> str:
            return _align_div(a, match.group(2))

        t = re.sub(
            rf"<p\s+align=(['\"]){align}\1\s*>(.*?)</p>",
            wrap_p,
            t,
            flags=re.I | re.S,
        )
        img_cls = "cms-img-center" if align == "center" else f"cms-img-align-{align}"
        t = re.sub(
            rf'<img([^>]*)\salign=(["\']){align}\2([^>]*)>',
            rf'<div class="cms-align cms-align-{align}'
            + (" cms-center" if align == "center" else "")
            + rf'" markdown="1">\n\n<img\1 align="{align}" class="{img_cls}"\3>\n\n</div>',
            t,
            flags=re.I,
        )
    return t


def normalize_cms_markdown_source(text: str) -> str:
    """Нормализация Markdown перед сохранением в БД (br, center, hard-break spaces)."""
    if not text:
        return ""
    t = html_lib.unescape(text)
    t = _collapse_br_in_source(t)
    t = _normalize_center_tags(t)
    t = _normalize_align_in_source(t)
    t = re.sub(
        r'(<div\s+class="[^"]*cms-align[^"]*")(?![^>]*\bmarkdown=)([^>]*)>',
        r'\1 markdown="1"\2>',
        t,
        flags=re.I,
    )
    return t


def _preprocess_cms_markdown(text: str) -> str:
    t = normalize_cms_markdown_source(text)
    t = _shield_br_tags(t)
    t = _convert_task_lists(t)
    t = re.sub(
        r'(<div\s+class="[^"]*cms-callout[^"]*")(?![^>]*\bmarkdown=)([^>]*)>',
        r'\1 markdown="1"\2>',
        t,
        flags=re.I,
    )
    return t


def _collapse_br_tags(html: str) -> str:
    html = re.sub(r"(?:<br\s*/?>\s*){2,}", "<br>", html, flags=re.I)
    html = re.sub(r"(?:<br\s*/?>\s*)+(?=</p>)", "", html, flags=re.I)
    html = re.sub(r"<p>\s*(?:<br\s*/?>\s*)+\s*</p>", "", html, flags=re.I)
    return html


def _postprocess_html(html: str) -> str:
    html = _unshield_br_tags(html)
    html = _collapse_br_tags(html)

    def img_center(match: re.Match[str]) -> str:
        tag = match.group(0)
        if "cms-img-center" in tag:
            return tag
        return tag.replace("<img", '<img class="cms-img-center"', 1)

    html = re.sub(r"<img[^>]*\salign=(['\"])center\1[^>]*>", img_center, html, flags=re.I)
    for align in ("center", "left", "right", "justify"):
        cls = "cms-img-center" if align == "center" else f"cms-img-align-{align}"
        html = re.sub(
            rf'(<div class="cms-align cms-align-{align}[^"]*"[^>]*>[\s\S]*?<img)(?![^>]*class=)',
            rf'\1 class="{cls}"',
            html,
            flags=re.I,
        )
    return html


def _fix_center_in_code_html(html: str) -> str:
    def repl_pre(match: re.Match[str]) -> str:
        raw = html_lib.unescape(match.group(1))
        low = raw.lower()
        if "<center" not in low and "cms-center" not in low and "cms-align" not in low:
            return match.group(0)
        src = _preprocess_cms_markdown(raw)
        inner = md_lib.markdown(src, extensions=_MD_EXTENSIONS)
        inner = _postprocess_html(inner)
        cleaned = bleach.clean(inner, tags=_CMS_ALLOWED_TAGS, attributes=_CMS_ALLOWED_ATTRS)
        return cleaned if cleaned.strip() else match.group(0)

    return re.sub(
        r"<pre><code(?:\s[^>]*)?>([\s\S]*?)</code></pre>",
        repl_pre,
        html,
        flags=re.I,
    )


def render_cms_markdown(text: str) -> str:
    if not text:
        return ""
    src = _preprocess_cms_markdown(text)
    html = md_lib.markdown(src, extensions=_MD_EXTENSIONS)
    html = _postprocess_html(html)
    html = _fix_center_in_code_html(html)
    return bleach.clean(html, tags=_CMS_ALLOWED_TAGS, attributes=_CMS_ALLOWED_ATTRS)
