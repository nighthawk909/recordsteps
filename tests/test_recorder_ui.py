import threading
import time
from pathlib import Path

import pytest

from recordsteps import bundle
from recordsteps.clicks import RawClick
from recordsteps.exporter import ExportResult
from recordsteps.recorder import Recorder, RecorderError
from tests.test_pipeline import FakeDeps, save_button

# ---------------------------------------------------------------- recorder threads


class FakeListener:
    instances: list["FakeListener"] = []

    def __init__(self, on_click, ok=True):
        self.on_click = on_click
        self.ok = ok
        self.running = False
        FakeListener.instances.append(self)

    def start(self):
        self.running = self.ok
        return self.ok

    def stop(self):
        self.running = False

    def press(self, x=1221, y=655, t=1000):
        if self.running:
            self.on_click(RawClick("left", x, y, t))


@pytest.fixture
def make_recorder(qapp, tmp_path):
    FakeListener.instances.clear()
    changes = []

    def build(ok=True):
        root = bundle.new_bundle_dir(tmp_path, stamp="rec")
        rec = Recorder(root, on_change=changes.append, on_click=lambda x, y: None,
                       deps_factory=lambda: FakeDeps(qapp, chain=save_button()),
                       listener_factory=lambda cb: FakeListener(cb, ok=ok), own_pid=1)
        return rec, root, changes

    return build


def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_recorder_turns_clicks_into_steps_on_its_worker(make_recorder):
    rec, root, changes = make_recorder()
    rec.start()
    listener = FakeListener.instances[-1]
    listener.press(t=1000)
    listener.press(t=5000)
    guide = rec.stop()
    assert len(guide.steps) == 2
    assert len(changes) == 2
    assert not listener.running
    assert bundle.load_guide(root) == guide


def test_pause_stops_listening_and_resume_listens_again(make_recorder):
    rec, _, _ = make_recorder()
    rec.start()
    rec.pause()
    assert not FakeListener.instances[-1].running
    FakeListener.instances[-1].press(t=1000)
    rec.resume()
    FakeListener.instances[-1].press(t=5000)
    assert len(rec.stop().steps) == 1


def test_start_failure_is_reported(make_recorder):
    rec, _, _ = make_recorder(ok=False)
    with pytest.raises(RecorderError):
        rec.start()


def test_discard_deletes_the_recording(make_recorder):
    rec, root, _ = make_recorder()
    rec.start()
    FakeListener.instances[-1].press()
    rec.discard()
    assert not Path(root).exists()


def test_stop_is_safe_to_call_twice(make_recorder):
    rec, _, _ = make_recorder()
    rec.start()
    first = rec.stop()
    assert rec.stop() == first


# ---------------------------------------------------------------- recording pill


def test_pill_walks_through_its_states(qapp):
    from recordsteps.ui.pill import RecordingPill

    pill = RecordingPill()
    pill.show_countdown(3)
    assert pill.state == "countdown" and "3" in pill.status_text()
    pill.show_recording()
    assert pill.state == "recording"
    pill.set_step_count(2)
    assert "2 steps" in pill.status_text()
    pill.set_paused(True)
    assert pill.state == "paused" and "Paused" in pill.status_text()
    pill.set_paused(False)
    pill.show_building()
    assert pill.state == "building"


def test_pill_asks_before_discarding(qapp):
    from recordsteps.ui.pill import RecordingPill

    pill = RecordingPill()
    pill.show_recording()
    confirmed = []
    pill.discard_confirmed.connect(lambda: confirmed.append(True))
    pill.discard_button.click()
    assert pill.state == "confirm_discard" and confirmed == []
    pill.keep_button.click()
    assert pill.state == "recording"
    pill.discard_button.click()
    pill.confirm_discard_button.click()
    assert confirmed == [True]


def test_pill_singular_step_wording(qapp):
    from recordsteps.ui.pill import RecordingPill

    pill = RecordingPill()
    pill.show_recording()
    pill.set_step_count(1)
    assert "1 step" in pill.status_text() and "1 steps" not in pill.status_text()


def test_elapsed_time_formats_as_minutes_and_seconds():
    from recordsteps.ui.pill import format_elapsed

    assert format_elapsed(0) == "00:00"
    assert format_elapsed(65_400) == "01:05"
    assert format_elapsed(3_600_000) == "60:00"


# ---------------------------------------------------------------- controller


class FakeRecorder:
    def __init__(self, root, on_change, on_click):
        self.root = Path(root)
        self.on_change = on_change
        self.calls = []

    def start(self):
        self.calls.append("start")

    def pause(self):
        self.calls.append("pause")

    def resume(self):
        self.calls.append("resume")

    def stop(self):
        self.calls.append("stop")
        from tests.conftest import make_guide, make_step

        return make_guide(make_step(1))

    def discard(self):
        self.calls.append("discard")
        bundle.remove_bundle(self.root)


@pytest.fixture
def controller(qapp, tmp_path):
    from recordsteps.ui.controller import Controller
    from recordsteps.ui.launcher import Launcher
    from recordsteps.ui.pill import RecordingPill

    made = []
    opened = []

    def factory(root, on_change, on_click):
        made.append(FakeRecorder(root, on_change, on_click))
        return made[-1]

    def exporter(root):
        return ExportResult(html=Path(root) / "export" / "guide.html", markdown=Path(root) / "export" / "guide.md",
                            review=Path(root) / "review.csv")

    ctl = Controller(Launcher(), RecordingPill(), flash=None, recorder_factory=factory, exporter=exporter,
                     root=tmp_path, countdown_seconds=0, open_file=opened.append,
                     run_async=lambda work, done: done(work()))
    return ctl, made, opened


def test_controller_records_then_builds_and_opens_the_guide(controller):
    ctl, made, opened = controller
    ctl.start_recording()
    assert made and made[0].calls == ["start"]
    assert ctl.pill.state == "recording"
    ctl.toggle_pause()
    ctl.toggle_pause()
    ctl.stop()
    assert made[0].calls == ["start", "pause", "resume", "stop"]
    assert opened == [made[0].root / "export" / "guide.html"]
    assert "guide.html" in ctl.launcher.result_text()


def test_controller_discard_returns_to_the_launcher(controller):
    ctl, made, opened = controller
    ctl.start_recording()
    ctl.discard()
    assert made[0].calls == ["start", "discard"]
    assert not made[0].root.exists()
    assert opened == []
    assert "Discarded" in ctl.launcher.result_text()


def test_controller_reports_a_failed_start(qapp, tmp_path):
    from recordsteps.ui.controller import Controller
    from recordsteps.ui.launcher import Launcher
    from recordsteps.ui.pill import RecordingPill

    class Broken(FakeRecorder):
        def start(self):
            raise RecorderError("Windows refused to share mouse clicks.")

    ctl = Controller(Launcher(), RecordingPill(), flash=None, recorder_factory=Broken, exporter=lambda r: None,
                     root=tmp_path, countdown_seconds=0, open_file=lambda p: None,
                     run_async=lambda work, done: done(work()))
    ctl.start_recording()
    assert "Windows refused" in ctl.launcher.result_text()
    assert not ctl.pill.isVisible()


def test_controller_reports_a_failed_export(qapp, tmp_path):
    from recordsteps.ui.controller import Controller
    from recordsteps.ui.launcher import Launcher
    from recordsteps.ui.pill import RecordingPill

    def exporter(root):
        raise OSError("disk full")

    ctl = Controller(Launcher(), RecordingPill(), flash=None, recorder_factory=FakeRecorder, exporter=exporter,
                     root=tmp_path, countdown_seconds=0, open_file=lambda p: None,
                     run_async=lambda work, done: done(work()))
    ctl.start_recording()
    ctl.stop()
    assert "disk full" in ctl.launcher.result_text()


def test_run_in_thread_delivers_on_the_gui_thread(qapp):
    from PySide6.QtCore import QCoreApplication

    from recordsteps.ui.controller import run_in_thread

    seen = []
    run_in_thread(lambda: threading.current_thread().name, seen.append)
    assert wait_for_events(lambda: seen, qapp)
    assert seen[0] != threading.current_thread().name
    QCoreApplication.processEvents()


def wait_for_events(predicate, qapp, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False
