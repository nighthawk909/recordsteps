"""Coordinate helpers. Capture works in physical pixels; Qt windows use logical pixels."""
from __future__ import annotations

from collections.abc import Sequence

from .model import Rect

MAX_TARGET_SHARE = 0.25  # a 'target' covering more of the screen than this isn't worth ringing


def relative_point(px: int, py: int, monitor: Rect) -> tuple[int, int]:
    return px - monitor.x, py - monitor.y


def relative_rect(rect: Rect, monitor: Rect) -> Rect | None:
    """rect clipped to the monitor and made relative to it; None if they don't overlap."""
    left, top = max(rect.x, monitor.x), max(rect.y, monitor.y)
    right, bottom = min(rect.right, monitor.right), min(rect.bottom, monitor.bottom)
    if right <= left or bottom <= top:
        return None
    return Rect(left - monitor.x, top - monitor.y, right - left, bottom - top)


def useful_bbox(rect: Rect | None, monitor: Rect, max_share: float = MAX_TARGET_SHARE) -> Rect | None:
    """The target's box relative to the monitor, or None when missing, off-screen or so big
    (a whole pane or window) that ringing it would point at nothing."""
    if rect is None:
        return None
    local = relative_rect(rect, monitor)
    if local is None or local.area > max_share * monitor.area:
        return None
    return local


def focus_rect(click: tuple[int, int], bbox: Rect | None, image_size: tuple[int, int], *,
               min_width: int = 1280, aspect: float = 1.6) -> Rect:
    """A crop around the target so wide or high-resolution screenshots stay readable in a
    document. Centred on the target, at least min_width wide (wider for big targets), clamped
    inside the image."""
    img_w, img_h = image_size
    if img_w <= min_width:
        return Rect(0, 0, img_w, img_h)
    width = max(min_width, int(bbox.w * 1.6) if bbox else 0)
    width = min(width, img_w)
    height = min(int(round(width / aspect)), img_h)
    width = min(img_w, int(round(height * aspect)))
    cx = bbox.x + bbox.w // 2 if bbox else click[0]
    cy = bbox.y + bbox.h // 2 if bbox else click[1]
    x = min(max(0, cx - width // 2), img_w - width)
    y = min(max(0, cy - height // 2), img_h - height)
    return Rect(x, y, width, height)


def percent_box(rect: Rect, frame: Rect) -> tuple[float, float, float, float]:
    """rect as left/top/width/height percentages of frame (rect in the same coordinates as frame)."""
    return (round((rect.x - frame.x) * 100 / frame.w, 3), round((rect.y - frame.y) * 100 / frame.h, 3),
            round(rect.w * 100 / frame.w, 3), round(rect.h * 100 / frame.h, 3))


def physical_to_logical(px: int, py: int, screens: Sequence[tuple[Rect, Rect, float]]) -> tuple[int, int]:
    """Map a physical point to Qt's logical coordinates. screens: (physical rect, logical rect,
    device pixel ratio) per monitor. Points on no monitor are returned unchanged."""
    for native, logical, dpr in screens:
        if native.contains(px, py):
            return (logical.x + int(round((px - native.x) / dpr)), logical.y + int(round((py - native.y) / dpr)))
    return px, py
