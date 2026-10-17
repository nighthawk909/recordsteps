"""A brief ring at the pointer for every captured click, so people know a step was recorded.
Click-through, never focused, and left out of the screenshots."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..geometry import physical_to_logical
from ..model import Rect
from . import theme

SIZE = 64
FLASH_MS = 160


def screen_map() -> list[tuple[Rect, Rect, float]]:
    """(physical, logical, ratio) per monitor. Qt keeps each screen's top-left in physical
    coordinates and scales only its size."""
    out = []
    for screen in QGuiApplication.screens():
        g, dpr = screen.geometry(), screen.devicePixelRatio()
        out.append((Rect(g.x(), g.y(), round(g.width() * dpr), round(g.height() * dpr)),
                    Rect(g.x(), g.y(), g.width(), g.height()), dpr))
    return out


class ClickFlash(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(SIZE, SIZE)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._excluded = False

    def flash(self, physical_x: int, physical_y: int) -> None:
        x, y = physical_to_logical(physical_x, physical_y, screen_map())
        self.move(x - SIZE // 2, y - SIZE // 2)
        self.show()
        self.raise_()
        self._timer.start(FLASH_MS)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if not self._excluded and QGuiApplication.platformName() == "windows":
            from ..win.system import exclude_from_capture

            self._excluded = exclude_from_capture(int(self.winId()))

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        center, r = QPointF(SIZE / 2, SIZE / 2), 20.0
        for color, width, radius in (("#FFFFFF", 7, r), (theme.CORAL, 3, r), (theme.HUD_BG, 1, r - 2)):
            p.setPen(QPen(QColor(color), width))
            p.drawEllipse(center, radius, radius)
        p.end()
