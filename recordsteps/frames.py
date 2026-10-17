"""Which screen frame to use for a click: the newest one from before it.

Pure logic, no Windows. Times are milliseconds on Windows' message clock (GetTickCount64), the
clock mouse clicks are stamped with. A Frame shows the screen as it was from `t_ms` (the last
change it contains) until at least `seen_ms` (the last time the capture loop looked and found
nothing newer). Using the newest frame whose content predates the click means an app that reacts
to the mouse-down never shows its *after* state.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

TICK_WRAP = 1 << 32  # GetMessageTime is 32 bits and wraps after 49.7 days


@dataclass(frozen=True)
class Frame:
    t_ms: float  # when the screen last changed before this frame was taken
    seen_ms: float  # the latest time this frame was known to still be on screen
    pixels: Any


@dataclass(frozen=True)
class Pick:
    image: Any
    age_ms: float  # how long before the click the frame's content appeared
    gap_ms: float  # how long before the click the frame was last confirmed current (0: at or after it)


def pick(frames: tuple[Frame, ...], click_ms: float, *, max_gap_ms: float, margin_ms: float = 0.0) -> Pick | None:
    """The newest frame whose content predates the click by at least margin_ms, if the capture
    loop was watching then. The margin absorbs clock-mapping error (see calibrate), which can make
    a frame look a little earlier than it was."""
    before = [f for f in frames if f.t_ms <= click_ms - margin_ms]
    if not before:
        return None
    frame = before[-1]
    gap = max(0.0, click_ms - frame.seen_ms)
    if gap > max_gap_ms:
        return None  # capture stalled around the click: what was on screen then is unknown
    return Pick(image=frame.pixels, age_ms=click_ms - frame.t_ms, gap_ms=gap)


def confirm(frames: tuple[Frame, ...], now_ms: float) -> tuple[Frame, ...]:
    """Nothing changed on screen up to now_ms: the newest frame is still current."""
    if not frames:
        return frames
    newest = frames[-1]
    return (*frames[:-1], replace(newest, seen_ms=max(newest.seen_ms, now_ms)))


def add(frames: tuple[Frame, ...], frame: Frame, *, keep_ms: float,
        max_frames: int) -> tuple[tuple[Frame, ...], tuple[Frame, ...]]:
    """Append a frame. Returns (kept, dropped): kept holds every frame that still answers a click
    made in the last keep_ms (the frame current at that horizon and all later ones), at most
    max_frames of them."""
    grown = (*frames, frame)
    horizon = frame.seen_ms - keep_ms
    start = 0
    while start < len(grown) - 1 and (grown[start + 1].t_ms <= horizon or len(grown) - start > max_frames):
        start += 1
    return grown[start:], grown[:start]


def unwrap_ms(t32: int, now_ms: int) -> int:
    """A 32-bit message time on the 64-bit tick clock, given that it is in the recent past."""
    return now_ms - ((now_ms - t32) % TICK_WRAP)


@dataclass(frozen=True)
class ClockMap:
    """Maps QueryPerformanceCounter readings onto the message clock."""

    offset_ms: float
    freq: int

    def to_ms(self, qpc: int) -> float:
        return qpc * 1000 / self.freq + self.offset_ms


def _edge_offset(read_qpc: Callable[[], int], read_tick: Callable[[], int], freq: int, max_reads: int,
                 max_bracket_ms: float) -> float:
    start = read_tick()
    last = read_qpc()
    for _ in range(max_reads):
        qpc = read_qpc()
        tick = read_tick()
        if tick != start:
            if (qpc - last) * 1000 / freq <= max_bracket_ms:
                return tick - qpc * 1000 / freq
            start = tick  # the step went by while this thread wasn't running: wait for the next one
        last = qpc
    raise RuntimeError("the tick count didn't move; can't line the clocks up")


def calibrate(read_qpc: Callable[[], int], read_tick: Callable[[], int], freq: int, *, edges: int = 3,
              max_reads: int = 2_000_000, max_bracket_ms: float = 0.5) -> ClockMap:
    """Line the two clocks up at moments the tick count steps (about every 15.6 ms): right then it
    equals the precise time. Every error here makes the offset look smaller, which makes frames
    look earlier than they were, the unsafe direction for picking a frame from before a click:
    a step seen late because this thread was paused (thrown away: the readings around it are too
    far apart), a step the kernel published late (the largest of a few steps wins), and whole-
    millisecond ticks (under 1 ms). pick()'s margin covers what is left."""
    offsets = [_edge_offset(read_qpc, read_tick, freq, max_reads, max_bracket_ms) for _ in range(edges)]
    return ClockMap(offset_ms=max(offsets), freq=freq)
