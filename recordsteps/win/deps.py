"""The real capture dependencies for pipeline.Session. Build on the worker thread."""
from __future__ import annotations

from PySide6.QtGui import QImage

from ..apps import app_name
from ..model import Rect
from ..ocr_target import Word
from ..pipeline import WindowHit
from ..targets import ElementInfo
from . import system
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

    def window_at(self, x: int, y: int) -> WindowHit:
        return system.window_at(x, y)

    def monitor_at(self, x: int, y: int) -> Rect:
        return self._screen.monitor_at(x, y)

    def dpi_at(self, x: int, y: int) -> int:
        return system.dpi_at(x, y)

    def grab(self, monitor: Rect) -> QImage:
        return self._screen.grab(monitor)

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
        self._screen.close()
        self._uia.close()
