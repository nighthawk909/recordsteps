"""Screen frames from DXGI Desktop Duplication, for the rolling frame buffer.

Desktop Duplication hands over the desktop image only when it changed, stamped with the
QueryPerformanceCounter time of the last change, and costs nothing while the screen is still.
Like the mss screenshots, it leaves out windows marked WDA_EXCLUDEFROMCAPTURE (the recording
pill and the click flash); this was checked on Windows 11 by showing an excluded and a normal
window and reading both spots of a duplicated frame. The DXGI/Direct3D 11 wrappers come from
dxcam (MIT).

A source is created, polled and closed on one thread: the frame buffer's.
"""
from __future__ import annotations

import ctypes
import logging
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from PySide6.QtGui import QImage

from ..framebuffer import Captured, Clocks, FrameBuffer
from ..model import Rect
from . import system
from .screen import ScreenGrabber

log = logging.getLogger(__name__)
SETTLE_S = 0.006  # let the GPU finish its copy first; Map would otherwise spin-wait on a CPU core
SPARE_BUFFERS = 2  # reusing frame memory: a fresh 20 MB allocation costs more than the copy itself
SILENT_POLLS = 2  # polls in a row with the pointer moving on the monitor and nothing reported

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetTickCount64.restype = ctypes.c_ulonglong
_kernel32.QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
_kernel32.QueryPerformanceFrequency.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]


def cursor_pos() -> tuple[int, int]:
    point = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


class DuplicationLost(RuntimeError):
    """Desktop Duplication stopped (display change, secure desktop, full-screen game); reopen it."""


@dataclass(frozen=True, eq=False)
class Pixels:
    data: bytearray  # BGRA rows, `stride` bytes apart; reused once the frame is dropped
    width: int
    height: int
    stride: int

    def to_image(self) -> QImage:
        return QImage(self.data, self.width, self.height, self.stride, QImage.Format_RGB32).copy()


class DdaSource:
    """One monitor's duplication plus a CPU-readable staging texture.

    live: whether Desktop Duplication is known to be reporting. With the display asleep or off it
    reports nothing at all, not even the pointer, and "no change" then proves nothing. A source
    is live once anything is reported, and stops being live when the pointer keeps moving on its
    monitor unreported."""

    def __init__(self, monitor: Rect, context: Any, duplicator: Any, stage: Any, *,
                 cursor_pos: Callable[[], tuple[int, int]] = cursor_pos) -> None:
        self.monitor = monitor
        self.live = False
        self._cursor_pos = cursor_pos
        self._cursor: tuple[int, int] | None = None
        self._silent = 0
        self._context = context
        self._dup = duplicator
        self._stage = stage
        self._spare: list[bytearray] = []
        self._last_change = 0  # the newest change time handed out
        self._grabber: ScreenGrabber | None = None  # GDI, for snapshots of a still screen

    def poll(self) -> Captured | None:
        moved = self._pointer_moved()
        if not self._dup.update_frame():
            raise DuplicationLost(f"desktop duplication of {self.monitor} was lost")
        self._note_reporting(self._dup.updated, moved)
        if not self._dup.updated:
            return None
        try:
            if not self._dup.accumulated_frames:
                return None  # only the pointer moved; the desktop image is unchanged
            self._context.CopyResource(self._stage.texture, self._dup.texture)
            changed = self._change_time(int(self._dup.latest_frame_ticks))
        finally:
            self._dup.release_frame()
        time.sleep(SETTLE_S)
        return Captured(self._read(), changed)

    def _pointer_moved(self) -> bool:
        """Whether the pointer moved across this monitor since the last poll. Read before asking
        Desktop Duplication, so a live duplication reports the move in this poll."""
        now, last = self._cursor_pos(), self._cursor
        self._cursor = now
        return last is not None and now != last and self.monitor.contains(*now) and self.monitor.contains(*last)

    def _note_reporting(self, reported: bool, moved: bool) -> None:
        if reported:
            self.live, self._silent = True, 0
        elif moved:  # one silent poll can be a race with the move; several in a row can't
            self._silent += 1
            self.live = self.live and self._silent < SILENT_POLLS

    def _change_time(self, stamp: int) -> int:
        """The frame's change time, or 0 (unknown: the buffer then uses the poll time, which is
        later) when Desktop Duplication gave no newer one: the old stamp would backdate the frame."""
        if stamp <= self._last_change:
            return 0
        self._last_change = stamp
        return stamp

    def snapshot(self) -> Captured:
        """The monitor as it is now, through GDI, for a still screen Desktop Duplication hasn't
        handed over. No change time: the buffer stamps it when this returns."""
        if self._grabber is None:
            self._grabber = ScreenGrabber()
        image = self._grabber.grab(self.monitor)
        stride = image.bytesPerLine()
        data = self._take(stride * image.height())
        data[:] = image.constBits()
        return Captured(Pixels(data, image.width(), image.height(), stride), 0)

    def _read(self) -> Pixels:
        rect = self._stage.map()
        try:
            size = rect.Pitch * self.monitor.h
            data = self._take(size)
            ctypes.memmove((ctypes.c_char * size).from_buffer(data), rect.pBits, size)
            return Pixels(data, self.monitor.w, self.monitor.h, rect.Pitch)
        finally:
            self._stage.unmap()

    def _take(self, size: int) -> bytearray:
        return self._spare.pop() if self._spare and len(self._spare[-1]) == size else bytearray(size)

    def recycle(self, pixels: Pixels) -> None:
        size = pixels.stride * self.monitor.h
        if len(self._spare) < SPARE_BUFFERS and len(pixels.data) == size:
            self._spare.append(pixels.data)

    def close(self) -> None:
        self._spare = []
        try:
            self._dup.release()
        finally:
            try:
                self._stage.release()
            finally:
                if self._grabber is not None:
                    self._grabber.close()


def _monitor_of(output: Any) -> Rect:
    c = output.desc.DesktopCoordinates
    return Rect(c.left, c.top, c.right - c.left, c.bottom - c.top)


def open_output(device: Any, output: Any, make_duplicator: Callable[[Any, Any], Any],
                make_stage: Callable[[Any, Any], Any]) -> DdaSource | None:
    """A source for one output, or None if Desktop Duplication can't serve it (those monitors get
    screenshots taken after the click)."""
    if not output.attached_to_desktop:
        return None
    monitor = _monitor_of(output)
    if output.rotation_angle:
        log.info("monitor %s is rotated; it gets screenshots after the click", monitor)
        return None
    try:
        duplicator = make_duplicator(output, device)
    except Exception as exc:
        log.warning("can't duplicate monitor %s: %s", monitor, exc)
        return None
    try:
        stage = make_stage(output, device)
    except Exception as exc:
        log.warning("can't read back monitor %s: %s", monitor, exc)
        duplicator.release()
        return None
    return DdaSource(monitor, device.im_context, duplicator, stage)


def open_sources() -> list[DdaSource]:
    import dxcam  # noqa: F401  (the first import builds dxcam's own adapter list; about a second)
    from dxcam.core.device import Device
    from dxcam.core.dxgi_duplicator import DXGIDuplicator
    from dxcam.core.output import Output
    from dxcam.core.stagesurf import StageSurface
    from dxcam.util.io import enum_dxgi_adapters

    def duplicator(output, device):
        return DXGIDuplicator(output=output, device=device)

    def stage(output, device):
        return StageSurface(output=output, device=device)

    sources = []
    for adapter in enum_dxgi_adapters():
        device = Device(adapter)
        for handle in device.enum_outputs():
            source = open_output(device, Output(handle), duplicator, stage)
            if source is not None:
                sources.append(source)
    return sources


def _qpc() -> int:
    value = ctypes.c_longlong()
    _kernel32.QueryPerformanceCounter(ctypes.byref(value))
    return value.value


def windows_clocks() -> Clocks:
    freq = ctypes.c_longlong()
    _kernel32.QueryPerformanceFrequency(ctypes.byref(freq))
    return Clocks(qpc=_qpc, tick_ms=_kernel32.GetTickCount64, freq=freq.value)


def new_frame_buffer() -> FrameBuffer:
    """A stopped buffer over every monitor; the Recorder starts and stops it."""
    return FrameBuffer(open_sources, private_on=system.private_window_on, clocks=windows_clocks())
