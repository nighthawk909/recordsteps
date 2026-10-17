"""Pick the element a click was meant for from what UI Automation found under the pointer.

ElementFromPoint returns the deepest element: often a text label or icon inside the button
the user actually meant. resolve() walks up a few levels to the nearest control a person
would name ("the Save button"), and borrows a label's text when that control has no name.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .model import Rect
from .titles import clean_name

LOOKUP_DEPTH = 6  # elements examined, starting with the one under the pointer
ACTIONABLE = frozenset({
    "Button", "SplitButton", "MenuItem", "TabItem", "Hyperlink", "CheckBox", "RadioButton", "ListItem",
    "TreeItem", "DataItem", "Edit", "ComboBox", "HeaderItem",
})
# Places people type: never read off the screen, the text in them may be private.
TEXT_ENTRY = frozenset({"Edit", "ComboBox", "Document"})
# Containers whose names describe a whole window or region, not the thing clicked.
NOT_A_TARGET = frozenset({"Window", "Pane", "TitleBar", "Document", "MenuBar", "ToolBar", "StatusBar", "ScrollBar"})


@dataclass(frozen=True)
class ElementInfo:
    """One UI Automation element; bbox in screen (physical) pixels."""

    name: str
    role: str
    bbox: Rect | None = None
    is_password: bool = False


@dataclass(frozen=True)
class Resolved:
    name: str = ""
    role: str = ""
    bbox: Rect | None = None
    is_password: bool = False


def resolve(chain: Sequence[ElementInfo]) -> Resolved:
    """chain[0] is the element under the pointer, then its ancestors."""
    if not chain:
        return Resolved()
    window = list(chain[:LOOKUP_DEPTH])
    hit = window[0]
    password = any(e.is_password for e in window)  # any password field near the pointer counts
    for index, element in enumerate(window):
        if element.role in ACTIONABLE:
            name = clean_name(element.name) or _label_below(window[:index])
            return Resolved(name, element.role, element.bbox or hit.bbox, password)
    for element in window:
        name = clean_name(element.name)
        if name and element.role not in NOT_A_TARGET:
            return Resolved(name, element.role, element.bbox or hit.bbox, password)
    return Resolved(is_password=password)


def _label_below(descendants: Sequence[ElementInfo]) -> str:
    """The nearest named element inside an unnamed control (e.g. the text in a button)."""
    for element in reversed(descendants):
        name = clean_name(element.name)
        if name:
            return name
    return ""
