"""Regression tests for the code and security review findings."""
import csv
import json
import time
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from recordsteps import bundle
from recordsteps.apps import is_private
from recordsteps.export_md import render_markdown
from recordsteps.model import PASSWORD_NOTE, GuideFormatError, Rect, guide_from_dict, guide_to_dict
from recordsteps.recorder import Recorder, RecorderError
from recordsteps.stats import write_review
from recordsteps.targets import ElementInfo
from tests.conftest import make_guide, make_step
from tests.test_pipeline import FakeDeps, click, new_session, save_button
from tests.test_recorder_ui import FakeListener, FakeRecorder

SCHEMA = json.loads((Path(__file__).parents[1] / "recordsteps" / "guide.schema.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- crafted guide.json can't escape the bundle


@pytest.mark.parametrize("field, value", [
    ("id", "..\\..\\outside\\planted"),
    ("id", "step-1"),
    ("image", "C:/Windows/win.ini"),
    ("image", "\\\\server\\share\\x.png"),
    ("image", "images/../../secret.png"),
    ("image", "images/step-002.png"),  # must match the step's own id
])
def test_step_ids_and_image_paths_are_validated(field, value):
    data = guide_to_dict(make_guide(make_step(1)))
    data["steps"][0][field] = value
    with pytest.raises(GuideFormatError):
        guide_from_dict(data)


@pytest.mark.parametrize("field, value", [
    ("id", "..\\..\\outside\\planted"),
    ("image", "C:/Windows/win.ini"),
    ("image", "\\\\server\\share\\x.png"),
    ("image", "images/../../secret.png"),
])
def test_the_schema_documents_the_same_path_rules(field, value):
    data = guide_to_dict(make_guide(make_step(1)))
    data["steps"][0][field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, SCHEMA)


def test_edited_title_must_be_text_or_null():
    data = guide_to_dict(make_guide(make_step(1)))
    data["steps"][0]["title"]["edited"] = 5
    with pytest.raises(GuideFormatError):
        guide_from_dict(data)


def test_exporter_refuses_paths_outside_the_bundle(tmp_path):
    from recordsteps.exporter import inside

    assert inside(tmp_path, "images/step-001.png") == tmp_path / "images" / "step-001.png"
    with pytest.raises(bundle.BundleError):
        inside(tmp_path, "../elsewhere.png")
    with pytest.raises(bundle.BundleError):
        inside(tmp_path, "C:/Windows/win.ini")


# ---------------------------------------------------------------- sensitive content


def test_password_fields_get_no_screenshot(qapp, tmp_path):
    chain = (ElementInfo("", "Text"), ElementInfo("Password", "Edit", Rect(10, 10, 200, 24), is_password=True))
    deps = FakeDeps(qapp, chain=chain)
    session, root = new_session(deps, tmp_path)
    step = session.handle(click(x=20, y=20)).steps[0]
    assert step.image == "" and step.note == PASSWORD_NOTE
    assert step.title == "Click the **Password** field in Excel"
    assert not list((root / "images").iterdir())


def test_text_fields_are_never_read_off_the_screen(qapp, tmp_path):
    from recordsteps.ocr_target import Word

    deps = FakeDeps(qapp, chain=(ElementInfo("", "Edit", Rect(800, 490, 300, 24)),),
                    words=(Word("hunter2", 220, 70, 60, 18, 0),))
    session, _ = new_session(deps, tmp_path)
    step = session.handle(click(x=900, y=500)).steps[0]
    assert deps.calls["ocr"] == 0
    assert "hunter2" not in step.title and step.target.source == "none"


def test_a_private_window_anywhere_on_the_monitor_blocks_the_screenshot(qapp, tmp_path):
    class Watched(FakeDeps):
        def private_window_on(self, monitor):
            return True

    deps = Watched(qapp, chain=save_button())
    session, _ = new_session(deps, tmp_path)
    step = session.handle(click()).steps[0]
    assert step.image == "" and deps.calls["grab"] == 0


@pytest.mark.parametrize("title", ["Tor Browser", "Inbox - Brave - Private Window", "Google - InPrivate"])
def test_more_private_window_markers(title):
    assert is_private(title)


def test_review_csv_neutralises_spreadsheet_formulas(tmp_path):
    step = make_step(1, window='=HYPERLINK("http://x","click")', app="+cmd", target=make_step(1).target)
    path = write_review(tmp_path / "review.csv", make_guide(step))
    row = list(csv.reader(path.open(encoding="utf-8")))[1]
    assert row[2].startswith("'=") and row[1].startswith("'+")


def test_markdown_alt_text_has_no_markup_or_line_breaks():
    step = make_step(1, title='Click **<b x="1">\nnext**')
    md = render_markdown(make_guide(step), {"step-001": "images/step-001.png"})
    alt = md.split("![", 1)[1].split("](", 1)[0]
    assert "<" not in alt and '"' not in alt and "\n" not in alt


# ---------------------------------------------------------------- deletion


def test_remove_bundle_retries_while_files_are_held(tmp_path, monkeypatch):
    folder = bundle.new_bundle_dir(tmp_path, stamp="x")
    real = bundle.shutil.rmtree
    failures = iter([PermissionError("held"), PermissionError("held")])

    def flaky(path, *a, **k):
        err = next(failures, None)
        if err:
            raise err
        real(path)

    monkeypatch.setattr(bundle.shutil, "rmtree", flaky)
    monkeypatch.setattr(bundle.time, "sleep", lambda s: None)
    bundle.remove_bundle(folder)
    assert not folder.exists()


def test_remove_bundle_reports_failure_as_a_bundle_error(tmp_path, monkeypatch):
    folder = bundle.new_bundle_dir(tmp_path, stamp="x")

    def held(path, *a, **k):
        raise PermissionError("held")

    monkeypatch.setattr(bundle.shutil, "rmtree", held)
    monkeypatch.setattr(bundle.time, "sleep", lambda s: None)
    with pytest.raises(bundle.BundleError, match="held"):
        bundle.remove_bundle(folder)


def test_cloud_synced_folders_are_detected():
    assert bundle.cloud_synced(Path(r"C:\Users\x\OneDrive - Contoso\Documents\Record Steps"))
    assert not bundle.cloud_synced(Path(r"C:\Users\x\Documents\Record Steps"))


# ---------------------------------------------------------------- controller failure paths


def controller(qapp, tmp_path, factory=FakeRecorder, open_file=None):
    from tests.test_app_cli_edges import make_controller

    return make_controller(qapp, tmp_path, factory=factory, open_file=open_file)


def test_failed_discard_tells_the_truth(qapp, tmp_path):
    class Held(FakeRecorder):
        def discard(self):
            raise bundle.BundleError("file in use")

    ctl = controller(qapp, tmp_path, factory=Held)
    ctl.start_recording()
    ctl.discard()
    text = ctl.launcher.result_text()
    assert "couldn't delete" in text.lower() and "file in use" in text and "Nothing was saved" not in text


def test_any_start_failure_returns_to_the_launcher(qapp, tmp_path):
    class Exploding(FakeRecorder):
        def start(self):
            raise OSError("Documents is offline")

    ctl = controller(qapp, tmp_path, factory=Exploding)
    ctl.start_recording()
    assert "Documents is offline" in ctl.launcher.result_text()
    assert ctl.launcher.isVisible() and not ctl.pill.isVisible()


def test_resume_failure_stops_and_explains(qapp, tmp_path):
    class Deaf(FakeRecorder):
        def resume(self):
            raise RecorderError("Windows stopped sharing mouse clicks.")

        def stop(self):
            self.calls.append("stop")
            return make_guide(make_step(1))

    ctl = controller(qapp, tmp_path, factory=Deaf)
    ctl.start_recording()
    ctl.toggle_pause()
    ctl.toggle_pause()
    assert "Windows stopped sharing mouse clicks" in ctl.launcher.result_text()


def test_empty_recordings_are_not_opened(qapp, tmp_path):
    class Empty(FakeRecorder):
        def stop(self):
            return make_guide()

    opened = []
    ctl = controller(qapp, tmp_path, factory=Empty, open_file=opened.append)
    ctl.start_recording()
    ctl.stop()
    assert opened == [] and "No steps were recorded" in ctl.launcher.result_text()


def test_open_failure_after_building_is_explained(qapp, tmp_path):
    class OneStep(FakeRecorder):
        def stop(self):
            return make_guide(make_step(1))

    def refuse(path):
        raise OSError("no browser")

    ctl = controller(qapp, tmp_path, factory=OneStep, open_file=refuse)
    ctl.start_recording()
    ctl.stop()
    assert "no browser" in ctl.launcher.result_text()


def test_run_in_thread_delivers_exceptions(qapp):
    from recordsteps.ui.controller import run_in_thread
    from tests.test_recorder_ui import wait_for_events

    seen = []
    run_in_thread(lambda: 1 / 0, seen.append)
    assert wait_for_events(lambda: seen, qapp)
    assert isinstance(seen[0], ZeroDivisionError)


def test_launcher_warns_about_cloud_synced_folders(qapp):
    from recordsteps.ui.launcher import Launcher

    launcher = Launcher(recordings_dir=Path(r"C:\Users\x\OneDrive\Documents\Record Steps"))
    assert "OneDrive" in launcher.location_text()


# ---------------------------------------------------------------- recorder worker robustness


def make_recorder(qapp, tmp_path, deps, on_change=lambda g: None):
    FakeListener.instances.clear()
    return Recorder(bundle.new_bundle_dir(tmp_path, stamp="r"), on_change=on_change, on_click=lambda x, y: None,
                    deps_factory=lambda: deps, listener_factory=lambda cb: FakeListener(cb), own_pid=1)


def test_a_failing_change_callback_does_not_kill_the_worker(qapp, tmp_path):
    calls = []

    def bad(guide):
        calls.append(guide)
        raise RuntimeError("GUI gone")

    rec = make_recorder(qapp, tmp_path, FakeDeps(qapp, chain=save_button()), on_change=bad)
    rec.start()
    FakeListener.instances[-1].press(t=1000)
    FakeListener.instances[-1].press(t=9000)
    assert len(rec.stop().steps) == 2 and len(calls) == 2


def test_failed_steps_are_counted(qapp, tmp_path):
    class Broken(FakeDeps):
        def grab(self, monitor):
            raise OSError("screen busy")

    rec = make_recorder(qapp, tmp_path, Broken(qapp, chain=save_button()))
    rec.start()
    FakeListener.instances[-1].press()
    rec.stop()
    assert rec.failed_steps == 1


def test_discard_drops_clicks_still_waiting(qapp, tmp_path):
    class Slow(FakeDeps):
        def grab(self, monitor):
            time.sleep(0.2)
            return super().grab(monitor)

    deps = Slow(qapp, chain=save_button())
    rec = make_recorder(qapp, tmp_path, deps)
    rec.start()
    for i in range(6):
        FakeListener.instances[-1].press(t=1000 + i * 5000)
    rec.discard()
    assert deps.calls["grab"] <= 2


def test_resume_reports_a_listener_that_will_not_start(qapp, tmp_path):
    rec = make_recorder(qapp, tmp_path, FakeDeps(qapp))
    rec.start()
    rec.pause()
    FakeListener.instances[-1].ok = False
    with pytest.raises(RecorderError):
        rec.resume()
    rec.stop()


def test_listener_start_failure_is_not_remembered_as_success(monkeypatch):
    from recordsteps.win import rawinput as ri

    listener = ri.MouseListener(lambda c: None)
    listener._ok = True  # a stale success from an earlier session
    monkeypatch.setattr(ri, "_user32", SimpleNamespace())  # every Win32 call fails
    started = time.monotonic()
    assert listener.start() is False
    assert time.monotonic() - started < 2.0
    listener.stop()
