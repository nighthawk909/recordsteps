"""Text recognition with the OCR engine built into Windows (offline, no model download).

Adapted from SnipForge (github.com/nighthawk909/snipforge, snipforge/ocr.py at 37bb815, MIT
license); returns plain Words for the pipeline instead of Qt rectangles.
"""
from __future__ import annotations

import asyncio

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

from .ocr_target import Word

OCR_MAX_SIDE = 9000  # under OcrEngine.MaxImageDimension (10000)


class OcrUnavailable(RuntimeError):
    """Windows can't do OCR here (e.g. no OCR language pack installed)."""


def _png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(data)


async def _recognize_async(png: bytes):
    try:
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    except ImportError as exc:  # pragma: no cover - only when the install is broken
        raise OcrUnavailable("Text recognition components are missing.") from exc

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrUnavailable("No OCR language pack is installed in Windows.")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    return await engine.recognize_async(bitmap)


def _upscale_small(image: QImage) -> tuple[QImage, float]:
    """Windows OCR misses small UI text; doubling small images helps a lot."""
    short = min(image.width(), image.height())
    if short < 600 and max(image.width(), image.height()) * 2 <= OCR_MAX_SIDE:
        return image.scaled(image.width() * 2, image.height() * 2), 2.0
    return image, 1.0


def recognize_words(image: QImage) -> tuple[Word, ...]:
    """Blocking OCR; words in the image's pixel coordinates, numbered by line."""
    scaled, scale = _upscale_small(image)
    raw = asyncio.run(_recognize_async(_png_bytes(scaled)))
    words: list[Word] = []
    for index, line in enumerate(raw.lines):
        for w in line.words:
            r = w.bounding_rect
            words.append(Word(w.text, int(r.x / scale), int(r.y / scale), max(1, int(r.width / scale)),
                              max(1, int(r.height / scale)), index))
    return tuple(words)
