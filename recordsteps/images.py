"""Screenshot drawing and encoding for exports. Originals in the bundle are never changed."""
from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from .model import Rect

RING = QColor("#FF5A36")
BAND = QColor("#FFFFFF")
HAIRLINE = QColor("#0E1116")
BASE_WIDTH = 1600  # stroke sizes are tuned for an image this wide


def annotate(image: QImage, click: tuple[int, int], bbox: Rect | None) -> QImage:
    """A copy with the click ring: coral stroke, white outer band and a dark inner hairline,
    which stays visible on light, dark and coral backgrounds alike."""
    out = image.convertToFormat(QImage.Format_ARGB32)
    s = max(1.0, image.width() / BASE_WIDTH)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(Qt.NoBrush)
    if bbox is not None:
        pad = 6 * s
        outer = QRectF(bbox.x - pad, bbox.y - pad, bbox.w + 2 * pad, bbox.h + 2 * pad)
        radius = 8 * s
        _stroke(painter, BAND, 7 * s, lambda: painter.drawRoundedRect(outer, radius, radius))
        _stroke(painter, RING, 3 * s, lambda: painter.drawRoundedRect(outer, radius, radius))
        inner = outer.adjusted(2 * s, 2 * s, -2 * s, -2 * s)
        _stroke(painter, HAIRLINE, 1 * s, lambda: painter.drawRoundedRect(inner, radius, radius))
    else:
        center = QPointF(*click)
        r = 18 * s
        _stroke(painter, BAND, 7 * s, lambda: painter.drawEllipse(center, r, r))
        _stroke(painter, RING, 3 * s, lambda: painter.drawEllipse(center, r, r))
        _stroke(painter, HAIRLINE, 1 * s, lambda: painter.drawEllipse(center, r - 2 * s, r - 2 * s))
    painter.end()
    return out


def _stroke(painter: QPainter, color: QColor, width: float, draw) -> None:
    painter.setPen(QPen(color, width))
    draw()


def fit_width(image: QImage, max_width: int) -> QImage:
    if image.width() <= max_width:
        return image
    return image.scaledToWidth(max_width, Qt.SmoothTransformation)


def encode(image: QImage, fmt: str, quality: int = -1) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, fmt, quality)
    buf.close()
    return bytes(data)


def to_data_uri(image: QImage, max_width: int = 1600, quality: int = 82) -> str:
    jpeg = encode(fit_width(image, max_width).convertToFormat(QImage.Format_RGB32), "JPEG", quality)
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
