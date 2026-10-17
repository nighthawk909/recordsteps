"""Turn a recording folder into guide.html, guide.md (with images) and review.csv."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from .bundle import BundleError, load_guide
from .export_html import ShotView, render_html
from .export_md import render_markdown
from .geometry import focus_rect, percent_box
from .images import annotate, fit_width, to_data_uri
from .model import Rect, Step
from .stats import write_review

log = logging.getLogger(__name__)
EXPORT_DIR = "export"
MAX_WIDTH = 1600


@dataclass(frozen=True)
class ExportResult:
    html: Path
    markdown: Path
    review: Path


def inside(bundle_dir: Path, relative: str) -> Path:
    """bundle_dir / relative, refusing anything that resolves outside the bundle (absolute paths,
    '..', network shares). guide.json is validated on load; this guards the file system too."""
    root = Path(bundle_dir).resolve()
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or Path(relative).drive or not path.is_relative_to(root):
        raise BundleError(f"{relative!r} points outside the recording folder")
    return path


def _crop(step: Step, image: QImage) -> tuple[QImage, Rect, tuple[int, int], Rect | None]:
    frame = focus_rect(step.click, step.target.bbox, (image.width(), image.height()))
    cropped = image.copy(QRect(frame.x, frame.y, frame.w, frame.h))
    click = (step.click[0] - frame.x, step.click[1] - frame.y)
    bbox = step.target.bbox
    local = Rect(bbox.x - frame.x, bbox.y - frame.y, bbox.w, bbox.h) if bbox else None
    return cropped, frame, click, local


def export_bundle(bundle_dir: Path) -> ExportResult:
    bundle_dir = Path(bundle_dir)
    guide = load_guide(bundle_dir)
    out = bundle_dir / EXPORT_DIR
    (out / "images").mkdir(parents=True, exist_ok=True)
    md_images: dict[str, str] = {}
    shots: dict[str, ShotView] = {}
    for step in guide.steps:
        if not step.image:
            continue
        image = QImage(str(inside(bundle_dir, step.image)))
        if image.isNull():
            log.warning("missing or unreadable screenshot %s", step.image)
            continue
        cropped, frame, click, local_bbox = _crop(step, image)
        marked = fit_width(annotate(cropped, click, local_bbox), MAX_WIDTH)
        relative = f"images/{step.id}.png"
        if marked.save(str(inside(out, relative)), "PNG"):
            md_images[step.id] = relative
        ring = percent_box(step.target.bbox, frame) if step.target.bbox else None
        dot = (round(click[0] * 100 / frame.w, 3), round(click[1] * 100 / frame.h, 3))
        shots[step.id] = ShotView(to_data_uri(cropped, MAX_WIDTH), ring, dot, f"../{step.image}")
    html = out / "guide.html"
    html.write_text(render_html(guide, shots), encoding="utf-8")
    markdown = out / "guide.md"
    markdown.write_text(render_markdown(guide, md_images), encoding="utf-8")
    review = write_review(bundle_dir / "review.csv", guide)
    return ExportResult(html=html, markdown=markdown, review=review)
