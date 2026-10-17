"""Mouse clicks as they arrive from the input listener."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawClick:
    button: str  # "left" or "right"
    x: int  # virtual-desktop physical pixels
    y: int
    t_ms: int  # Windows message time (milliseconds since boot, wraps after 49.7 days)


def is_double(prev: RawClick | None, cur: RawClick, *, max_ms: int, max_dx: int, max_dy: int) -> bool:
    """A second left click soon after the first and in the same place, per Windows' own
    double-click time and distance."""
    if prev is None or prev.button != "left" or cur.button != "left":
        return False
    elapsed = cur.t_ms - prev.t_ms
    return 0 <= elapsed <= max_ms and abs(cur.x - prev.x) <= max_dx and abs(cur.y - prev.y) <= max_dy
