"""Name a click from the text on screen when UI Automation can't (remote desktops, Citrix,
custom-drawn apps): the OCR'd words nearest the pointer."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

MAX_DISTANCE = 40  # pixels from the click to the nearest word's edge
MAX_CHARS = 40


@dataclass(frozen=True)
class Word:
    text: str
    x: int
    y: int
    w: int
    h: int
    line: int  # words on the same OCR line share this number

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


@dataclass(frozen=True)
class TextHit:
    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w


def _distance(word: Word, point: tuple[int, int]) -> float:
    px, py = point
    dx = max(word.x - px, 0, px - word.right)
    dy = max(word.y - py, 0, py - word.bottom)
    return math.hypot(dx, dy)


def nearest_text(words: Sequence[Word], point: tuple[int, int]) -> TextHit | None:
    """The line of text under or next to the click, trimmed around the nearest word."""
    if not words:
        return None
    best = min(words, key=lambda w: _distance(w, point))
    if _distance(best, point) > MAX_DISTANCE:
        return None
    line = sorted((w for w in words if w.line == best.line), key=lambda w: w.x)
    lo = hi = line.index(best)
    length = len(best.text)
    while True:  # grow outwards from the nearest word while the text stays short
        grew = False
        if hi + 1 < len(line) and length + 1 + len(line[hi + 1].text) <= MAX_CHARS:
            hi += 1
            length += 1 + len(line[hi].text)
            grew = True
        if lo > 0 and length + 1 + len(line[lo - 1].text) <= MAX_CHARS:
            lo -= 1
            length += 1 + len(line[lo].text)
            grew = True
        if not grew:
            break
    chosen = line[lo:hi + 1]
    left, top = min(w.x for w in chosen), min(w.y for w in chosen)
    right, bottom = max(w.right for w in chosen), max(w.bottom for w in chosen)
    text = " ".join(w.text for w in chosen)[:MAX_CHARS]
    return TextHit(text, left, top, right - left, bottom - top)
