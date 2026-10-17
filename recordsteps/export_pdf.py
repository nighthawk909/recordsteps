"""PDF export with Qt's own PDF writer: real (searchable) text, a step never split across pages,
and 'Page N of M' footers. Needs a QGuiApplication; no extra dependencies."""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QImageReader,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
    QTextDocument,
)

from .bundle import replace_file
from .emphasis import segments
from .model import Guide, Step, display_title

log = logging.getLogger(__name__)
RESOLUTION = 144  # layout units per inch; text and lines stay vector at any zoom
MARGIN_PT = 54  # 0.75 inch
BADGE_IN, INDENT_IN, GAP_IN, FOOTER_IN, IMAGE_GAP_IN = 0.30, 0.42, 0.28, 0.32, 0.12
MAX_IMAGE_IN = 3.85  # two steps fit on a Letter page
MAX_TEXT = 300  # characters of a title shown; longer ones (hand-edited) are cut with an ellipsis
INK, MUTED, LINE, CORAL = "#1C1A18", "#666461", "#E5DFD7", "#FF5A36"
FONT_FILES = ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf")  # regular, bold, italic


def plan_pages(header: float, blocks: Sequence[float], page_height: float, gap: float) -> list[list[int]]:
    """Which blocks go on which page. A block never splits; one taller than a page gets a page of
    its own. The header only takes space on the first page, and counts as content there."""
    pages: list[list[int]] = [[]]
    y = header
    for index, height in enumerate(blocks):
        if (pages[-1] or y > 0) and y + height > page_height:
            pages.append([])
            y = 0.0
        pages[-1].append(index)
        y += height + gap
    return pages


def _short(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _font_family() -> str:
    """Segoe UI, loaded from Windows' font folder when Qt's platform doesn't provide it (the
    headless platform has no fonts of its own)."""
    if "Segoe UI" in QFontDatabase.families():
        return "Segoe UI"
    folder = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    families = [QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(folder / name)))
                for name in FONT_FILES if (folder / name).is_file()]
    return next((f[0] for f in families if f), QFont().defaultFamily())


@dataclass(frozen=True)
class _Block:
    """One step's layout. The screenshot is loaded only while it is drawn, so a long guide
    doesn't hold every image in memory at once."""

    title: QTextDocument
    image: Path | None
    image_size: tuple[float, float]  # drawn size in layout units
    note: QTextDocument | None

    @property
    def height(self) -> float:
        h = self.title.size().height()
        if self.image is not None:
            h += self.image_size[1] + IMAGE_GAP_IN * RESOLUTION
        if self.note is not None:
            h += self.note.size().height()
        return h


class _Renderer:
    def __init__(self, writer: QPdfWriter, family: str) -> None:
        self.writer = writer
        self.family = family
        self.width = float(writer.width())
        self.indent = INDENT_IN * RESOLUTION

    def doc(self, html: str, size: float, width: float, color: str = INK, italic: bool = False) -> QTextDocument:
        doc = QTextDocument()
        doc.documentLayout().setPaintDevice(self.writer)  # point sizes measured for the PDF, not the screen
        font = QFont(self.family)
        font.setPointSizeF(size)
        font.setItalic(italic)
        doc.setDefaultFont(font)
        doc.setDocumentMargin(0)
        doc.setTextWidth(width)
        doc.setHtml(f'<div style="color:{color}">{html}</div>')
        return doc

    def block(self, step: Step, image_path: Path | None) -> _Block:
        parts = segments(_short(display_title(step)))
        title = self.doc("".join(f"<b>{escape(t)}</b>" if bold else escape(t) for t, bold in parts), 12.5,
                         self.width - self.indent)
        size = QImageReader(str(image_path)).size() if image_path else QSize()
        if image_path and not size.isValid():
            log.warning("PDF export: can't read screenshot %s", image_path)
        drawn = self._fit(size) if size.isValid() and not size.isEmpty() else None
        note = self.doc(escape(step.note), 10, self.width - self.indent, MUTED, italic=True) \
            if drawn is None and step.note else None
        return _Block(title, image_path if drawn else None, drawn or (0.0, 0.0), note)

    def _fit(self, size: QSize) -> tuple[float, float]:
        width = self.width - self.indent
        height = width * size.height() / size.width()
        limit = MAX_IMAGE_IN * RESOLUTION
        if height > limit:
            height, width = limit, limit * size.width() / size.height()
        return width, height

    def draw_doc(self, painter: QPainter, doc: QTextDocument, x: float, y: float) -> None:
        painter.save()
        painter.translate(x, y)
        doc.drawContents(painter)
        painter.restore()

    def draw_badge(self, painter: QPainter, number: int, y: float) -> None:
        d = BADGE_IN * RESOLUTION
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(CORAL))
        painter.drawEllipse(QRectF(0, y, d, d))
        font = QFont(self.family)
        font.setPointSizeF(9.5)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(INK))
        painter.drawText(QRectF(0, y, d, d), Qt.AlignCenter, str(number))
        painter.restore()

    def draw_block(self, painter: QPainter, number: int, block: _Block, y: float) -> None:
        self.draw_badge(painter, number, y)
        self.draw_doc(painter, block.title, self.indent, y + 0.02 * RESOLUTION)
        y += block.title.size().height()
        if block.image is not None:
            y += IMAGE_GAP_IN * RESOLUTION
            target = QRectF(self.indent, y, *block.image_size)
            image = QImage(str(block.image))  # loaded now and freed after drawing
            painter.drawImage(target, image)
            painter.save()
            painter.setPen(QPen(QColor(LINE), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(target)
            painter.restore()
        if block.note is not None:
            self.draw_doc(painter, block.note, self.indent, y)

    def draw_footer(self, painter: QPainter, title: str, page: int, pages: int) -> None:
        painter.save()
        font = QFont(self.family)
        font.setPointSizeF(8)
        painter.setFont(font)
        painter.setPen(QColor(MUTED))
        area = QRectF(0, self.writer.height() - FOOTER_IN * RESOLUTION * 0.6, self.width, FOOTER_IN * RESOLUTION)
        label = QFontMetricsF(font, self.writer).elidedText(f"Record Steps · {title}", Qt.ElideRight,
                                                            self.width * 0.7)
        painter.drawText(area, Qt.AlignLeft | Qt.AlignTop, label)
        painter.drawText(area, Qt.AlignRight | Qt.AlignTop, f"Page {page} of {pages}")
        painter.restore()


def _writer(guide: Guide, path: Path) -> QPdfWriter:
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.Letter))
    writer.setPageMargins(QMarginsF(MARGIN_PT, MARGIN_PT, MARGIN_PT, MARGIN_PT), QPageLayout.Unit.Point)
    writer.setResolution(RESOLUTION)
    writer.setTitle(guide.title)
    writer.setCreator("Record Steps")
    return writer


def _header_html(guide: Guide) -> str:
    count = len(guide.steps)
    apps = ", ".join(dict.fromkeys(s.app for s in guide.steps if s.app))
    meta = " · ".join(p for p in (f"Recorded {guide.created[:10]}", f"{count} step{'' if count == 1 else 's'}",
                                  apps) if p)
    return (f'<div style="font-size:22pt;font-weight:700">{escape(_short(guide.title, 120))}</div>'
            f'<div style="font-size:10pt;color:{MUTED}">{escape(_short(meta, 200))}</div>')


def _paint(writer: QPdfWriter, guide: Guide, r: _Renderer, header: QTextDocument, blocks: list[_Block],
           pages: list[list[int]]) -> None:
    gap = GAP_IN * RESOLUTION
    painter = QPainter(writer)
    if not painter.isActive():
        raise OSError("couldn't write the PDF file (is the folder read-only?)")
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    try:
        for page_number, indices in enumerate(pages, start=1):
            if page_number > 1:
                writer.newPage()
            y = 0.0
            if page_number == 1:
                r.draw_doc(painter, header, 0, 0)
                y = header.size().height() + gap / 2
                painter.setPen(QPen(QColor(LINE), 1.5))
                painter.drawLine(0, int(y), int(r.width), int(y))
                y += gap / 2
            for index in indices:
                r.draw_block(painter, index + 1, blocks[index], y)
                y += blocks[index].height + gap
            r.draw_footer(painter, _short(guide.title, 120), page_number, len(pages))
    finally:
        painter.end()


def render_pdf(guide: Guide, images: Mapping[str, Path], out_path: Path) -> Path:
    """images maps step id -> an annotated screenshot file. Writes to a temporary file first, so
    a failure (or a PDF viewer holding the old file) never leaves a broken or stale guide.pdf."""
    if QGuiApplication.instance() is None:
        raise RuntimeError("PDF export needs a QGuiApplication")
    out_path = Path(out_path)
    tmp = out_path.with_name(out_path.name + ".tmp")
    writer = _writer(guide, tmp)
    r = _Renderer(writer, _font_family())
    header = r.doc(_header_html(guide), 11, r.width)
    blocks = [r.block(step, images.get(step.id)) for step in guide.steps]
    body = writer.height() - FOOTER_IN * RESOLUTION
    gap = GAP_IN * RESOLUTION
    pages = plan_pages(header.size().height() + gap, [b.height for b in blocks], body, gap)
    try:
        _paint(writer, guide, r, header, blocks, pages)  # ending the painter finishes and closes the file
        replace_file(tmp, out_path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return out_path
