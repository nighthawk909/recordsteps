"""The CLI, the app icon, the click flash, and edge cases around recording and the windows."""
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from recordsteps import bundle
from recordsteps.model import GuideFormatError, Rect, guide_from_dict, guide_to_dict
from recordsteps.recorder import Recorder, RecorderError
from tests.conftest import make_guide, make_step
from tests.test_pipeline import FakeDeps, save_button
from tests.test_recorder_ui import FakeListener, FakeRecorder

# ---------------------------------------------------------------- CLI


@pytest.fixture
def saved_bundle(tmp_path, screen_image):
    folder = bundle.new_bundle_dir(tmp_path, stamp="cli")
    bundle.save_image(folder, "step-001", screen_image)
    bundle.save_guide(folder, make_guide(make_step(1)))
    return folder


def test_cli_export_writes_the_files(saved_bundle, capsys, qapp):
    from recordsteps.__main__ import _cli

    assert _cli(["export", str(saved_bundle)]) == 0
    assert "guide.html" in capsys.readouterr().out
    assert (saved_bundle / "export" / "guide.md").exists()


def test_cli_stats_over_a_folder_of_recordings(saved_bundle, capsys, qapp):
    from recordsteps.__main__ import _cli

    assert _cli(["stats", str(saved_bundle.parent)]) == 0
    out = capsys.readouterr().out
    assert "1 recording" in out and "Named by UI Automation: 1" in out


def test_cli_stats_with_nothing_to_read(tmp_path, capsys, qapp):
    from recordsteps.__main__ import _cli

    assert _cli(["stats", str(tmp_path)]) == 1
    assert "No recordings" in capsys.readouterr().err


def test_cli_reports_a_broken_recording(tmp_path, capsys, qapp):
    from recordsteps.__main__ import _cli

    (tmp_path / "guide.json").write_text("[]", encoding="utf-8")
    assert _cli(["stats", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_without_a_command_opens_the_app(monkeypatch):
    import recordsteps.app
    from recordsteps.__main__ import _cli

    monkeypatch.setattr(recordsteps.app, "main", lambda: 42)
    assert _cli([]) == 42


def test_app_icon_and_recorder_factory(qapp, tmp_path):
    from recordsteps.app import _recorder_factory, build_icon

    assert not build_icon(64).isNull()
    rec = _recorder_factory(tmp_path, lambda g: None, lambda x, y: None)
    assert isinstance(rec, Recorder) and rec.bundle_dir == tmp_path


# ---------------------------------------------------------------- model and bundle edges


@pytest.mark.parametrize("data", [[], {"schema": 1, "id": "x", "title": "t", "created": "c", "steps": {}},
                                  {"schema": 1, "title": "t"}])
def test_from_dict_rejects_the_wrong_shape(data):
    with pytest.raises(GuideFormatError):
        guide_from_dict(data)


def test_from_dict_rejects_bad_rects_and_text():
    data = guide_to_dict(make_guide(make_step(1)))
    data["steps"][0]["monitor"] = [0, 0, "wide", 10]
    with pytest.raises(GuideFormatError):
        guide_from_dict(data)
    data = guide_to_dict(make_guide(make_step(1)))
    data["steps"][0]["app"] = 5
    with pytest.raises(GuideFormatError):
        guide_from_dict(data)


def test_default_root_is_in_documents(qapp):
    root = bundle.default_root()
    assert root.name == bundle.FOLDER_NAME


def test_save_image_failure_is_reported(tmp_path, screen_image):
    with pytest.raises(bundle.BundleError):
        bundle.save_image(tmp_path / "missing-folder", "step-001", screen_image)


def test_export_skips_missing_screenshots(saved_bundle, qapp):
    from recordsteps.exporter import export_bundle

    (saved_bundle / "images" / "step-001.png").unlink()
    result = export_bundle(saved_bundle)
    assert "data:image" not in result.html.read_text(encoding="utf-8")


# ---------------------------------------------------------------- recorder edges


def test_recorder_reports_capture_setup_failure(qapp, tmp_path):
    def broken():
        raise OSError("no screen")

    rec = Recorder(bundle.new_bundle_dir(tmp_path, stamp="x"), on_change=lambda g: None, on_click=lambda x, y: None,
                   deps_factory=broken, listener_factory=lambda cb: FakeListener(cb), own_pid=1)
    with pytest.raises(RecorderError, match="no screen"):
        rec.start()


def test_recorder_survives_a_failing_step_and_closes_deps(qapp, tmp_path):
    class Flaky(FakeDeps):
        closed = False

        def grab(self, monitor):
            if self.calls["grab"] == 0:
                self.calls["grab"] += 1
                raise OSError("screen busy")
            return super().grab(monitor)

        def close(self):
            Flaky.closed = True

    FakeListener.instances.clear()
    rec = Recorder(bundle.new_bundle_dir(tmp_path, stamp="x"), on_change=lambda g: None, on_click=lambda x, y: None,
                   deps_factory=lambda: Flaky(qapp, chain=save_button()),
                   listener_factory=lambda cb: FakeListener(cb), own_pid=1)
    rec.start()
    rec.start()  # second start is ignored
    FakeListener.instances[-1].press(t=1000)
    FakeListener.instances[-1].press(t=9000)
    guide = rec.stop()
    assert len(guide.steps) == 1 and Flaky.closed


def test_pause_and_resume_before_start_do_nothing(qapp, tmp_path):
    rec = Recorder(tmp_path, on_change=lambda g: None, on_click=lambda x, y: None,
                   deps_factory=lambda: FakeDeps(qapp), listener_factory=lambda cb: FakeListener(cb))
    rec.pause()
    rec.resume()
    assert rec.stop().steps == ()


# ---------------------------------------------------------------- flash


def test_flash_shows_briefly_at_the_mapped_point(qapp):
    from recordsteps.ui.flash import SIZE, ClickFlash, screen_map

    assert screen_map()
    flash = ClickFlash()
    flash.flash(100, 100)
    assert flash.isVisible()
    assert flash.grab().width() == SIZE
    QTest.qWait(250)
    assert not flash.isVisible()


# ---------------------------------------------------------------- pill details


def test_pill_paints_drags_and_animates(qapp):
    from recordsteps.ui.pill import RecordingPill

    pill = RecordingPill()
    pill.show_countdown(2)
    pill.show_recording()
    pill._animate = True
    pill._tick()
    assert 0.0 < pill._dot.alpha <= 1.0
    assert not pill.grab().isNull()
    start = pill.pos()
    QTest.mousePress(pill, Qt.LeftButton, pos=QPoint(4, 4))
    QTest.mouseMove(pill, QPoint(44, 24))
    QTest.mouseRelease(pill, Qt.LeftButton, pos=QPoint(44, 24))
    assert pill.pos() != start or pill.isVisible()
    pill.set_paused(True)
    pill.discard_button.click()
    pill.keep_button.click()
    assert pill.state == "paused"
    pill.hide()
    assert pill.state == "idle"


# ---------------------------------------------------------------- controller edges


def make_controller(qapp, tmp_path, *, countdown=0, factory=FakeRecorder, open_file=None):
    from recordsteps.exporter import ExportResult
    from recordsteps.ui.controller import Controller
    from recordsteps.ui.launcher import Launcher
    from recordsteps.ui.pill import RecordingPill

    class Flash:
        points = []

        def flash(self, x, y):
            self.points.append((x, y))

    def exporter(root):
        return ExportResult(html=Path(root) / "g.html", markdown=Path(root) / "g.md", review=Path(root) / "r.csv")

    return Controller(Launcher(recordings_dir=tmp_path), RecordingPill(), Flash(), recorder_factory=factory,
                      exporter=exporter, root=tmp_path, countdown_seconds=countdown,
                      open_file=open_file or (lambda p: None), run_async=lambda work, done: done(work()))


def test_countdown_ticks_then_records(qapp, tmp_path):
    ctl = make_controller(qapp, tmp_path, countdown=2)
    ctl.start_recording()
    assert ctl.pill.state == "countdown"
    ctl.start_recording()  # ignored while counting down
    ctl._tick()
    assert "1" in ctl.pill.status_text()
    ctl._tick()
    assert ctl.pill.state == "recording"


def test_countdown_can_be_skipped_or_cancelled(qapp, tmp_path):
    ctl = make_controller(qapp, tmp_path, countdown=3)
    ctl.start_recording()
    ctl.pill.start_now_button.click()
    assert ctl.pill.state == "recording"
    ctl.discard()
    ctl.start_recording()
    ctl.pill.cancel_button.click()
    assert ctl.pill.state == "idle" and ctl.launcher.isVisible()


def test_worker_events_update_the_pill_and_flash(qapp, tmp_path):
    ctl = make_controller(qapp, tmp_path)
    ctl.start_recording()
    ctl._bridge.changed.emit(make_guide(make_step(1), make_step(2)))
    ctl._bridge.clicked.emit(30, 40)
    qapp.processEvents()
    assert "2 steps" in ctl.pill.status_text()
    assert ctl.flash.points[-1] == (30, 40)


def test_controls_without_a_recording_do_nothing(qapp, tmp_path):
    ctl = make_controller(qapp, tmp_path)
    ctl.toggle_pause()
    ctl.stop()
    assert ctl.pill.state == "idle"


def test_open_failure_is_explained(qapp, tmp_path):
    def refuse(path):
        raise OSError("no app for .html")

    ctl = make_controller(qapp, tmp_path, open_file=refuse)
    ctl._open(tmp_path / "guide.html")
    assert "no app for .html" in ctl.launcher.result_text()


def test_discard_failure_still_returns_to_the_launcher(qapp, tmp_path):
    class Stuck(FakeRecorder):
        def discard(self):
            raise OSError("file in use")

    ctl = make_controller(qapp, tmp_path, factory=Stuck)
    ctl.start_recording()
    ctl.discard()
    assert "Couldn't delete the recording: file in use" in ctl.launcher.result_text()
    assert ctl.launcher.isVisible()


def test_launcher_buttons_emit_paths(qapp, tmp_path):
    from recordsteps.ui.launcher import Launcher

    launcher = Launcher(recordings_dir=tmp_path)
    opened = []
    launcher.open_path.connect(opened.append)
    launcher.show_result("done", html=tmp_path / "g.html", folder=tmp_path)
    launcher.open_guide_button.click()
    launcher.open_folder_button.click()
    launcher.recordings_button.click()
    assert opened == [tmp_path / "g.html", tmp_path, tmp_path]


def test_guide_json_is_pretty_printed(saved_bundle):
    text = (saved_bundle / "guide.json").read_text(encoding="utf-8")
    assert text.startswith("{\n") and json.loads(text)["steps"][0]["id"] == "step-001"


def test_rect_from_list_rejects_floats():
    with pytest.raises(GuideFormatError):
        Rect.from_list([0.5, 0, 1, 1])
