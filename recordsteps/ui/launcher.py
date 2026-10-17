"""The small start window: what the app records, where it saves, a Record button, the last result."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..bundle import cloud_synced
from . import theme

PRIVACY = ("Each click becomes a step with a screenshot of that monitor, but only while the red recording pill "
           "is on screen. Keystrokes are never recorded. Password fields and private browser windows get no "
           "screenshot. Record Steps never uploads anything.")


class Launcher(QWidget):
    record_clicked = Signal()
    open_path = Signal(object)  # Path

    def __init__(self, recordings_dir: Path | None = None) -> None:
        super().__init__()
        self.setObjectName("launcher")
        self.setWindowTitle("Record Steps")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet(theme.launcher_style(theme.palette()))
        self.setMinimumWidth(480)
        self._recordings = recordings_dir
        self._html: Path | None = None
        self._folder: Path | None = None
        self._word: Path | None = None
        self._pdf: Path | None = None
        self._build()
        self._wire()
        self.show_result("")

    def _build(self) -> None:
        title = QLabel("Record Steps")
        title.setObjectName("title")
        tag = QLabel("Prototype · Phase 0")
        tag.setObjectName("subtle")
        body = QLabel(PRIVACY)
        body.setWordWrap(True)
        self._location = QLabel(self._location_message())
        self._location.setObjectName("subtle")
        self._location.setWordWrap(True)
        self.record_button = QPushButton("Record steps")
        self.record_button.setObjectName("primary")
        self.record_button.setToolTip("Ctrl+R")
        self._result = QLabel()
        self._result.setObjectName("result")
        self._result.setWordWrap(True)
        self._result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.open_guide_button = QPushButton("Open guide")
        self.open_word_button = QPushButton("Open Word")
        self.open_pdf_button = QPushButton("Open PDF")
        self.open_folder_button = QPushButton("Open folder")
        self.recordings_button = QPushButton("Open recordings folder")
        self.recordings_button.setObjectName("link")
        self.recordings_button.setVisible(self._recordings is not None)

        actions = QHBoxLayout()
        for button in (self.open_guide_button, self.open_word_button, self.open_pdf_button, self.open_folder_button):
            actions.addWidget(button)
        actions.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        for widget in (title, tag, body):
            layout.addWidget(widget)
        layout.addWidget(self.record_button, alignment=Qt.AlignLeft)
        layout.addWidget(self._result)
        layout.addLayout(actions)
        layout.addStretch()
        layout.addWidget(self._location)
        layout.addWidget(self.recordings_button, alignment=Qt.AlignLeft)

    def _wire(self) -> None:
        self.record_button.clicked.connect(self.record_clicked)
        shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        shortcut.activated.connect(self.record_clicked)
        self.open_guide_button.clicked.connect(lambda: self._html and self.open_path.emit(self._html))
        self.open_word_button.clicked.connect(lambda: self._word and self.open_path.emit(self._word))
        self.open_pdf_button.clicked.connect(lambda: self._pdf and self.open_path.emit(self._pdf))
        self.open_folder_button.clicked.connect(lambda: self._folder and self.open_path.emit(self._folder))
        self.recordings_button.clicked.connect(lambda: self._recordings and self.open_path.emit(self._recordings))

    def _location_message(self) -> str:
        if self._recordings is None:
            return ""
        text = f"Recordings are saved in {self._recordings}."
        if cloud_synced(self._recordings):
            text += " That folder syncs to the cloud (OneDrive or similar), which will upload the screenshots."
        return text

    def location_text(self) -> str:
        return self._location.text()

    def show_result(self, text: str, html: Path | None = None, folder: Path | None = None,
                    word: Path | None = None, pdf: Path | None = None) -> None:
        self._html, self._folder, self._word, self._pdf = html, folder, word, pdf
        self._result.setText(text)
        self._result.setVisible(bool(text))
        self.open_guide_button.setVisible(html is not None)
        self.open_word_button.setVisible(word is not None)
        self.open_pdf_button.setVisible(pdf is not None)
        self.open_folder_button.setVisible(folder is not None)

    def result_text(self) -> str:
        return self._result.text()
