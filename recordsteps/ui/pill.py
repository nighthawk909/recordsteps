"""The recording pill: the visible promise that clicks are being recorded.

It floats over every app, stays out of the screenshots, never takes focus from the app being
recorded, and shows a pulsing red dot, the elapsed time and the step count.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from . import theme

HEIGHT = 44
TOP_MARGIN = 12
TICK_MS = 100
PULSE_MS = 1600


def format_elapsed(ms: int) -> str:
    seconds = max(0, ms) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class _Dot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.color = QColor(theme.RECORDING)
        self.alpha = 1.0

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self.color)
        c.setAlphaF(self.alpha)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(1, 1, 10, 10))
        p.end()


class RecordingPill(QWidget):
    start_now_clicked = Signal()
    cancel_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    discard_confirmed = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAccessibleName("Record Steps recording controls")
        self.setStyleSheet(theme.pill_style())
        self.setFixedHeight(HEIGHT)
        self.state = "idle"
        self._resume_state = "recording"
        self._steps = 0
        self._countdown = 0
        self._elapsed_ms = 0
        self._running = QElapsedTimer()
        self._drag: QPoint | None = None
        self._excluded = False
        self._animate = _animations_enabled()
        self._build()
        self._wire()
        self._ticker = QTimer(self)
        self._ticker.setInterval(TICK_MS)
        self._ticker.timeout.connect(self._tick)
        self._pulse = QElapsedTimer()
        self._pulse.start()
        self._show_only()

    def _build(self) -> None:
        self._dot = _Dot(self)
        self._status = QLabel(self)
        self._status.setAccessibleName("Recording status")
        self._confirm = QLabel("Discard this recording?", self)
        self.start_now_button = self._button("Start now", "start")
        self.cancel_button = self._button("Cancel", "cancel")
        self.pause_button = self._button("Pause", "pause")
        self.stop_button = self._button("Stop && build", "stop")
        self.discard_button = self._button("Discard", "discard")
        self.keep_button = self._button("Keep recording", "keep")
        self.confirm_discard_button = self._button("Discard", "stop")
        self.confirm_discard_button.setAccessibleName("Yes, discard the recording")

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 6, 0)
        row.setSpacing(6)
        row.addWidget(self._dot)
        row.addWidget(self._status)
        row.addWidget(self._confirm)
        for b in (self.start_now_button, self.cancel_button, self.pause_button, self.stop_button,
                  self.discard_button, self.keep_button, self.confirm_discard_button):
            row.addWidget(b)

    def _wire(self) -> None:
        self.start_now_button.clicked.connect(self.start_now_clicked)
        self.cancel_button.clicked.connect(self.cancel_clicked)
        self.pause_button.clicked.connect(self.pause_clicked)
        self.stop_button.clicked.connect(self.stop_clicked)
        self.discard_button.clicked.connect(self._ask_discard)
        self.keep_button.clicked.connect(self._keep)
        self.confirm_discard_button.clicked.connect(self.discard_confirmed)

    def _button(self, text: str, name: str) -> QPushButton:
        b = QPushButton(text, self)
        b.setObjectName(name)
        b.setFocusPolicy(Qt.TabFocus)
        b.setCursor(Qt.PointingHandCursor)
        return b

    # ------------------------------------------------------------------ states
    def show_countdown(self, seconds: int) -> None:
        self.state = "countdown"
        self._countdown = seconds
        self._dot.color = QColor(theme.HUD_DIM)
        self._status.setText(f"Recording starts in {seconds}")
        self._show_only(self._dot, self._status, self.start_now_button, self.cancel_button)
        self._present()

    def show_recording(self) -> None:
        self.state = "recording"
        self._elapsed_ms = 0
        self._running.start()
        self._dot.color = QColor(theme.RECORDING)
        self._show_running()
        self._ticker.start()
        self._present()

    def set_step_count(self, count: int) -> None:
        self._steps = count
        self._refresh()

    def set_paused(self, paused: bool) -> None:
        if paused and self.state == "recording":
            self._elapsed_ms += self._running.elapsed()
            self.state = "paused"
            self._dot.color = QColor(theme.PAUSED)
        elif not paused and self.state == "paused":
            self._running.start()
            self.state = "recording"
            self._dot.color = QColor(theme.RECORDING)
        self.pause_button.setText("Resume" if self.state == "paused" else "Pause")
        self._refresh()

    def show_building(self) -> None:
        self.state = "building"
        self._ticker.stop()
        self._dot.color = QColor(theme.HUD_DIM)
        self._dot.alpha = 1.0
        self._status.setText("Building your guide…")
        self._show_only(self._dot, self._status)
        self._fit()

    def status_text(self) -> str:
        return self._confirm.text() if self.state == "confirm_discard" else self._status.text()

    def elapsed_ms(self) -> int:
        running = self._running.elapsed() if self.state == "recording" and self._running.isValid() else 0
        return self._elapsed_ms + running

    def hide(self) -> None:
        self._ticker.stop()
        self.state = "idle"
        super().hide()

    # ------------------------------------------------------------------ discard confirmation
    def _ask_discard(self) -> None:
        self._resume_state = self.state
        self.state = "confirm_discard"
        self._show_only(self._dot, self._confirm, self.keep_button, self.confirm_discard_button)
        self._fit()

    def _keep(self) -> None:
        self.state = self._resume_state
        self._show_running()

    # ------------------------------------------------------------------ internals
    def _show_running(self) -> None:
        self._show_only(self._dot, self._status, self.pause_button, self.stop_button, self.discard_button)
        self._refresh()

    def _show_only(self, *widgets: QWidget) -> None:
        for w in (self._dot, self._status, self._confirm, self.start_now_button, self.cancel_button,
                  self.pause_button, self.stop_button, self.discard_button, self.keep_button,
                  self.confirm_discard_button):
            w.setVisible(w in widgets)

    def _refresh(self) -> None:
        if self.state not in ("recording", "paused"):
            return
        steps = f"{self._steps} step{'' if self._steps == 1 else 's'}"
        prefix = "Paused · " if self.state == "paused" else ""
        self._status.setText(f"{prefix}{format_elapsed(self.elapsed_ms())} · {steps}")
        self._fit()

    def _tick(self) -> None:
        if self.state == "recording" and self._animate:
            phase = (self._pulse.elapsed() % PULSE_MS) / PULSE_MS
            self._dot.alpha = 0.55 + 0.45 * (0.5 + 0.5 * math.cos(phase * 2 * math.pi))
        else:
            self._dot.alpha = 1.0
        self._dot.update()
        self._refresh()

    def _fit(self) -> None:
        self.adjustSize()
        self.setFixedHeight(HEIGHT)

    def _present(self) -> None:
        self._fit()
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.top() + TOP_MARGIN)
        self.show()
        self.raise_()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if not self._excluded and QGuiApplication.platformName() == "windows":
            from ..win.system import exclude_from_capture

            self._excluded = exclude_from_capture(int(self.winId()))

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.HUD_LINE), 1))
        p.setBrush(QColor(theme.HUD_BG))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag is not None:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802 - Qt API
        self._drag = None


def _animations_enabled() -> bool:
    if QGuiApplication.platformName() != "windows":
        return True
    from ..win.system import animations_enabled

    return animations_enabled()
