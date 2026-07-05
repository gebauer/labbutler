"""Template filters for rendering comment bodies."""

import re

from django import template
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()

# Markdown-style [text](/relative/path). The URL must be site-relative (leading "/"),
# so external hosts and javascript:/mailto: schemes never match and stay plain text.
_LINK_RE = re.compile(r"\[([^\]]+)\]\((/[^)\s]*)\)")


@register.filter
def linkify_comment(body):
    """Escape a comment body, turning ``[text](/path)`` references into anchors.

    System comments (e.g. "Checked in from [Request #7](/requests/7/).") use this to
    cross-link records. Only site-relative URLs become links; protocol-relative
    ``//host`` URLs are rejected and render as literal text like everything else.
    """
    parts = []
    position = 0
    for match in _LINK_RE.finditer(body):
        parts.append(conditional_escape(body[position : match.start()]))
        text, url = match.group(1), match.group(2)
        if url.startswith("//"):
            parts.append(conditional_escape(match.group(0)))
        else:
            parts.append(
                format_html('<a href="{}" class="text-teal-700 hover:underline">{}</a>', url, text)
            )
        position = match.end()
    parts.append(conditional_escape(body[position:]))
    return mark_safe("".join(parts))
