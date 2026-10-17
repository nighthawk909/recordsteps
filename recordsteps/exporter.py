"""Turn a recording folder into guide.html, guide.md (with images), guide.docx, guide.pdf and
review.csv."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from .bundle import BundleError, load_guide
from .export_docx import render_docx
from .export_html import ShotView, render_html
from .export_md import render_markdown
from .export_pdf import render_pdf
from .geometry import focus_rect, percent_box
from .images import annotate, fit_width, to_data_uri
from .model import Guide, Rect, Step
from .stats import write_review

log = logging.getLogger(__name__)
EXPORT_DIR = "export"
MAX_WIDTH = 1600


@dataclass(frozen=True)
class ExportResult:
    html: Path
    markdown: Path
    review: Path
    word: Path | None = None  # None when that export failed; see problems
    pdf: Path | None = None
    problems: tuple[str, ...] = ()


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


def _screenshots(bundle_dir: Path, guide: Guide, out: Path,
                 missing: list[str]) -> tuple[dict[str, str], dict[str, ShotView]]:
    """Crop and annotate each screenshot once: files for Markdown, Word and PDF, data URIs for HTML.
    Steps whose screenshot can't be read or written are added to missing."""
    md_images: dict[str, str] = {}
    shots: dict[str, ShotView] = {}
    for step in guide.steps:
        if not step.image:
            continue
        image = QImage(str(inside(bundle_dir, step.image)))
        if image.isNull():
            log.warning("missing or unreadable screenshot %s", step.image)
            missing.append(step.id)
            continue
        cropped, frame, click, local_bbox = _crop(step, image)
        marked = fit_width(annotate(cropped, click, local_bbox), MAX_WIDTH)
        relative = f"images/{step.id}.png"
        if marked.save(str(inside(out, relative)), "PNG"):
            md_images[step.id] = relative
        else:
            log.warning("couldn't write %s", relative)
            missing.append(step.id)
        ring = percent_box(step.target.bbox, frame) if step.target.bbox else None
        dot = (round(click[0] * 100 / frame.w, 3), round(click[1] * 100 / frame.h, 3))
        shots[step.id] = ShotView(to_data_uri(cropped, MAX_WIDTH), ring, dot, f"../{step.image}")
    return md_images, shots


def _failure(kind: str, path: Path, exc: Exception) -> str:
    if isinstance(exc, PermissionError):
        return f"{kind} export failed: {path.name} is open in another program; close it and export again"
    return f"{kind} export failed: {exc}"


def _office(guide: Guide, images: dict[str, Path], out: Path, template: Path | None):
    """Word and PDF are extras: if one fails (say guide.docx is open in Word), the rest still exports."""
    word = pdf = None
    problems: list[str] = []
    try:
        word = render_docx(guide, images, out / "guide.docx", template=template)
    except Exception as exc:
        log.exception("Word export failed")
        problems.append(_failure("Word", out / "guide.docx", exc))
    try:
        pdf = render_pdf(guide, images, out / "guide.pdf")
    except Exception as exc:
        log.exception("PDF export failed")
        problems.append(_failure("PDF", out / "guide.pdf", exc))
    return word, pdf, tuple(problems)


def export_bundle(bundle_dir: Path, *, word_template: Path | None = None) -> ExportResult:
    bundle_dir = Path(bundle_dir)
    guide = load_guide(bundle_dir)
    out = bundle_dir / EXPORT_DIR
    (out / "images").mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    md_images, shots = _screenshots(bundle_dir, guide, out, missing)
    html = out / "guide.html"
    html.write_text(render_html(guide, shots), encoding="utf-8")
    markdown = out / "guide.md"
    markdown.write_text(render_markdown(guide, md_images), encoding="utf-8")
    review = write_review(bundle_dir / "review.csv", guide)
    files = {step_id: out / relative for step_id, relative in md_images.items()}
    word, pdf, problems = _office(guide, files, out, word_template)
    if missing:
        problems = (f"{len(missing)} screenshot{'' if len(missing) == 1 else 's'} couldn't be exported "
                    f"({', '.join(missing)})", *problems)
    return ExportResult(html=html, markdown=markdown, review=review, word=word, pdf=pdf, problems=problems)
