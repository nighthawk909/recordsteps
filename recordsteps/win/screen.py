"""Screenshots of one monitor via mss (GDI BitBlt). Create and use it on one thread (it holds GDI
device contexts); the capture worker owns it.

Windows marked with WDA_EXCLUDEFROMCAPTURE (the recording pill, the click flash) don't appear.
"""
from __future__ import annotations

from PySide6.QtGui import QImage

from ..model import Rect


class ScreenGrabber:
    def __init__(self) -> None:
        import mss

        factory = getattr(mss, "MSS", None) or mss.mss
        self._mss = factory()

    def monitors(self) -> list[Rect]:
        return [Rect(m["left"], m["top"], m["width"], m["height"]) for m in self._mss.monitors[1:]]

    def monitor_at(self, x: int, y: int) -> Rect:
        monitors = self.monitors()
        for monitor in monitors:
            if monitor.contains(x, y):
                return monitor
        return monitors[0]

    def grab(self, monitor: Rect) -> QImage:
        shot = self._mss.grab({"left": monitor.x, "top": monitor.y, "width": monitor.w, "height": monitor.h})
        raw = bytes(shot.bgra)
        return QImage(raw, shot.width, shot.height, shot.width * 4, QImage.Format_RGB32).copy()

    def close(self) -> None:
        self._mss.close()
