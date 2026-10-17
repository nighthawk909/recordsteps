"""Ink & Ember colors for the app's own windows (see the blueprint's palette)."""
from __future__ import annotations

from dataclasses import dataclass

FONT = '"Segoe UI Variable Text", "Segoe UI", sans-serif'


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    line: str
    text: str
    text2: str
    accent: str
    accent_hover: str
    on_accent: str


LIGHT = Palette(bg="#FAF8F5", surface="#FFFFFF", line="#E5DFD7", text="#1C1A18", text2="#666461",
                accent="#D53100", accent_hover="#BC2A00", on_accent="#FFFFFF")
DARK = Palette(bg="#0E1116", surface="#151920", line="#262B34", text="#EBF0F8", text2="#A5AAB1",
               accent="#FF5A36", accent_hover="#FF7D60", on_accent="#0E1116")

# The recording pill is always dark, like a heads-up display, so it reads over any app.
HUD_BG = "#0E1116"
HUD_LINE = "#2A2F38"
HUD_TEXT = "#EBF0F8"
HUD_DIM = "#A5AAB1"
RECORDING = "#FF4A3D"
PAUSED = "#F5A524"
CORAL = "#FF5A36"


def is_dark() -> bool:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    hints = QGuiApplication.styleHints()
    return bool(hints) and hints.colorScheme() == Qt.ColorScheme.Dark


def palette() -> Palette:
    return DARK if is_dark() else LIGHT


def launcher_style(p: Palette) -> str:
    return f"""
    QWidget#launcher {{ background: {p.bg}; }}
    QLabel {{ color: {p.text}; font-family: {FONT}; font-size: 14px; }}
    QLabel#title {{ font-size: 22px; font-weight: 700; }}
    QLabel#subtle {{ color: {p.text2}; font-size: 12px; }}
    QLabel#result {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: 8px; padding: 10px; }}
    QPushButton {{ font-family: {FONT}; font-size: 13px; color: {p.text}; background: {p.surface};
                  border: 1px solid {p.line}; border-radius: 8px; padding: 7px 14px; }}
    QPushButton:hover {{ border-color: {p.text2}; }}
    QPushButton:focus {{ outline: none; border: 2px solid {p.accent}; }}
    QPushButton#primary {{ background: {p.accent}; color: {p.on_accent}; border: none; font-weight: 600;
                          padding: 10px 18px; font-size: 14px; }}
    QPushButton#primary:hover {{ background: {p.accent_hover}; }}
    QPushButton#link {{ border: none; background: transparent; color: {p.accent}; padding: 2px 0; }}
    """


def pill_style() -> str:
    return f"""
    QLabel {{ color: {HUD_TEXT}; font-family: {FONT}; font-size: 13px; }}
    QLabel#dim {{ color: {HUD_DIM}; }}
    QPushButton {{ font-family: {FONT}; font-size: 12px; color: {HUD_TEXT}; background: transparent;
                  border: none; border-radius: 13px; padding: 6px 11px; }}
    QPushButton:hover {{ background: {HUD_LINE}; }}
    QPushButton:focus {{ outline: none; border: 1px solid {CORAL}; }}
    QPushButton#stop {{ background: {CORAL}; color: {HUD_BG}; font-weight: 600; }}
    QPushButton#stop:hover {{ background: #FF7D60; }}
    """
