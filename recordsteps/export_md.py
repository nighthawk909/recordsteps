"""Markdown export: a numbered list with one annotated screenshot per step."""
from __future__ import annotations

import re
from collections.abc import Mapping

from .emphasis import plain, segments
from .model import Guide, display_title

_SPECIAL = re.compile(r"([\\`*_\[\]<>|#])")
_SPACES = re.compile(r"\s+")


def _escape(text: str) -> str:
    """Escape Markdown and keep it on one line (a newline could start a new list item)."""
    return _SPECIAL.sub(r"\\\1", _SPACES.sub(" ", text))


def _alt(text: str) -> str:
    """Image alt text: one line, no brackets, angle brackets or quotes."""
    return " ".join(re.sub(r"[\[\]<>\"]", "", text).split())


def _title_md(title: str) -> str:
    return "".join(f"**{_escape(text)}**" if bold else _escape(text) for text, bold in segments(title))


def _apps(guide: Guide) -> str:
    seen: list[str] = []
    for step in guide.steps:
        if step.app and step.app not in seen:
            seen.append(step.app)
    return ", ".join(seen)


def render_markdown(guide: Guide, images: Mapping[str, str]) -> str:
    """images maps step id -> image path relative to the Markdown file."""
    count = len(guide.steps)
    meta = [f"Recorded {guide.created[:10]}", f"{count} step{'' if count == 1 else 's'}"]
    if _apps(guide):
        meta.append(_escape(_apps(guide)))
    out = [f"# {_escape(guide.title)}", "", f"_{' · '.join(meta)}_", ""]
    for number, step in enumerate(guide.steps, start=1):
        title = display_title(step)
        out.append(f"{number}. {_title_md(title)}")
        if step.id in images:
            alt = _alt(f"Step {number}: {plain(title)}")
            path = images[step.id]
            out += ["", f"   ![{alt}]({path if ' ' not in path else f'<{path}>'})"]
        elif step.note:
            out += ["", f"   _{_escape(step.note)}_"]
        out.append("")
    return "\n".join(out)
