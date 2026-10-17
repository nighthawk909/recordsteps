"""Markdown-lite step titles: '**bold**' around element names, with backslash escapes.

Titles are stored this way so every exporter can render the emphasis its own way and escape
the rest for its own format (HTML, Markdown, plain text).
"""
from __future__ import annotations


def emphasize(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("*", "\\*")
    return f"**{escaped}**"


def _markers(title: str) -> list[int]:
    """Positions of unescaped '**' pairs."""
    found: list[int] = []
    i = 0
    while i < len(title):
        if title[i] == "\\" and i + 1 < len(title):
            i += 2
        elif title.startswith("**", i):
            found.append(i)
            i += 2
        else:
            i += 1
    return found


def segments(title: str) -> list[tuple[str, bool]]:
    """'Click **Save** now' -> [('Click ', False), ('Save', True), (' now', False)].
    A '**' with no partner is dropped and the text after it stays plain."""
    markers = _markers(title)
    dangling = markers[-1] if len(markers) % 2 else None
    parts: list[tuple[str, bool]] = []
    buf: list[str] = []
    bold = False
    i = 0
    while i < len(title):
        if title[i] == "\\" and i + 1 < len(title):
            buf.append(title[i + 1])
            i += 2
            continue
        if i in markers:
            if buf:
                parts.append(("".join(buf), bold))
                buf = []
            if i != dangling:
                bold = not bold
            i += 2
            continue
        buf.append(title[i])
        i += 1
    if buf:
        parts.append(("".join(buf), bold))
    return parts


def plain(title: str) -> str:
    return "".join(text for text, _ in segments(title))
