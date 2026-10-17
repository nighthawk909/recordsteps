"""The real capture dependencies for pipeline.Session. Build on the worker thread.

frame_buffer is started and stopped by the Recorder; until it runs, frame_before() has nothing
and steps use a screenshot taken after the click."""
from __future__ import annotations

from PySide6.QtGui import QImage

from ..apps import app_name
from ..frames import Pick
from ..model import Rect
from ..ocr_target import Word
from ..pipeline import WindowHit
from ..targets import ElementInfo
from . import system
from .dda import new_frame_buffer
from .screen import ScreenGrabber
from .uia import UiaClient


class WindowsDeps:
    def __init__(self) -> None:
        self._screen = ScreenGrabber()
        try:
            self._uia = UiaClient()
        except Exception:
            self._screen.close()
            raise
        self.frame_buffer = new_frame_buffer()

    def window_at(self, x: int, y: int) -> WindowHit:
        return system.window_at(x, y)

    def monitor_at(self, x: int, y: int) -> Rect:
        return self._screen.monitor_at(x, y)

    def dpi_at(self, x: int, y: int) -> int:
        return system.dpi_at(x, y)

    def grab(self, monitor: Rect) -> QImage:
        return self._screen.grab(monitor)

    def frame_before(self, monitor: Rect, t_ms: int) -> Pick | None:
        return self.frame_buffer.frame_before(monitor, t_ms)

    def chain_at(self, x: int, y: int) -> tuple[ElementInfo, ...]:
        return self._uia.chain_at(x, y)

    def ocr_words(self, image: QImage) -> tuple[Word, ...]:
        from ..ocr import recognize_words

        return recognize_words(image)

    def app_name(self, process_path: str) -> str:
        return app_name(process_path)

    def private_window_on(self, monitor: Rect) -> bool:
        return system.private_window_on(monitor)

    def close(self) -> None:
        try:
            self.frame_buffer.stop()
        finally:
            try:
                self._screen.close()
            finally:
                self._uia.close()
