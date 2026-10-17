"""Real Windows APIs that need no input: they read the screen, UI Automation and OCR, and
parse fake raw input. Nothing here moves or clicks the mouse."""
import ctypes
import os
import sys
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def in_thread(fn):
    """Run fn on a fresh thread, like the capture worker, and return its result."""
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # re-raised on the test thread
            box["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join(60)
    if "error" in box:
        raise box["error"]
    return box["value"]


# ---------------------------------------------------------------- system queries


def test_system_queries_answer_sensibly():
    from recordsteps.win import system

    assert system.process_path(os.getpid()).lower().endswith(".exe")
    assert system.process_path(0) == ""
    assert system.dpi_at(0, 0) >= 96
    ms, dx, dy = system.double_click_metrics()
    assert 100 <= ms <= 5000 and dx >= 1 and dy >= 1
    assert isinstance(system.animations_enabled(), bool)
    hit = system.window_at(10, 10)
    assert hit.pid >= 0 and isinstance(hit.title, str)
    assert system.window_at(-999_999, -999_999).pid == 0


def test_app_names_from_real_programs():
    from recordsteps import apps

    assert apps.app_name(sys.executable)  # python.exe -> its version-info description
    assert apps.app_name(r"C:\nowhere\EXCEL.EXE") == "Excel"
    assert apps.file_description("") == ""
    assert apps.file_description(r"C:\nowhere\missing.exe") == ""


# ---------------------------------------------------------------- capture dependencies


def test_screen_grabber_returns_a_monitor_sized_image(qapp):
    from recordsteps.win.screen import ScreenGrabber

    def grab():
        g = ScreenGrabber()
        try:
            monitor = g.monitor_at(5, 5)
            image = g.grab(monitor)
            fallback = g.monitor_at(-999_999, -999_999)
            return monitor, (image.width(), image.height()), fallback
        finally:
            g.close()

    monitor, size, fallback = in_thread(grab)
    assert size == (monitor.w, monitor.h)
    assert fallback.w > 0


def test_ui_automation_describes_what_is_on_screen():
    from recordsteps.targets import ElementInfo
    from recordsteps.win.uia import UiaClient

    def look():
        client = UiaClient()
        try:
            return client.chain_at(10, 10)
        finally:
            client.close()

    chain = in_thread(look)
    assert chain and all(isinstance(e, ElementInfo) for e in chain)
    assert all(e.role for e in chain)


def test_windows_deps_end_to_end_without_input(qapp):
    from recordsteps.win.deps import WindowsDeps

    def use():
        deps = WindowsDeps()
        try:
            monitor = deps.monitor_at(10, 10)
            return (deps.window_at(10, 10), monitor, deps.dpi_at(10, 10), deps.grab(monitor).isNull(),
                    deps.chain_at(10, 10), deps.app_name(r"C:\x\msedge.exe"))
        finally:
            deps.close()

    hit, monitor, dpi, null_image, chain, name = in_thread(use)
    assert monitor.w > 0 and dpi >= 96 and not null_image and name == "Edge"


def test_windows_ocr_reads_rendered_text(qapp):
    from PySide6.QtGui import QFontDatabase

    from recordsteps.ocr import OcrUnavailable, recognize_words

    # The headless Qt platform used in tests has no fonts of its own; borrow Windows' Segoe UI.
    font_id = QFontDatabase.addApplicationFont(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts",
                                                            "segoeui.ttf"))
    if font_id < 0:
        pytest.skip("Segoe UI isn't available to draw test text")
    font = QFont(QFontDatabase.applicationFontFamilies(font_id)[0])
    font.setPixelSize(40)
    image = QImage(420, 120, QImage.Format_RGB32)
    image.fill(QColor("white"))
    p = QPainter(image)
    p.setPen(QColor("black"))
    p.setFont(font)
    p.drawText(image.rect(), Qt.AlignCenter, "Submit order")
    p.end()
    try:
        words = in_thread(lambda: recognize_words(image))
    except OcrUnavailable:
        pytest.skip("no OCR language pack on this machine")
    text = " ".join(w.text for w in words)
    assert "Submit" in text
    assert all(0 <= w.x < 420 and 0 <= w.y < 120 for w in words)
    assert len({w.line for w in words}) == 1


# ---------------------------------------------------------------- raw input


def test_raw_input_structures_match_the_windows_layout():
    from recordsteps.win import rawinput as ri

    pointer = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(ri.RAWINPUTHEADER) == 8 + 2 * pointer
    assert ri.RAWMOUSE.u.offset == 4  # the button flags union is 4-byte aligned after usFlags
    assert ctypes.sizeof(ri.RAWMOUSE) == 24


def test_listener_registers_and_unregisters_cleanly():
    from recordsteps.win.rawinput import MouseListener

    listener = MouseListener(lambda click: None)
    assert listener.start()
    assert listener.start()  # already running: no second thread
    listener.stop()
    assert listener.start()  # can start again after a pause
    listener.stop()
    listener.stop()  # stopping twice is harmless


def fake_user32(ri, *, button_flags, pos, dtype=0, fail=False):
    def get_raw_input_data(lparam, command, buf, size_ref, header_size):
        if fail:
            return ri._FAILED
        size_ref._obj.value = ctypes.sizeof(ri.RAWINPUT)
        if buf is not None:
            raw = ri.RAWINPUT()
            raw.header.dwType = dtype
            raw.mouse.u.s.usButtonFlags = button_flags
            ctypes.memmove(buf, ctypes.byref(raw), ctypes.sizeof(raw))
        return ctypes.sizeof(ri.RAWINPUT)

    return SimpleNamespace(GetRawInputData=get_raw_input_data, GetMessagePos=lambda: pos,
                           GetMessageTime=lambda: 123456, DefWindowProcW=lambda *a: 7)


@pytest.mark.parametrize("flags, expected", [
    (0x0001, "left"),
    (0x0004, "right"),
    (0x0002, None),  # left button up
    (0x0400, None),  # wheel
])
def test_raw_input_reads_button_presses(monkeypatch, flags, expected):
    from recordsteps.win import rawinput as ri

    seen = []
    listener = ri.MouseListener(seen.append)
    x, y = -1200, 340  # a monitor left of the primary one has negative x
    monkeypatch.setattr(ri, "_user32", fake_user32(ri, button_flags=flags, pos=(x & 0xFFFF) | (y << 16)))
    assert listener._wndproc(None, ri.WM_INPUT, 0, 99) == 7
    if expected is None:
        assert seen == []
    else:
        assert [(c.button, c.x, c.y, c.t_ms) for c in seen] == [(expected, x, y, 123456)]


def test_raw_input_ignores_other_devices_and_failures(monkeypatch):
    from recordsteps.win import rawinput as ri

    seen = []
    listener = ri.MouseListener(seen.append)
    monkeypatch.setattr(ri, "_user32", fake_user32(ri, button_flags=1, pos=0, dtype=1))  # keyboard
    listener._wndproc(None, ri.WM_INPUT, 0, 1)
    monkeypatch.setattr(ri, "_user32", fake_user32(ri, button_flags=1, pos=0, fail=True))
    listener._wndproc(None, ri.WM_INPUT, 0, 1)
    assert seen == []


def test_raw_input_callback_errors_never_escape(monkeypatch):
    from recordsteps.win import rawinput as ri

    def boom(click):
        raise RuntimeError("bad listener")

    listener = ri.MouseListener(boom)
    monkeypatch.setattr(ri, "_user32", fake_user32(ri, button_flags=1, pos=0))
    assert listener._wndproc(None, ri.WM_INPUT, 0, 1) == 7


# ---------------------------------------------------------------- review follow-ups


def test_private_window_check_looks_at_every_window_on_the_monitor(monkeypatch):
    from recordsteps.model import Rect
    from recordsteps.win import system

    everything = Rect(-100_000, -100_000, 200_000, 200_000)
    nowhere = Rect(900_000, 900_000, 10, 10)
    monkeypatch.setattr(system, "is_private", lambda title: bool(title))  # every titled window counts
    assert system.private_window_on(everything)
    assert not system.private_window_on(nowhere)
    monkeypatch.setattr(system, "is_private", lambda title: False)
    assert not system.private_window_on(everything)


def test_uia_prewarm_runs_on_a_side_thread():
    from recordsteps.win.uia import prewarm

    in_thread(prewarm)


def test_windows_deps_releases_the_screen_if_ui_automation_fails(monkeypatch):
    from recordsteps.win import deps as deps_module

    closed = []

    class Screen:
        def close(self):
            closed.append(True)

    def broken():
        raise OSError("UI Automation unavailable")

    monkeypatch.setattr(deps_module, "ScreenGrabber", Screen)
    monkeypatch.setattr(deps_module, "UiaClient", broken)
    with pytest.raises(OSError):
        deps_module.WindowsDeps()
    assert closed == [True]


def test_log_file_lives_in_local_app_data(tmp_path, monkeypatch):
    from recordsteps import app

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = app.setup_logging()
    assert path == tmp_path / "Record Steps" / "recordsteps.log"
    assert path.parent.is_dir()
