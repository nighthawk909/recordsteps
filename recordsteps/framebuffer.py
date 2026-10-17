"""A rolling buffer of the last second of screen frames, kept only while recording.

One thread polls each monitor's frame source about ten times a second. A source hands over a frame
only when the screen changed, so a still screen costs almost nothing. For a click, frame_before()
returns the newest frame from before it (see frames.py): the step shows the screen as the person
saw it, not after the app reacted to the mouse-down.

Frames live in memory only. While a private-browsing window is visible on a monitor, that
monitor's frames are dropped instead of kept. Stopping drops every frame.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from .frames import ClockMap, Frame, Pick, add, calibrate, confirm, pick, unwrap_ms
from .model import Rect

log = logging.getLogger(__name__)
JOIN_TIMEOUT_S = 3.0
MAX_RETRY_S = 30.0
STEADY_POLLS = 50  # after this many good passes in a row, a failure starts the backoff afresh


@dataclass(frozen=True)
class Captured:
    pixels: Any  # has to_image(): a copy the caller owns
    present_qpc: int = 0  # QueryPerformanceCounter time of the newest screen update in it; 0 if unknown


class FrameSource(Protocol):
    monitor: Rect
    live: bool  # known to be reporting changes; until then, "nothing changed" proves nothing

    def poll(self) -> Captured | None: ...  # None: nothing changed since the last poll. Raises if lost.
    def snapshot(self) -> Captured: ...  # the monitor as it is now, by a slower route
    def recycle(self, pixels: Any) -> None: ...  # a dropped frame's memory, free to reuse
    def close(self) -> None: ...


@dataclass(frozen=True)
class Clocks:
    qpc: Callable[[], int]  # QueryPerformanceCounter
    tick_ms: Callable[[], int]  # GetTickCount64: the clock clicks are stamped with
    freq: int  # QueryPerformanceFrequency


@dataclass(frozen=True)
class Settings:
    interval_s: float = 0.1  # about ten looks a second
    keep_ms: float = 1000.0  # clicks up to this old still find their frame
    max_frames: int = 12  # per monitor; bounds memory when the screen never stops changing
    max_gap_ms: float = 250.0  # a frame last confirmed longer than this before the click isn't trusted
    margin_ms: float = 20.0  # a frame must predate the click by this much: one tick plus clock-mapping slack
    retry_s: float = 2.0  # first wait before reopening lost sources (doubles up to MAX_RETRY_S)
    recalibrate_s: float = 60.0
    private_check_s: float = 0.5  # how often a still screen is checked for private windows
    private_hold_s: float = 1.0  # frames stay unkept this long after a private window was last seen
    baseline_s: float = 1.0  # a monitor without frames gets a snapshot at most this often


@dataclass(frozen=True)
class Stats:
    polls: int = 0
    frames: int = 0
    private_drops: int = 0
    failures: int = 0
    calibrations: int = 0
    blind_polls: int = 0  # "nothing changed" from a source not known to be reporting


class FrameBuffer:
    """start()/stop() from any thread; frame_before() from the capture worker."""

    def __init__(self, open_sources: Callable[[], Sequence[FrameSource]], *, private_on: Callable[[Rect], bool],
                 clocks: Clocks, settings: Settings = Settings()) -> None:
        self._open_sources = open_sources
        self._private_on = private_on
        self._clocks = clocks
        self._settings = settings
        self._lock = threading.Lock()
        self._frames: dict[Rect, tuple[Frame, ...]] = {}
        self._clock: ClockMap | None = None
        self._calibrated_at = 0.0
        self._private_checked: dict[Rect, float] = {}  # capture thread only: monotonic times
        self._private_seen: dict[Rect, float] = {}
        self._baseline_at: dict[Rect, float] = {}
        self._stats = Stats()
        self._halt = threading.Event()  # each run gets its own, so a late-stopping thread stays stopped
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._halt.is_set()

    def stats(self) -> Stats:
        return self._stats

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            if self._halt.is_set():
                log.warning("the last frame buffer thread is still stopping; screenshots are taken after clicks")
            return
        self._halt = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._halt,), name="recordsteps-frames", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._halt.set()
        thread.join(JOIN_TIMEOUT_S)
        if thread.is_alive():  # kept, so start() won't run a second thread beside it
            log.error("the frame buffer thread didn't stop in %ss; it will end on its own", JOIN_TIMEOUT_S)
        else:
            self._thread = None
        self._drop_all()
        log.info("frame buffer stopped: %s", self._stats)

    def frame_before(self, monitor: Rect, t_ms: int) -> Pick | None:
        """The newest frame of the monitor from before a click stamped t_ms (32-bit message time),
        as an image the caller owns; None if the buffer has no frame it can vouch for."""
        with self._lock:  # the copy is made before the capture thread can reuse the frame's memory
            frames = self._frames.get(monitor, ())
            if not frames:
                return None
            chosen = pick(frames, unwrap_ms(t_ms, self._clocks.tick_ms()), max_gap_ms=self._settings.max_gap_ms,
                          margin_ms=self._settings.margin_ms)
            return None if chosen is None else replace(chosen, image=chosen.image.to_image())

    # ------------------------------------------------------------------ capture thread
    def _run(self, halt: threading.Event) -> None:
        sources: Sequence[FrameSource] = ()
        retry, steady = self._settings.retry_s, 0
        self._private_checked, self._private_seen, self._baseline_at = {}, {}, {}
        try:
            while not halt.is_set():
                started = time.monotonic()
                sources = sources or self._open()
                if sources and self._poll_safely(sources, halt):
                    steady += 1
                    retry = self._settings.retry_s if steady >= STEADY_POLLS else retry
                    halt.wait(max(0.0, self._settings.interval_s - (time.monotonic() - started)))
                    continue
                _close_all(sources)
                sources, steady = (), 0
                halt.wait(retry)
                retry = min(retry * 2, MAX_RETRY_S)
        finally:
            _close_all(sources)
            self._drop_all()

    def _open(self) -> Sequence[FrameSource]:
        sources: Sequence[FrameSource] = ()
        try:
            sources = tuple(self._open_sources())
            self._calibrate()
        except Exception:
            _close_all(sources)
            log.warning("can't watch the screen continuously; steps use a screenshot taken after the click",
                        exc_info=True)
            self._count(failures=1)
            return ()
        log.info("watching %d monitor(s) for screen changes", len(sources))
        return sources

    def _poll_safely(self, sources: Iterable[FrameSource], halt: threading.Event) -> bool:
        try:
            for source in sources:
                self._poll(source, halt)
            if time.monotonic() - self._calibrated_at >= self._settings.recalibrate_s:
                self._calibrate()
            return True
        except Exception:
            log.warning("screen capture was interrupted; trying again", exc_info=True)
            self._count(failures=1)
            self._drop_all()
            return False

    def _calibrate(self) -> None:
        self._clock = calibrate(self._clocks.qpc, self._clocks.tick_ms, self._clocks.freq)
        self._calibrated_at = time.monotonic()
        self._count(calibrations=1)

    def _poll(self, source: FrameSource, halt: threading.Event) -> None:
        before = self._now_ms()
        captured = source.poll()
        self._count(polls=1)
        if captured is None:
            captured = self._baseline(source)
        if captured is None:
            self._unchanged(source, halt, before)
            return
        monitor = source.monitor
        if self._private(monitor):
            self._drop_monitor(source, halt, captured.pixels)
            return
        changed = self._clock.to_ms(captured.present_qpc) if captured.present_qpc else self._now_ms()
        frame = Frame(t_ms=changed, seen_ms=before, pixels=captured.pixels)
        s = self._settings
        dropped = self._update(monitor, lambda frames: add(frames, frame, keep_ms=s.keep_ms, max_frames=s.max_frames),
                               halt)
        self._count(frames=1)
        _recycle(source, (f.pixels for f in dropped))

    def _unchanged(self, source: FrameSource, halt: threading.Event, before: float) -> None:
        """Nothing changed: the newest frame is still what's on screen. Now and then, look for a
        private window anyway (one moved onto this monitor may not change it)."""
        if self._private_due(source.monitor) and self._private(source.monitor):
            self._drop_monitor(source, halt)
        elif source.live:
            self._update(source.monitor, lambda frames: (confirm(frames, before), ()), halt)
        else:  # e.g. the display is asleep: what is on screen now is unknown, so frames age out
            self._count(blind_polls=1)

    def _baseline(self, source: FrameSource) -> Captured | None:
        """Desktop Duplication only reports changes: on a still screen it may hand over nothing at
        all. A monitor without frames gets a slower snapshot, at most every baseline_s. It has no
        change time, so it is stamped when it finished: it can only look newer than it is."""
        monitor, now = source.monitor, time.monotonic()
        if self._frames.get(monitor) or now - self._baseline_at.get(monitor, -1e9) < self._settings.baseline_s:
            return None
        self._baseline_at = {**self._baseline_at, monitor: now}
        if self._private(monitor):
            return None
        try:
            return source.snapshot()
        except Exception:
            log.warning("couldn't take a snapshot of the still screen on %s", monitor, exc_info=True)
            return None

    def _now_ms(self) -> float:
        return self._clock.to_ms(self._clocks.qpc())

    def _private_due(self, monitor: Rect) -> bool:
        return time.monotonic() - self._private_checked.get(monitor, 0.0) >= self._settings.private_check_s

    def _private(self, monitor: Rect) -> bool:
        """A private window is on the monitor now, or was moments ago: a frame taken just before it
        closed may still show it although it is gone by the time we look."""
        now = time.monotonic()
        try:
            visible = bool(self._private_on(monitor))
        except Exception:  # can't tell: treat it as private, so nothing is kept
            log.debug("private-window check failed", exc_info=True)
            visible = True
        self._private_checked = {**self._private_checked, monitor: now}
        if visible:
            self._private_seen = {**self._private_seen, monitor: now}
        return now - self._private_seen.get(monitor, -1e9) < self._settings.private_hold_s

    def _drop_monitor(self, source: FrameSource, halt: threading.Event, *extra: Any) -> None:
        dropped = self._update(source.monitor, lambda frames: ((), frames), halt)
        self._count(private_drops=1)
        _recycle(source, (*(f.pixels for f in dropped), *extra))

    def _update(self, monitor: Rect, change: Callable[[tuple[Frame, ...]], tuple[tuple[Frame, ...], tuple]],
                halt: threading.Event) -> tuple[Frame, ...]:
        with self._lock:
            if halt.is_set():  # stopped while this poll was running: keep nothing
                return ()
            kept, dropped = change(self._frames.get(monitor, ()))
            self._frames = {**self._frames, monitor: kept}
        return dropped

    def _drop_all(self) -> None:
        with self._lock:
            self._frames = {}

    def _count(self, **deltas: int) -> None:
        self._stats = replace(self._stats, **{k: getattr(self._stats, k) + v for k, v in deltas.items()})

def _recycle(source: FrameSource, pixels: Iterable[Any]) -> None:
    for item in pixels:
        source.recycle(item)


def _close_all(sources: Iterable[FrameSource]) -> None:
    for source in sources:
        try:
            source.close()
        except Exception:
            log.exception("closing a frame source failed")
