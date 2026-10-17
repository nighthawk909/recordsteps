"""Phase 0 measurements: where step names came from, how fast capture was, and how many
titles a reviewer accepted (review.csv)."""
from __future__ import annotations

import csv
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .emphasis import plain
from .model import Guide, display_title

REVIEW_HEADER = ["step", "app", "window", "role", "element", "source", "title", "title_ok", "better_title"]
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_YES = {"y", "yes", "1", "true", "ok"}
_NO = {"n", "no", "0", "false"}


@dataclass(frozen=True)
class Summary:
    steps: int
    uia: int
    ocr: int
    unnamed: int
    skipped: int
    by_app: tuple[tuple[str, int, int], ...]  # app, steps, steps with a name
    median_capture_ms: float
    median_uia_ms: float
    p95_total_ms: float
    reviewed: int = 0
    titles_ok: int = 0


def summarize(guides: Sequence[Guide], reviews: Sequence[Mapping[str, str]] | None = None) -> Summary:
    steps = [s for g in guides for s in g.steps]
    kept = [s for s in steps if s.image]
    named = [s for s in kept if s.target.name]
    apps: Counter[str] = Counter(s.app or "Unknown" for s in steps)
    apps_named: Counter[str] = Counter(s.app or "Unknown" for s in named)
    answers = [a for review in (reviews or []) for a in review.values() if a in ("y", "n")]
    return Summary(
        steps=len(steps),
        uia=sum(1 for s in named if s.target.source == "uia"),
        ocr=sum(1 for s in named if s.target.source == "ocr"),
        unnamed=len(kept) - len(named),
        skipped=len(steps) - len(kept),
        by_app=tuple((app, n, apps_named[app]) for app, n in apps.most_common()),
        median_capture_ms=_median([s.timing.capture_ms for s in kept]),
        median_uia_ms=_median([s.timing.uia_ms for s in kept]),
        p95_total_ms=_p95([s.timing.total_ms for s in kept]),
        reviewed=len(answers),
        titles_ok=answers.count("y"),
    )


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 1) if values else 0.0


def _p95(values: list[float]) -> float:
    if len(values) < 2:
        return round(values[0], 1) if values else 0.0
    return round(statistics.quantiles(values, n=20, method="inclusive")[18], 1)


def _pct(part: int, whole: int) -> str:
    return f"{part * 100 / whole:.0f}%" if whole else "-"


def format_summary(s: Summary) -> str:
    named = s.uia + s.ocr
    lines = [
        f"{s.steps} steps ({s.skipped} in private windows, not captured)",
        f"  Named by UI Automation: {s.uia} ({_pct(s.uia, s.steps - s.skipped)})",
        f"  Named by reading the screen (OCR): {s.ocr} ({_pct(s.ocr, s.steps - s.skipped)})",
        f"  No name found: {s.unnamed} ({_pct(s.unnamed, s.steps - s.skipped)})",
        f"Capture speed: screenshot {s.median_capture_ms} ms median, UI Automation {s.median_uia_ms} ms median, "
        f"whole step {s.p95_total_ms} ms at the 95th percentile",
        "By app (steps, named):",
        *[f"  {app}: {n}, {k} named ({_pct(k, n)})" for app, n, k in s.by_app],
    ]
    if s.reviewed:
        lines.append(f"Review: {s.titles_ok} of {s.reviewed} titles accepted as-is ({_pct(s.titles_ok, s.reviewed)})")
    else:
        lines.append(f"Review: none yet. Fill in title_ok (y/n) in each review.csv. {named} titles to check.")
    return "\n".join(lines)


def _normalize(answer: str) -> str:
    value = (answer or "").strip().lower()
    return "y" if value in _YES else "n" if value in _NO else ""


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except FileNotFoundError:
        return []


def read_review(path: Path) -> dict[str, str]:
    """Step number -> 'y' or 'n', for the rows a reviewer answered."""
    answers = {row.get("step", ""): _normalize(row.get("title_ok", "")) for row in _read_rows(path)}
    return {step: a for step, a in answers.items() if a}


def _cell(value: str) -> str:
    """Text from other apps can start like a spreadsheet formula ('=HYPERLINK(...)'). A leading
    apostrophe makes Excel show it as text instead of running it."""
    return "'" + value if value.startswith(_FORMULA_START) else value


def write_review(path: Path, guide: Guide) -> Path:
    """One row per step for a reviewer to mark title_ok. Answers already in the file are kept."""
    previous = {row.get("step", ""): row for row in _read_rows(path)}
    rows = [REVIEW_HEADER]
    for number, step in enumerate(guide.steps, start=1):
        old = previous.get(str(number), {})
        generated = [step.app, step.window, step.target.role, step.target.name, step.target.source,
                     plain(display_title(step))]
        rows.append([str(number), *map(_cell, generated), old.get("title_ok", ""), old.get("better_title", "")])
    with path.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    return path
