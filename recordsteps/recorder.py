"""A recording session with its threads: the click listener feeds a queue, one worker turns
clicks into steps. The listener, and the deps' rolling frame buffer if they have one, only run
between start/resume and pause/stop."""
from __future__ import annotations

import logging
import os
import queue
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from . import bundle
from .clicks import RawClick
from .model import Guide
from .pipeline import Session

log = logging.getLogger(__name__)
_STOP = object()
READY_TIMEOUT_S = 15.0
STOP_TIMEOUT_S = 30.0


class RecorderError(RuntimeError):
    """Recording couldn't start; the message is shown to the user."""


class Recorder:
    def __init__(self, bundle_dir: Path, *, on_change: Callable[[Guide], None], on_click: Callable[[int, int], None],
                 deps_factory: Callable[[], Any], listener_factory: Callable[[Callable[[RawClick], None]], Any],
                 own_pid: int | None = None, double_click: tuple[int, int, int] = (500, 4, 4),
                 title: str = "Recorded steps") -> None:
        self._dir = Path(bundle_dir)
        self._on_change = on_change
        self._on_click = on_click
        self._deps_factory = deps_factory
        self._listener_factory = listener_factory
        self._own_pid = os.getpid() if own_pid is None else own_pid
        self._double = double_click
        self._title = title
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._worker: threading.Thread | None = None
        self._listener: Any = None
        self._frames: Any = None  # the deps' frame buffer (start/stop), if they have one
        self._session: Session | None = None
        self._error: BaseException | None = None
        self._final: Guide | None = None
        self._paused = False
        self._discarding = False
        self.failed_steps = 0  # clicks that couldn't become steps (see the log)

    @property
    def bundle_dir(self) -> Path:
        return self._dir

    def start(self) -> None:
        if self._worker is not None:
            return
        self._worker = threading.Thread(target=self._run, name="recordsteps-worker", daemon=True)
        self._worker.start()
        if not self._ready.wait(READY_TIMEOUT_S) or self._error is not None:
            self._shutdown_worker()
            raise RecorderError(f"Couldn't prepare screen capture: {self._error or 'timed out'}")
        self._start_frames()
        try:
            self._listener = self._listener_factory(self._enqueue)
            listening = self._listener.start()
        except BaseException:
            self._abandon_start()
            raise
        if not listening:
            self._abandon_start()
            raise RecorderError("Windows didn't let Record Steps listen for mouse clicks.")

    def _abandon_start(self) -> None:
        """Recording didn't start: nothing may keep capturing."""
        self._stop_frames()
        self._shutdown_worker()

    def pause(self) -> None:
        if self._listener is not None and not self._paused:
            self._paused = True
            self._listener.stop()
            self._stop_frames()

    def resume(self) -> None:
        if self._listener is not None and self._paused:
            self._start_frames()
            if not self._listener.start():
                self._stop_frames()
                raise RecorderError("Windows stopped sharing mouse clicks with Record Steps.")
            self._paused = False

    def stop(self) -> Guide:
        """Stop listening, finish the clicks already queued, and return the guide."""
        if self._final is not None:
            return self._final
        if self._listener is not None:
            self._listener.stop()
        self._shutdown_worker()  # queued clicks still find their frames
        self._stop_frames()
        self._final = self._session.guide if self._session else self._empty_guide()
        return self._final

    def discard(self) -> None:
        """Stop, skip any clicks still waiting, and delete the recording (BundleError if it can't)."""
        self._discarding = True
        self.stop()
        bundle.remove_bundle(self._dir)

    def _start_frames(self) -> None:
        if self._frames is not None:
            try:
                self._frames.start()
            except Exception:  # steps fall back to screenshots taken after the click
                log.exception("the frame buffer didn't start")

    def _stop_frames(self) -> None:
        if self._frames is not None:
            try:
                self._frames.stop()
            except Exception:
                log.exception("the frame buffer didn't stop")

    # ------------------------------------------------------------------ worker thread
    def _enqueue(self, click: RawClick) -> None:
        if not self._paused:
            self._queue.put(click)

    def _empty_guide(self) -> Guide:
        stamp = datetime.now().isoformat(timespec="seconds")
        return Guide(id=self._dir.name, title=self._title, created=stamp)

    def _shutdown_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            self._queue.put(_STOP)
            self._worker.join(STOP_TIMEOUT_S)
            if self._worker.is_alive():
                log.error("capture worker didn't finish in %ss", STOP_TIMEOUT_S)

    def _run(self) -> None:
        deps = None
        try:
            deps = self._deps_factory()
            self._frames = getattr(deps, "frame_buffer", None)
            guide = self._empty_guide()
            self._session = Session(guide, deps, own_pid=self._own_pid, bundle_dir=self._dir,
                                    double_click=self._double, on_accept=lambda c: self._on_click(c.x, c.y))
            bundle.save_guide(self._dir, guide)
        except Exception as exc:
            log.exception("capture setup failed")
            self._error = exc
            self._ready.set()
            _close(deps)
            return
        self._ready.set()
        try:
            while (item := self._queue.get()) is not _STOP:
                if not self._discarding:
                    self._process(item)
        finally:
            _close(deps)

    def _process(self, click: RawClick) -> None:
        try:
            changed = self._session.handle(click)
        except Exception:  # one bad step must not end the recording
            self.failed_steps += 1
            log.exception("couldn't capture a step")
            return
        if changed is None:
            return
        try:
            self._on_change(changed)
        except Exception:
            log.exception("the window didn't take the step update")


def _close(deps: Any) -> None:
    close = getattr(deps, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            log.exception("closing capture resources failed")
