"""Markdown → safe HTML for CMS articles (preview and published must match)."""
import bleach
import markdown as md_lib

_CMS_ALLOWED_TAGS = bleach.sanitizer.ALLOWED_TAGS.union({
    "p", "h1", "h2", "h3", "h4", "pre", "code", "ul", "ol", "li", "strong", "em",
    "br", "hr", "table", "thead", "tbody", "tr", "th", "td", "img", "blockquote",
})

_CMS_ALLOWED_ATTRS = {
    "a": ["href", "title", "rel"],
    "code": ["class"],
    "img": ["src", "alt", "title", "width", "height"],
    "th": ["rowspan", "colspan", "align"],
    "td": ["rowspan", "colspan", "align"],
    "table": ["class"],
}


def render_cms_markdown(text: str) -> str:
    if not text:
        return ""
    html = md_lib.markdown(text, extensions=["fenced_code", "tables", "nl2br"])
    return bleach.clean(html, tags=_CMS_ALLOWED_TAGS, attributes=_CMS_ALLOWED_ATTRS)
