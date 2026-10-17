"""A recording on disk: one folder holding guide.json, images/ and, after export, export/.

guide.json is rewritten (atomically) after every step, so a crash loses at most the step
being captured.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from PySide6.QtGui import QImage

from .model import Guide, GuideFormatError, guide_from_dict, guide_to_dict

MARKER = ".recordsteps"  # marks folders this app created; only those may be deleted
GUIDE_FILE = "guide.json"
FOLDER_NAME = "Record Steps"
PNG_QUALITY = 70  # Qt maps PNG quality to zlib effort; lower compression keeps capture quick
REPLACE_ATTEMPTS = 8
CLOUD_FOLDERS = ("onedrive", "dropbox", "google drive", "icloud")


class BundleError(RuntimeError):
    """A recording folder can't be read, written or removed."""


def default_root() -> Path:
    from PySide6.QtCore import QStandardPaths

    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home() / "Documents")
    return Path(docs) / FOLDER_NAME


def new_bundle_dir(root: Path, stamp: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    base = f"{stamp} Recording"
    for n in range(1, 1000):
        candidate = root / (base if n == 1 else f"{base} ({n})")
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        (candidate / "images").mkdir()
        (candidate / MARKER).write_text("Created by Record Steps. Safe to delete with the app.\n", encoding="utf-8")
        return candidate
    raise BundleError(f"couldn't create a new recording folder in {root}")


def save_image(bundle_dir: Path, step_id: str, image: QImage) -> str:
    relative = f"images/{step_id}.png"
    if not image.save(str(bundle_dir / relative), "PNG", PNG_QUALITY):
        raise BundleError(f"couldn't save {relative}")
    return relative


def save_guide(bundle_dir: Path, guide: Guide) -> Path:
    path = bundle_dir / GUIDE_FILE
    tmp = path.with_name(GUIDE_FILE + ".tmp")
    tmp.write_text(json.dumps(guide_to_dict(guide), indent=2, ensure_ascii=False), encoding="utf-8")
    replace_file(tmp, path)
    return path


def replace_file(src: Path, dst: Path, attempts: int = REPLACE_ATTEMPTS) -> None:
    """os.replace, retried briefly: antivirus and the search indexer often hold a file that was
    just written for a few milliseconds, and Windows refuses to swap it until they let go."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.02 * (attempt + 1))


def load_guide(bundle_dir: Path) -> Guide:
    path = Path(bundle_dir) / GUIDE_FILE
    try:
        return guide_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, GuideFormatError) as exc:
        raise BundleError(f"can't read {path}: {exc}") from exc


def cloud_synced(path: Path) -> bool:
    """True when the folder sits inside OneDrive, Dropbox, Google Drive or iCloud, which upload it."""
    return any(part.lower().startswith(CLOUD_FOLDERS) for part in Path(path).parts)


def remove_bundle(bundle_dir: Path, attempts: int = REPLACE_ATTEMPTS) -> None:
    """Delete a recording folder this app created. Retries while antivirus or the indexer still
    hold freshly written screenshots; any final failure is a BundleError naming the folder."""
    folder = Path(bundle_dir)
    if folder.is_symlink() or getattr(folder, "is_junction", lambda: False)():
        raise BundleError(f"{folder} is a link, not a recording; not deleting it")
    if not (folder / MARKER).is_file():
        raise BundleError(f"{folder} isn't a Record Steps recording; not deleting it")
    for attempt in range(attempts):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if attempt == attempts - 1:
                raise BundleError(f"couldn't delete {folder}: {exc}") from exc
            time.sleep(0.05 * (attempt + 1))
