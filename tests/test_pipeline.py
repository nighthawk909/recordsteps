import itertools
import logging

import pytest
from PySide6.QtGui import QColor, QImage

from recordsteps import bundle
from recordsteps.clicks import RawClick
from recordsteps.frames import Pick
from recordsteps.model import PRIVATE_NOTE, Guide, Rect
from recordsteps.ocr_target import Word
from recordsteps.pipeline import Session, WindowHit, capture_step
from recordsteps.targets import ElementInfo

OWN_PID = 4242
MON = Rect(0, 0, 1920, 1080)


class FakeDeps:
    def __init__(self, qapp, *, hit=None, chain=(), words=(), monitor=MON, chain_error=None, ocr_error=None,
                 buffered=None):
        self.hit = hit or WindowHit(pid=100, title="Q3 forecast.xlsx - Excel", process_path=r"C:\Office\EXCEL.EXE")
        self.chain = chain
        self.words = words
        self.monitor = monitor
        self.chain_error = chain_error
        self.ocr_error = ocr_error
        self.buffered = buffered  # a Pick from the frame buffer, or an exception to raise
        self.calls = {"grab": 0, "chain": 0, "ocr": 0, "frame_before": []}

    def window_at(self, x, y):
        return self.hit

    def monitor_at(self, x, y):
        return self.monitor

    def dpi_at(self, x, y):
        return 144

    def grab(self, monitor):
        self.calls["grab"] += 1
        img = QImage(monitor.w, monitor.h, QImage.Format_RGB32)
        img.fill(QColor("#FAFAFA"))
        return img

    def frame_before(self, monitor, t_ms):
        self.calls["frame_before"].append((monitor, t_ms))
        if isinstance(self.buffered, Exception):
            raise self.buffered
        return self.buffered

    def chain_at(self, x, y):
        self.calls["chain"] += 1
        if self.chain_error:
            raise self.chain_error
        return self.chain

    def ocr_words(self, image):
        self.calls["ocr"] += 1
        if self.ocr_error:
            raise self.ocr_error
        return self.words

    def private_window_on(self, monitor):
        return False

    def app_name(self, process_path):
        return {"EXCEL.EXE": "Excel", "mstsc.exe": "Remote Desktop"}.get(process_path.split("\\")[-1], "App")


def save_button():
    return (ElementInfo("Save", "Button", Rect(1184, 642, 76, 28)), ElementInfo("Book1 - Excel", "Window"))


def new_session(deps, tmp_path, **kw):
    root = bundle.new_bundle_dir(tmp_path, stamp="test")
    guide = Guide(id="g", title="Recorded steps", created="2026-10-17T09:00:00")
    session = Session(guide, deps, own_pid=OWN_PID, bundle_dir=root, now=lambda: "2026-10-17T09:30:00", **kw)
    return session, root


def click(x=1221, y=655, t=1000, button="left"):
    return RawClick(button=button, x=x, y=y, t_ms=t)


def test_a_click_on_a_named_button_becomes_a_titled_step(qapp, tmp_path):
    deps = FakeDeps(qapp, chain=save_button())
    session, root = new_session(deps, tmp_path)
    guide = session.handle(click())
    step = guide.steps[0]
    assert step.title == "Click **Save** in Excel"
    assert (step.app, step.process, step.dpi) == ("Excel", "EXCEL.EXE", 144)
    assert step.target.source == "uia" and step.target.bbox == Rect(1184, 642, 76, 28)
    assert step.click == (1221, 655) and step.image == "images/step-001.png"
    assert (root / "images" / "step-001.png").exists()
    assert bundle.load_guide(root) == guide  # saved after every step
    assert step.timing.total_ms >= 0


def test_clicks_on_our_own_windows_are_ignored(qapp, tmp_path):
    deps = FakeDeps(qapp, hit=WindowHit(pid=OWN_PID, title="Recording", process_path="python.exe"))
    session, _ = new_session(deps, tmp_path)
    assert session.handle(click()) is None
    assert session.guide.steps == () and deps.calls["grab"] == 0


def test_second_quick_click_turns_the_step_into_a_double_click(qapp, tmp_path):
    deps = FakeDeps(qapp, chain=(ElementInfo("report.xlsx", "ListItem", Rect(100, 100, 300, 24)),))
    session, root = new_session(deps, tmp_path, double_click=(500, 4, 4))
    session.handle(click(x=120, y=110, t=1000))
    guide = session.handle(click(x=121, y=111, t=1200))
    assert len(guide.steps) == 1
    assert guide.steps[0].action == "double_click"
    assert guide.steps[0].title == "Double-click **report.xlsx** in Excel"
    assert deps.calls["grab"] == 1
    third = session.handle(click(x=121, y=111, t=1300))
    assert len(third.steps) == 2  # a third click starts a new step, not a triple-click


def test_right_clicks_are_their_own_steps(qapp, tmp_path):
    deps = FakeDeps(qapp, chain=save_button())
    session, _ = new_session(deps, tmp_path)
    guide = session.handle(click(button="right"))
    assert guide.steps[0].action == "right_click"
    assert guide.steps[0].title.startswith("Right-click **Save**")


def test_private_windows_are_recorded_without_screenshot_or_title(qapp, tmp_path):
    hit = WindowHit(pid=100, title="Bank - Microsoft Edge [InPrivate]", process_path="msedge.exe")
    deps = FakeDeps(qapp, hit=hit, chain=save_button())
    session, root = new_session(deps, tmp_path)
    step = session.handle(click()).steps[0]
    assert step.image == "" and step.window == "" and step.note == PRIVATE_NOTE
    assert step.target.name == "" and step.title == "Click in a private window"
    assert deps.calls["grab"] == 0 and deps.calls["chain"] == 0
    assert not list((root / "images").iterdir())


def ocr_words_at_click():
    # The pipeline OCRs a box centred on the click; this word sits on that centre.
    return (Word("Submit", 220, 70, 60, 18, 0),)


def test_remote_sessions_skip_ui_automation_and_read_the_screen(qapp, tmp_path):
    hit = WindowHit(pid=100, title="server01 - Remote Desktop Connection", process_path=r"C:\Windows\mstsc.exe")
    deps = FakeDeps(qapp, hit=hit, words=ocr_words_at_click())
    session, _ = new_session(deps, tmp_path)
    step = session.handle(click(x=900, y=500)).steps[0]
    assert deps.calls["chain"] == 0
    assert step.target.source == "ocr" and step.target.name == "Submit"
    assert step.target.bbox is not None and step.target.bbox.contains(900, 500)
    assert step.title == "Click **Submit** in Remote Desktop"


def test_ui_automation_failure_falls_back_to_ocr(qapp, tmp_path):
    deps = FakeDeps(qapp, chain_error=OSError("COM said no"), words=ocr_words_at_click())
    session, _ = new_session(deps, tmp_path)
    step = session.handle(click(x=900, y=500)).steps[0]
    assert step.target.source == "ocr"


def test_unnamed_and_unreadable_targets_point_at_the_window(qapp, tmp_path):
    deps = FakeDeps(qapp, chain=(ElementInfo("", "Pane"),), ocr_error=RuntimeError("no OCR language"))
    session, _ = new_session(deps, tmp_path)
    step = session.handle(click()).steps[0]
    assert step.target.source == "none"
    assert step.title == "Click in **Q3 forecast.xlsx - Excel**"


def test_boxes_that_cover_the_screen_are_dropped(qapp, tmp_path):
    deps = FakeDeps(qapp, chain=(ElementInfo("Canvas", "Button", Rect(0, 0, 1900, 1000)),))
    session, _ = new_session(deps, tmp_path)
    assert session.handle(click()).steps[0].target.bbox is None


def test_coordinates_are_relative_to_the_clicked_monitor(qapp, tmp_path):
    second = Rect(1920, 0, 1920, 1080)
    deps = FakeDeps(qapp, monitor=second, chain=(ElementInfo("Save", "Button", Rect(2000, 100, 80, 30)),))
    session, _ = new_session(deps, tmp_path)
    step = session.handle(click(x=2010, y=110)).steps[0]
    assert step.click == (90, 110)
    assert step.target.bbox == Rect(80, 100, 80, 30)
    assert step.monitor == second


def test_accepted_clicks_are_reported_for_the_flash(qapp, tmp_path):
    seen = []
    deps = FakeDeps(qapp, chain=save_button())
    session, _ = new_session(deps, tmp_path, on_accept=seen.append)
    session.handle(click())
    assert seen == [click()]


def test_password_fields_are_flagged(qapp, tmp_path):
    deps = FakeDeps(qapp, chain=(ElementInfo("Password", "Edit", Rect(10, 10, 200, 24), is_password=True),))
    session, _ = new_session(deps, tmp_path)
    step = session.handle(click(x=20, y=20)).steps[0]
    assert step.target.is_password and step.title == "Click the **Password** field in Excel"


@pytest.mark.parametrize("n", [3])
def test_steps_are_numbered_in_order(qapp, tmp_path, n):
    deps = FakeDeps(qapp, chain=save_button())
    session, _ = new_session(deps, tmp_path)
    for i in range(n):
        session.handle(click(t=1000 + i * 2000))
    assert [s.id for s in session.guide.steps] == ["step-001", "step-002", "step-003"]
    assert [s.title for s in session.guide.steps] == ["Click **Save** in Excel", "Click **Save**", "Click **Save**"]


# ---------------------------------------------------------------- frames from before the click


def before_click_frame(color="#203040", age_ms=420.0, gap_ms=35.0):
    img = QImage(MON.w, MON.h, QImage.Format_RGB32)
    img.fill(QColor(color))
    return Pick(image=img, age_ms=age_ms, gap_ms=gap_ms)


def test_a_buffered_frame_from_before_the_click_is_the_screenshot(qapp, tmp_path, caplog):
    deps = FakeDeps(qapp, chain=save_button(), buffered=before_click_frame())
    session, root = new_session(deps, tmp_path)
    readings = itertools.count(0.0, 0.0001)  # each clock reading 0.1 ms after the last
    with caplog.at_level(logging.INFO, logger="recordsteps.pipeline"):
        step, image = capture_step(click(t=777), deps.hit, "step-001", deps, now="2026-10-17T09:30:00",
                                   clock=lambda: next(readings))
    assert deps.calls["grab"] == 0 and deps.calls["frame_before"] == [(MON, 777)]
    assert image.pixelColor(5, 5).name() == "#203040"
    assert step.timing.capture_ms == 0.1  # one clock reading: nothing was grabbed
    assert "420 ms" in caplog.text and "35 ms" in caplog.text
    session.handle(click(t=5000))
    assert QImage(str(root / "images" / "step-001.png")).pixelColor(5, 5).name() == "#203040"


def test_without_a_buffered_frame_the_screen_is_grabbed_after_the_click(qapp, tmp_path, caplog):
    deps = FakeDeps(qapp, chain=save_button())
    session, _ = new_session(deps, tmp_path)
    with caplog.at_level(logging.INFO, logger="recordsteps.pipeline"):
        session.handle(click())
    assert deps.calls["grab"] == 1 and len(deps.calls["frame_before"]) == 1
    assert "after it" in caplog.text


def test_a_failing_frame_buffer_falls_back_to_a_screenshot(qapp, tmp_path):
    deps = FakeDeps(qapp, chain=save_button(), buffered=RuntimeError("buffer broke"))
    session, _ = new_session(deps, tmp_path)
    step = session.handle(click()).steps[0]
    assert deps.calls["grab"] == 1 and step.image == "images/step-001.png"


def test_buffered_frames_are_never_asked_for_when_a_private_window_is_on_screen(qapp, tmp_path):
    class Watched(FakeDeps):
        def private_window_on(self, monitor):
            return True

    deps = Watched(qapp, chain=save_button(), buffered=before_click_frame())
    session, _ = new_session(deps, tmp_path)
    step = session.handle(click()).steps[0]
    assert step.image == "" and deps.calls["frame_before"] == [] and deps.calls["grab"] == 0


def test_a_buffered_frame_of_a_password_field_is_not_saved(qapp, tmp_path):
    chain = (ElementInfo("Password", "Edit", Rect(10, 10, 200, 24), is_password=True),)
    deps = FakeDeps(qapp, chain=chain, buffered=before_click_frame())
    session, root = new_session(deps, tmp_path)
    step = session.handle(click(x=20, y=20)).steps[0]
    assert step.image == "" and not list((root / "images").iterdir())


@pytest.mark.parametrize("image", [QImage(), QImage(640, 480, QImage.Format_RGB32)])
def test_an_unusable_buffered_frame_falls_back_to_a_screenshot(qapp, tmp_path, image):
    deps = FakeDeps(qapp, chain=save_button(), buffered=Pick(image=image, age_ms=100.0, gap_ms=0.0))
    session, root = new_session(deps, tmp_path)
    step = session.handle(click()).steps[0]
    assert deps.calls["grab"] == 1
    assert QImage(str(root / step.image)).size().width() == MON.w
