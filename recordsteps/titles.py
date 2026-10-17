"""Write step titles from what was clicked: 'Click **Save** in Excel'."""
from __future__ import annotations

import re
from collections.abc import Sequence

from .emphasis import emphasize
from .model import PRIVATE_NOTE, Step, Target

MAX_NAME = 60
_SHORTCUT = re.compile(r"\s*(?:\((?:ctrl|alt|shift|win|f\d{1,2})[^)]*\)|\t.*)$", re.IGNORECASE)
# A menu-style '&' accelerator at the start of a word ('&Save'); 'R&D' and 'Terms & Conditions' stay.
_ACCELERATOR = re.compile(r"(?<!\S)&(?=\w)")

# Click wording by UI Automation control type; {n} is the emphasized name.
_CLICK = {
    "MenuItem": "Select {n}",
    "TabItem": "Open the {n} tab",
    "Hyperlink": "Click the {n} link",
    "CheckBox": "Click the {n} checkbox",
    "RadioButton": "Choose {n}",
    "ListItem": "Select {n}",
    "TreeItem": "Select {n}",
    "DataItem": "Select {n}",
    "Edit": "Click the {n} field",
    "ComboBox": "Open the {n} list",
}
_VERB = {"click": "Click", "double_click": "Double-click", "right_click": "Right-click"}


def clean_name(name: str) -> str:
    """Tidy an accessibility name for a title: one line, no '&' accelerators, no trailing
    colon or keyboard shortcut, at most MAX_NAME characters."""
    text = _SHORTCUT.sub("", name or "")
    text = _ACCELERATOR.sub("", text).replace("&&", "&")
    text = " ".join(text.split())
    text = text.rstrip(":").strip()
    if len(text) > MAX_NAME:
        text = text[: MAX_NAME - 1].rstrip() + "…"
    return text


def describe(action: str, target: Target, window: str) -> str:
    """The title without the app: 'Click **Save**'."""
    verb = _VERB.get(action, "Click")
    if target.name:
        n = emphasize(target.name)
        if action == "click":
            return _CLICK.get(target.role, "Click {n}").format(n=n)
        return f"{verb} {n}"
    if window:
        return f"{verb} in {emphasize(clean_name(window))}"
    return f"{verb} here"


def title_steps(steps: Sequence[Step]) -> tuple[str, ...]:
    """Titles for a whole guide. The app is named on the first step and whenever it changes,
    so a run of steps in one app doesn't repeat 'in Excel' every line."""
    titles: list[str] = []
    previous_app: str | None = None
    for step in steps:
        if step.note == PRIVATE_NOTE:
            verb = _VERB.get(step.action, "Click")
            titles.append(f"{verb} in a private window")
            previous_app = None
            continue
        title = describe(step.action, step.target, step.window)
        if step.app and step.target.name and step.app != previous_app:
            title = f"{title} in {step.app}"
        titles.append(title)
        previous_app = step.app
    return tuple(titles)
