"""python -m recordsteps            open the app
python -m recordsteps export DIR   rebuild guide.html, guide.md and review.csv for a recording
python -m recordsteps stats DIR... Phase 0 numbers across recordings (or a folder of them)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__


def _bundles(paths: list[str]) -> list[Path]:
    from .bundle import GUIDE_FILE

    found: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if (p / GUIDE_FILE).is_file():
            found.append(p)
        elif p.is_dir():
            found += sorted(child for child in p.iterdir() if (child / GUIDE_FILE).is_file())
    return found


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="recordsteps", description="Record Steps (Phase 0 prototype)")
    parser.add_argument("--version", action="version", version=f"recordsteps {__version__}")
    sub = parser.add_subparsers(dest="command")
    export = sub.add_parser("export", help="rebuild the HTML, Markdown and review sheet for a recording")
    export.add_argument("folder")
    stats = sub.add_parser("stats", help="Phase 0 numbers across recordings")
    stats.add_argument("folders", nargs="*", help="recordings, or folders of recordings (default: Documents)")
    args = parser.parse_args(argv)

    if args.command is None:
        from .app import main

        return main()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    _app = QGuiApplication.instance() or QGuiApplication([])  # image encoding needs a Qt app
    from .bundle import BundleError, default_root, load_guide
    from .exporter import export_bundle
    from .stats import format_summary, read_review, summarize

    try:
        if args.command == "export":
            result = export_bundle(Path(args.folder))
            print(f"HTML:     {result.html}\nMarkdown: {result.markdown}\nReview:   {result.review}")
            return 0
        folders = _bundles(args.folders or [str(default_root())])
        if not folders:
            print("No recordings found.", file=sys.stderr)
            return 1
        guides = [load_guide(f) for f in folders]
        reviews = [read_review(f / "review.csv") for f in folders]
        print(f"{len(folders)} recording{'' if len(folders) == 1 else 's'}")
        print(format_summary(summarize(guides, reviews)))
        return 0
    except BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
