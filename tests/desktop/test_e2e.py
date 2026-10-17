"""End to end on real Windows: raw mouse input, UI Automation, screen capture, export.

Run with:  QT_QPA_PLATFORM=windows python -m pytest -m desktop
It moves the real mouse and clicks a test window this file starts. Needs an unlocked desktop.
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest

pytestmark = [pytest.mark.desktop, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2, like the real app

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("_pad", ctypes.c_byte * 32)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(flags, x=0, y=0):
    m = ctypes.windll.user32.GetSystemMetrics
    vx, vy, vw, vh = m(SM_XVIRTUALSCREEN), m(SM_YVIRTUALSCREEN), m(SM_CXVIRTUALSCREEN), m(SM_CYVIRTUALSCREEN)
    dx = round((x - vx) * 65535 / max(1, vw - 1))
    dy = round((y - vy) * 65535 / max(1, vh - 1))
    event = INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dx, dy, 0, flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                                                   0, 0))
    assert ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) == 1


def click_at(x, y, settle=0.7):
    _send(MOUSEEVENTF_MOVE, x, y)
    time.sleep(0.15)
    _send(MOUSEEVENTF_LEFTDOWN, x, y)
    time.sleep(0.05)
    _send(MOUSEEVENTF_LEFTUP, x, y)
    time.sleep(settle)


@pytest.fixture
def target_window():
    env = dict(os.environ, QT_QPA_PLATFORM="windows")
    proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("target_app.py"))],
                            stdout=subprocess.PIPE, text=True, env=env)
    try:
        line = proc.stdout.readline()
        assert line, "the test window didn't start"
        yield json.loads(line)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture
def cursor_restored():
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    yield
    ctypes.windll.user32.SetCursorPos(pt.x, pt.y)


def wait_for(predicate, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_recording_real_clicks_produces_a_titled_guide(qapp, tmp_path, target_window, cursor_restored):
    from recordsteps import bundle
    from recordsteps.exporter import export_bundle
    from recordsteps.recorder import Recorder
    from recordsteps.win.deps import WindowsDeps
    from recordsteps.win.rawinput import MouseListener
    from recordsteps.win.system import double_click_metrics

    folder = bundle.new_bundle_dir(tmp_path, stamp="e2e")
    changes = []
    rec = Recorder(folder, on_change=changes.append, on_click=lambda x, y: None, deps_factory=WindowsDeps,
                   listener_factory=MouseListener, double_click=double_click_metrics())
    rec.start()
    try:
        for name in ("save", "remember", "email", "advanced"):
            click_at(*target_window[name])
        x, y = target_window["save"]
        click_at(x, y, settle=0.05)  # a double-click on Save
        click_at(x, y)
        assert wait_for(lambda: changes and changes[-1].steps and changes[-1].steps[-1].action == "double_click"), \
            f"steps seen: {[(s.title, s.action) for s in (changes[-1].steps if changes else ())]}"
    finally:
        guide = rec.stop()

    titles = [s.title for s in guide.steps]
    assert len(titles) == 5, titles
    assert titles[0] == "Click **Save report** in Python"
    assert titles[1] == "Click the **Remember me** checkbox"
    assert titles[2] == "Click the **Email** field"
    assert titles[3] == "Open the **Advanced** tab"
    assert guide.steps[4].action == "double_click" and titles[4] == "Double-click **Save report**"
    for step in guide.steps:
        assert step.target.source == "uia"
        assert step.target.bbox is not None and step.target.bbox.contains(*step.click), step
        assert (folder / step.image).is_file()
        assert step.timing.total_ms < 3000

    result = export_bundle(folder)
    html = result.html.read_text(encoding="utf-8")
    assert "Click <strong>Save report</strong> in Python" in html
    assert len(list((folder / "export" / "images").glob("*.png"))) == 5


def test_the_pill_is_left_out_of_screenshots(qapp):
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "windows":
        pytest.skip("needs the real Windows platform: set QT_QPA_PLATFORM=windows")
    from recordsteps.ui.pill import RecordingPill
    from recordsteps.win.screen import ScreenGrabber

    pill = RecordingPill()
    pill.show_recording()
    for _ in range(20):
        qapp.processEvents()
        time.sleep(0.02)
    assert pill._excluded, "SetWindowDisplayAffinity didn't apply"
    g = pill.frameGeometry()
    dpr = pill.screen().devicePixelRatio()
    cx = round(g.center().x() * dpr)
    cy = round(g.center().y() * dpr)
    grabber = ScreenGrabber()
    image = grabber.grab(grabber.monitor_at(cx, cy))
    mon = grabber.monitor_at(cx, cy)
    colour = image.pixelColor(cx - mon.x, cy - mon.y).name()
    grabber.close()
    pill.hide()
    assert colour != "#0e1116", "the pill showed up in the screenshot"
