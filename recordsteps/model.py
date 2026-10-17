"""The guide format: what a recording is, independent of how it was captured or exported.

Everything here is immutable. A recording grows by building a new Guide with one more Step
(add_step), never by changing one in place. guide.json is this model written out with
guide_to_dict; guide.schema.json documents the same shape for other tools.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

SCHEMA_VERSION = 1
ACTIONS = ("click", "double_click", "right_click")
SOURCES = ("uia", "ocr", "none")
PRIVATE_NOTE = "Private window: details skipped"
PRIVATE_ON_SCREEN_NOTE = "A private window was on screen: screenshot skipped"
PASSWORD_NOTE = "Password field: screenshot skipped"  # noqa: S105 - a message, not a secret
STEP_ID = re.compile(r"step-\d{3,6}")


class GuideFormatError(ValueError):
    """guide.json doesn't match the format this version understands."""


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def to_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]

    @staticmethod
    def from_list(values: Any) -> Rect:
        if not isinstance(values, list | tuple) or len(values) != 4 or not all(isinstance(v, int) for v in values):
            raise GuideFormatError(f"expected [x, y, w, h] integers, got {values!r}")
        return Rect(*values)


@dataclass(frozen=True)
class Target:
    """What was clicked. bbox is relative to the step's screenshot; None when unknown or unhelpful."""

    name: str = ""
    role: str = ""
    source: str = "none"  # "uia" (UI Automation), "ocr" (read off the screen) or "none"
    bbox: Rect | None = None
    is_password: bool = False


@dataclass(frozen=True)
class Timing:
    capture_ms: float = 0.0
    uia_ms: float = 0.0
    ocr_ms: float = 0.0
    total_ms: float = 0.0


@dataclass(frozen=True)
class Step:
    id: str
    action: str
    at: str
    app: str
    process: str
    window: str
    monitor: Rect
    dpi: int
    image: str  # path inside the bundle, "" when no screenshot was kept
    image_size: tuple[int, int]
    click: tuple[int, int]  # relative to the screenshot
    target: Target
    title: str  # generated; markdown-lite (only **bold** and backslash escapes)
    edited_title: str | None = None
    note: str = ""
    timing: Timing = field(default_factory=Timing)


@dataclass(frozen=True)
class Guide:
    id: str
    title: str
    created: str
    steps: tuple[Step, ...] = ()
    recorder: str = "recordsteps"
    platform: str = "windows"
    schema: int = SCHEMA_VERSION


def add_step(guide: Guide, step: Step) -> Guide:
    return replace(guide, steps=(*guide.steps, step))


def replace_step(guide: Guide, index: int, step: Step) -> Guide:
    if not 0 <= index < len(guide.steps):
        raise IndexError(f"no step at index {index}")
    steps = list(guide.steps)
    steps[index] = step
    return replace(guide, steps=tuple(steps))


def next_step_id(guide: Guide) -> str:
    return f"step-{len(guide.steps) + 1:03d}"


def display_title(step: Step) -> str:
    return step.edited_title if step.edited_title else step.title


# ------------------------------------------------------------------ dict (guide.json) conversion

def guide_to_dict(guide: Guide) -> dict[str, Any]:
    return {
        "schema": guide.schema,
        "id": guide.id,
        "title": guide.title,
        "created": guide.created,
        "recorder": guide.recorder,
        "platform": guide.platform,
        "steps": [_step_to_dict(s) for s in guide.steps],
    }


def _step_to_dict(step: Step) -> dict[str, Any]:
    t = step.target
    return {
        "id": step.id,
        "action": step.action,
        "at": step.at,
        "app": step.app,
        "process": step.process,
        "window": step.window,
        "monitor": step.monitor.to_list(),
        "dpi": step.dpi,
        "image": step.image,
        "imageSize": list(step.image_size),
        "click": list(step.click),
        "element": {"name": t.name, "role": t.role, "source": t.source,
                    "bbox": t.bbox.to_list() if t.bbox else None, "isPassword": t.is_password},
        "title": {"generated": step.title, "edited": step.edited_title},
        "note": step.note,
        "timing": {"captureMs": step.timing.capture_ms, "uiaMs": step.timing.uia_ms,
                   "ocrMs": step.timing.ocr_ms, "totalMs": step.timing.total_ms},
    }


def guide_from_dict(data: Any) -> Guide:
    try:
        if not isinstance(data, dict):
            raise GuideFormatError("guide.json must hold an object")
        if data.get("schema") != SCHEMA_VERSION:
            raise GuideFormatError(f"unsupported schema version {data.get('schema')!r}")
        steps = data["steps"]
        if not isinstance(steps, list):
            raise GuideFormatError("steps must be a list")
        return Guide(id=_str(data["id"]), title=_str(data["title"]), created=_str(data["created"]),
                     steps=tuple(_step_from_dict(s) for s in steps), recorder=_str(data.get("recorder", "")),
                     platform=_str(data.get("platform", "windows")))
    except (KeyError, TypeError) as exc:
        raise GuideFormatError(f"guide.json is missing or mistypes a field: {exc}") from exc


def _step_from_dict(d: dict[str, Any]) -> Step:
    step_id, image = _str(d["id"]), _str(d["image"])
    # The id names files and the image is read from disk: neither may point outside the bundle.
    if not STEP_ID.fullmatch(step_id):
        raise GuideFormatError(f"bad step id {step_id!r}")
    if image not in ("", f"images/{step_id}.png"):
        raise GuideFormatError(f"step {step_id} image must be images/{step_id}.png, got {image!r}")
    edited = d["title"].get("edited")
    if edited is not None and not isinstance(edited, str):
        raise GuideFormatError(f"step {step_id} edited title must be text")
    if d["action"] not in ACTIONS:
        raise GuideFormatError(f"unknown action {d['action']!r}")
    el = d["element"]
    if el["source"] not in SOURCES:
        raise GuideFormatError(f"unknown element source {el['source']!r}")
    timing = d.get("timing") or {}
    return Step(
        id=step_id, action=d["action"], at=_str(d["at"]), app=_str(d["app"]), process=_str(d["process"]),
        window=_str(d["window"]), monitor=Rect.from_list(d["monitor"]), dpi=int(d["dpi"]), image=image,
        image_size=_pair(d["imageSize"]), click=_pair(d["click"]),
        target=Target(name=_str(el["name"]), role=_str(el["role"]), source=el["source"],
                      bbox=Rect.from_list(el["bbox"]) if el.get("bbox") is not None else None,
                      is_password=bool(el.get("isPassword", False))),
        title=_str(d["title"]["generated"]), edited_title=edited, note=_str(d.get("note", "")),
        timing=Timing(capture_ms=float(timing.get("captureMs", 0)), uia_ms=float(timing.get("uiaMs", 0)),
                      ocr_ms=float(timing.get("ocrMs", 0)), total_ms=float(timing.get("totalMs", 0))),
    )


def _str(value: Any) -> str:
    if not isinstance(value, str):
        raise GuideFormatError(f"expected text, got {value!r}")
    return value


def _pair(value: Any) -> tuple[int, int]:
    if not isinstance(value, list | tuple) or len(value) != 2 or not all(isinstance(v, int) for v in value):
        raise GuideFormatError(f"expected [x, y] integers, got {value!r}")
    return int(value[0]), int(value[1])
