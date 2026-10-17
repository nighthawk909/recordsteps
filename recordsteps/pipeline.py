"""One click in, one step out: screenshot, what was clicked, and a title.

Session holds the growing (immutable) Guide and is used from a single worker thread. All
Windows access goes through a Deps object, so the pipeline runs against fakes in tests.
"""
from __future__ import annotations

import logging
import ntpath
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from . import bundle
from .apps import is_private, is_remote
from .clicks import RawClick, is_double
from .frames import Pick
from .geometry import relative_point, useful_bbox
from .model import (
    PASSWORD_NOTE,
    PRIVATE_NOTE,
    PRIVATE_ON_SCREEN_NOTE,
    Guide,
    Rect,
    Step,
    Target,
    Timing,
    add_step,
    next_step_id,
    replace_step,
)
from .ocr_target import Word, nearest_text
from .targets import TEXT_ENTRY, ElementInfo, Resolved, resolve
from .titles import title_steps

log = logging.getLogger(__name__)
OCR_BOX = (480, 160)  # physical pixels read around the click when UI Automation has no name


@dataclass(frozen=True)
class WindowHit:
    pid: int
    title: str
    process_path: str


class Deps(Protocol):
    def window_at(self, x: int, y: int) -> WindowHit: ...
    def monitor_at(self, x: int, y: int) -> Rect: ...
    def dpi_at(self, x: int, y: int) -> int: ...
    def grab(self, monitor: Rect) -> QImage: ...
    def chain_at(self, x: int, y: int) -> tuple[ElementInfo, ...]: ...
    def ocr_words(self, image: QImage) -> tuple[Word, ...]: ...
    def app_name(self, process_path: str) -> str: ...
    def private_window_on(self, monitor: Rect) -> bool: ...
    def frame_before(self, monitor: Rect, t_ms: int) -> Pick | None: ...


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def retitle(guide: Guide) -> Guide:
    titles = title_steps(guide.steps)
    return replace(guide, steps=tuple(replace(s, title=t) for s, t in zip(guide.steps, titles, strict=True)))


def _ms(start: float, clock: Callable[[], float]) -> float:
    return round((clock() - start) * 1000, 1)


def _read_near(image: QImage, click: tuple[int, int], deps: Deps) -> tuple[str, Rect] | None:
    """OCR a box around the click; the nearest line of text and its box (image coordinates)."""
    w, h = min(OCR_BOX[0], image.width()), min(OCR_BOX[1], image.height())
    x0 = min(max(0, click[0] - w // 2), image.width() - w)
    y0 = min(max(0, click[1] - h // 2), image.height() - h)
    try:
        words = deps.ocr_words(image.copy(QRect(x0, y0, w, h)))
    except Exception as exc:  # OCR missing or failed: the step just goes unnamed
        log.info("OCR unavailable: %s", exc)
        return None
    hit = nearest_text(words, (click[0] - x0, click[1] - y0))
    return (hit.text, Rect(hit.x + x0, hit.y + y0, hit.w, hit.h)) if hit else None


def _screenshot(click: RawClick, monitor: Rect, deps: Deps, step_id: str) -> QImage:
    """The newest buffered frame from before the click; failing that, a screenshot taken now,
    which can already show the app's reaction to the mouse-down."""
    try:
        chosen = deps.frame_before(monitor, click.t_ms)
    except Exception as exc:  # the buffer is an improvement, not a requirement
        log.warning("%s: frame buffer failed: %s", step_id, exc)
        chosen = None
    if chosen is not None and (chosen.image.isNull() or (chosen.image.width(), chosen.image.height()) != (monitor.w,
                                                                                                      monitor.h)):
        log.warning("%s: buffered frame unusable (%sx%s)", step_id, chosen.image.width(), chosen.image.height())
        chosen = None
    if chosen is None:
        log.info("%s: no frame from before the click; screenshot taken after it", step_id)
        return deps.grab(monitor)
    log.info("%s: frame from before the click: content %.0f ms old, last confirmed %.0f ms before the click",
             step_id, chosen.age_ms, chosen.gap_ms)
    return chosen.image


def capture_step(click: RawClick, hit: WindowHit, step_id: str, deps: Deps, *, now: str,
                 clock: Callable[[], float] = time.perf_counter) -> tuple[Step, QImage | None]:
    start = clock()
    process = ntpath.basename(hit.process_path)
    monitor = deps.monitor_at(click.x, click.y)
    base = dict(id=step_id, action="right_click" if click.button == "right" else "click", at=now,
                app=deps.app_name(hit.process_path), process=process, monitor=monitor,
                dpi=deps.dpi_at(click.x, click.y), image_size=(monitor.w, monitor.h),
                click=relative_point(click.x, click.y, monitor), title="")
    if is_private(hit.title):
        return Step(**base, window="", image="", target=Target(), note=PRIVATE_NOTE,
                    timing=Timing(total_ms=_ms(start, clock))), None

    note = PRIVATE_ON_SCREEN_NOTE if deps.private_window_on(monitor) else ""
    t = clock()
    image = None if note else _screenshot(click, monitor, deps, step_id)
    capture_ms = _ms(t, clock)

    found, uia_ms = Resolved(), 0.0
    if not is_remote(process):
        t = clock()
        try:
            found = resolve(deps.chain_at(click.x, click.y))
        except Exception as exc:  # the app under the pointer didn't answer; fall back to OCR
            log.info("UI Automation failed at %s,%s: %s", click.x, click.y, exc)
        uia_ms = _ms(t, clock)
    if found.is_password:
        image, note = None, PASSWORD_NOTE  # a revealed or half-typed password must never reach disk

    name, source, bbox, ocr_ms = found.name, "uia" if found.name else "none", useful_bbox(found.bbox, monitor), 0.0
    if not name and image is not None and found.role not in TEXT_ENTRY:
        t = clock()  # read the label next to the click; never the inside of a text field
        read = _read_near(image, base["click"], deps)
        ocr_ms = _ms(t, clock)
        if read:
            name, bbox, source = read[0], read[1], "ocr"
    target = Target(name=name, role=found.role, source=source, bbox=bbox, is_password=found.is_password)
    timing = Timing(capture_ms=capture_ms, uia_ms=uia_ms, ocr_ms=ocr_ms, total_ms=_ms(start, clock))
    return Step(**base, window=hit.title, image="", target=target, note=note, timing=timing), image


class Session:
    def __init__(self, guide: Guide, deps: Deps, *, own_pid: int, bundle_dir: Path | None,
                 double_click: tuple[int, int, int] = (500, 4, 4), now: Callable[[], str] = _now,
                 on_accept: Callable[[RawClick], None] | None = None,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        self._guide = guide
        self._deps = deps
        self._own_pid = own_pid
        self._bundle_dir = Path(bundle_dir) if bundle_dir else None
        self._double = double_click
        self._now = now
        self._on_accept = on_accept
        self._clock = clock
        self._last: RawClick | None = None

    @property
    def guide(self) -> Guide:
        return self._guide

    def handle(self, click: RawClick) -> Guide | None:
        """Process one click. Returns the new guide, or None when the click is ignored."""
        hit = self._deps.window_at(click.x, click.y)
        if hit.pid == self._own_pid:
            return None  # the recording pill or another of our windows
        if self._on_accept:
            self._on_accept(click)
        max_ms, dx, dy = self._double
        if self._guide.steps and is_double(self._last, click, max_ms=max_ms, max_dx=dx, max_dy=dy):
            last = len(self._guide.steps) - 1
            self._guide = retitle(replace_step(self._guide, last, replace(self._guide.steps[last],
                                                                          action="double_click")))
            self._last = None
            self._persist()
            return self._guide
        step, image = capture_step(click, hit, next_step_id(self._guide), self._deps, now=self._now(),
                                   clock=self._clock)
        if image is not None and self._bundle_dir is not None:
            step = replace(step, image=bundle.save_image(self._bundle_dir, step.id, image))
        self._guide = retitle(add_step(self._guide, step))
        self._last = click
        self._persist()
        return self._guide

    def _persist(self) -> None:
        if self._bundle_dir is not None:
            bundle.save_guide(self._bundle_dir, self._guide)
