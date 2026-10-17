"""A small window with known controls for the end-to-end test. Prints the physical screen
centre of each control as one JSON line once it is on screen, then waits to be closed."""
import json
import sys

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget


def physical(widget, local: QPoint) -> list[int]:
    logical = widget.mapToGlobal(local)
    screen = QGuiApplication.screenAt(logical) or QGuiApplication.primaryScreen()
    g, dpr = screen.geometry(), screen.devicePixelRatio()
    return [round(g.x() + (logical.x() - g.x()) * dpr), round(g.y() + (logical.y() - g.y()) * dpr)]


def main() -> int:
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Record Steps Test Target")
    save = QPushButton("Save report")
    remember = QCheckBox("Remember me")
    email = QLineEdit()
    email.setAccessibleName("Email")
    tabs = QTabWidget()
    tabs.addTab(QLabel("General settings"), "General")
    tabs.addTab(QLabel("Advanced settings"), "Advanced")
    layout = QVBoxLayout(window)
    for w in (save, remember, email, tabs):
        layout.addWidget(w)
    window.resize(520, 360)
    window.move(200, 200)
    window.show()
    window.raise_()
    window.activateWindow()

    def report() -> None:
        bar = tabs.tabBar()
        points = {
            "save": physical(save, save.rect().center()),
            "remember": physical(remember, QPoint(8, remember.height() // 2)),
            "email": physical(email, email.rect().center()),
            "advanced": physical(bar, bar.tabRect(1).center()),
        }
        print(json.dumps(points), flush=True)

    QTimer.singleShot(800, report)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
