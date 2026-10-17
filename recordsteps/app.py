"""Start the Record Steps window."""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from . import __version__, bundle
from .exporter import export_bundle
from .recorder import Recorder
from .ui import theme
from .ui.controller import Controller
from .ui.flash import ClickFlash
from .ui.launcher import Launcher
from .ui.pill import RecordingPill

APP_ID = "RecordSteps.Prototype"
LOG_NAME = "recordsteps.log"


def log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Record Steps" / LOG_NAME


def setup_logging() -> Path:
    """Log to a file: the windowed app (pythonw) has no console for errors to go to."""
    path = log_path()
    handlers: list[logging.Handler] = []
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    except OSError:
        pass  # read-only profile: fall back to the console below
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers or [logging.NullHandler()])
    return path


def build_icon(size: int = 256) -> QIcon:
    """The click ring on an ink tile."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 64, size / 64)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.HUD_BG))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 15, 15)
    for color, width in (("#FFFFFF", 9), (theme.CORAL, 5)):
        p.setPen(QPen(QColor(color), width))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(17, 17, 30, 30))
    p.end()
    return QIcon(pix)


def _recorder_factory(folder, on_change, on_click):
    from .win.deps import WindowsDeps
    from .win.rawinput import MouseListener
    from .win.system import double_click_metrics

    return Recorder(folder, on_change=on_change, on_click=on_click, deps_factory=WindowsDeps,
                    listener_factory=MouseListener, double_click=double_click_metrics())


def main() -> int:
    setup_logging()
    if sys.platform == "win32":
        import ctypes

        from .win.uia import prewarm

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        threading.Thread(target=prewarm, name="recordsteps-prewarm", daemon=True).start()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Record Steps")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(build_icon())
    root = bundle.default_root()
    launcher = Launcher(recordings_dir=root)
    controller = Controller(launcher, RecordingPill(), ClickFlash(), _recorder_factory, export_bundle, root)
    launcher.show()
    app._controller = controller  # keep alive for the app's lifetime
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
