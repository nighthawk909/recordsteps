"""Wires the windows to a recording: countdown, record, pause, stop and build, or discard."""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from .. import bundle
from ..model import Guide
from ..recorder import RecorderError

log = logging.getLogger(__name__)
START_ERRORS = (RecorderError, bundle.BundleError, OSError)


class _Relay(QObject):
    """Carries a result from a worker thread to the GUI thread (queued signal)."""

    done = Signal(object)


_IN_FLIGHT: set[_Relay] = set()


def run_in_thread(work: Callable[[], Any], done: Callable[[Any], None]) -> None:
    """Run work() on a thread and hand its result, or the exception it raised, to done() on the
    GUI thread. done() is always called exactly once."""
    relay = _Relay()
    _IN_FLIGHT.add(relay)

    def deliver(value: Any) -> None:
        _IN_FLIGHT.discard(relay)
        done(value)

    def target() -> None:
        try:
            value = work()
        except BaseException as exc:  # handed to done() so the UI never waits forever
            log.exception("background work failed")
            value = exc
        relay.done.emit(value)

    relay.done.connect(deliver)
    threading.Thread(target=target, name="recordsteps-build", daemon=True).start()


def _startfile(path: Path) -> None:
    os.startfile(str(path))  # Windows only; looked up at call time so the module imports anywhere


@dataclass(frozen=True)
class _Outcome:
    guide: Guide | None
    result: Any
    error: str
    failed_steps: int = 0


class _Bridge(QObject):
    changed = Signal(object)  # Guide, from the capture worker
    clicked = Signal(int, int)  # physical point, from the capture worker


class Controller(QObject):
    def __init__(self, launcher, pill, flash, recorder_factory, exporter, root: Path, *,
                 countdown_seconds: int = 3, open_file: Callable[[Path], None] | None = None,
                 run_async: Callable[[Callable[[], Any], Callable[[Any], None]], None] = run_in_thread) -> None:
        super().__init__()
        self.launcher, self.pill, self.flash = launcher, pill, flash
        self._factory = recorder_factory
        self._exporter = exporter
        self._root = Path(root)
        self._countdown_seconds = countdown_seconds
        self._open_file = open_file or _startfile
        self._run_async = run_async
        self._recorder = None
        self._dir: Path | None = None
        self._notice = ""
        self._remaining = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._bridge = _Bridge()
        self._bridge.changed.connect(lambda g: self.pill.set_step_count(len(g.steps)))
        self._bridge.clicked.connect(self._flash)
        self._connect()

    def _connect(self) -> None:
        self.launcher.record_clicked.connect(self.start_recording)
        self.launcher.open_path.connect(self._open)
        self.pill.start_now_clicked.connect(self._begin)
        self.pill.cancel_clicked.connect(self._cancel_countdown)
        self.pill.pause_clicked.connect(self.toggle_pause)
        self.pill.stop_clicked.connect(self.stop)
        self.pill.discard_confirmed.connect(self.discard)

    # ------------------------------------------------------------------ countdown and start
    def start_recording(self) -> None:
        if self._recorder is not None or self._timer.isActive():
            return
        self.launcher.hide()
        if self._countdown_seconds <= 0:
            self._begin()
            return
        self._remaining = self._countdown_seconds
        self.pill.show_countdown(self._remaining)
        self._timer.start()

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._begin()
        else:
            self.pill.show_countdown(self._remaining)

    def _cancel_countdown(self) -> None:
        self._timer.stop()
        self._back_to_launcher("")

    def _begin(self) -> None:
        self._timer.stop()
        if self._recorder is not None:
            return
        self._notice = ""
        try:
            self._dir = bundle.new_bundle_dir(self._root, stamp=datetime.now().strftime("%Y-%m-%d %H%M"))
            recorder = self._factory(self._dir, self._bridge.changed.emit, self._bridge.clicked.emit)
            recorder.start()
        except START_ERRORS as exc:
            log.exception("recording didn't start")
            self._abandon_folder()
            self._back_to_launcher(f"Couldn't start recording. {exc}")
            return
        self._recorder = recorder
        self.pill.set_step_count(0)
        self.pill.show_recording()

    # ------------------------------------------------------------------ pause, stop, discard
    def toggle_pause(self) -> None:
        if self._recorder is None:
            return
        if self.pill.state != "paused":
            self._recorder.pause()
            self.pill.set_paused(True)
            return
        try:
            self._recorder.resume()
        except RecorderError as exc:
            self._notice = f"Recording stopped early: {exc} "
            self.stop()
            return
        self.pill.set_paused(False)

    def stop(self) -> None:
        recorder, folder = self._recorder, self._dir
        if recorder is None or folder is None:
            return
        self.pill.show_building()

        def work() -> _Outcome:
            failed = 0
            try:
                guide = recorder.stop()
                failed = getattr(recorder, "failed_steps", 0)
                if not guide.steps:
                    return _Outcome(guide, None, "", failed)
                return _Outcome(guide, self._exporter(folder), "", failed)
            except Exception as exc:  # shown to the user; screenshots stay on disk
                log.exception("building the guide failed")
                return _Outcome(None, None, str(exc), failed)

        self._run_async(work, self._finished)

    def _finished(self, outcome: Any) -> None:
        folder, self._recorder = self._dir, None
        if not isinstance(outcome, _Outcome):  # the build thread itself failed
            outcome = _Outcome(None, None, str(outcome))
        skipped = (f" {outcome.failed_steps} click{'' if outcome.failed_steps == 1 else 's'} couldn't be "
                   "captured (details in the log).") if outcome.failed_steps else ""
        if outcome.error:
            self._back_to_launcher(f"{self._notice}Couldn't build the guide: {outcome.error}. "
                                   f"The screenshots are in {folder}.{skipped}", folder=folder)
            return
        if outcome.guide is None or not outcome.guide.steps:
            self._abandon_folder()
            self._back_to_launcher(f"{self._notice}No steps were recorded, so nothing was saved.{skipped}")
            return
        steps = len(outcome.guide.steps)
        html = outcome.result.html
        text = f"{self._notice}{steps} step{'' if steps == 1 else 's'} recorded. Saved {html}.{skipped}"
        self._back_to_launcher(text, html=html, folder=folder)
        self._open(html)

    def discard(self) -> None:
        recorder, folder = self._recorder, self._dir
        self._recorder = None
        if recorder is None:
            self._back_to_launcher("")
            return
        try:
            recorder.discard()
        except Exception as exc:
            log.exception("discarding the recording failed")
            self._back_to_launcher(f"Couldn't delete the recording: {exc}. It's still in {folder}; delete that "
                                   "folder yourself.", folder=folder)
            return
        self._back_to_launcher("Discarded the recording. Nothing was saved.")

    # ------------------------------------------------------------------ helpers
    def _back_to_launcher(self, text: str, html: Path | None = None, folder: Path | None = None) -> None:
        self.pill.hide()
        self.launcher.show_result(text, html=html, folder=folder)
        self.launcher.show()
        self.launcher.raise_()

    def _abandon_folder(self) -> None:
        if self._dir is not None and self._dir.exists():
            try:
                bundle.remove_bundle(self._dir)
            except bundle.BundleError:
                log.exception("couldn't remove the unused recording folder")

    def _flash(self, x: int, y: int) -> None:
        if self.flash is not None:
            self.flash.flash(x, y)

    def _open(self, path: Path) -> None:
        try:
            self._open_file(Path(path))
        except OSError as exc:
            self.launcher.show_result(f"{self.launcher.result_text()} Couldn't open {path}: {exc}".strip(),
                                      html=None, folder=self._dir)
