"""The Desktop Duplication frame source against fake DXGI objects (the real one is exercised in
test_windows_apis.py)."""
import ctypes
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

from recordsteps.model import Rect  # noqa: E402

MON = Rect(0, 0, 4, 2)
PITCH = 32  # bytes per row: wider than 4 pixels x 4 bytes, as GPUs often pad rows


class FakeDuplicator:
    def __init__(self, *, ok=True, updated=True, accumulated=1, ticks=12345):
        self.ok, self.updated, self.accumulated_frames, self.latest_frame_ticks = ok, updated, accumulated, ticks
        self.texture = "desktop-texture"
        self.released_frames = 0
        self.released = False

    def update_frame(self):
        return self.ok

    def release_frame(self):
        self.released_frames += 1
        return True

    def release(self):
        self.released = True


class FakeRect(ctypes.Structure):
    _fields_ = [("Pitch", ctypes.c_int), ("pBits", ctypes.POINTER(ctypes.c_ubyte))]


class FakeStage:
    def __init__(self):
        self.texture = "staging-texture"
        self.memory = (ctypes.c_ubyte * (PITCH * MON.h))(*([0x11, 0x22, 0x33, 0xFF] * (PITCH * MON.h // 4)))
        self.mapped = 0
        self.released = False

    def map(self):
        self.mapped += 1
        return FakeRect(PITCH, ctypes.cast(self.memory, ctypes.POINTER(ctypes.c_ubyte)))

    def unmap(self):
        self.mapped -= 1

    def release(self):
        self.released = True


class FakeContext:
    def __init__(self):
        self.copies = []

    def CopyResource(self, dst, src):  # noqa: N802 (D3D11 method name)
        self.copies.append((dst, src))


@pytest.fixture
def source(qapp, monkeypatch):
    from recordsteps.win import dda

    monkeypatch.setattr(dda, "SETTLE_S", 0)

    def build(cursor=lambda: (0, 0), **dup):
        duplicator, stage, context = FakeDuplicator(**dup), FakeStage(), FakeContext()
        return dda.DdaSource(MON, context, duplicator, stage, cursor_pos=cursor), duplicator, stage, context

    return build


def test_a_changed_screen_becomes_a_frame_with_its_change_time(source):
    src, dup, stage, context = source(ticks=987654)
    captured = src.poll()
    assert captured.present_qpc == 987654
    assert context.copies == [("staging-texture", "desktop-texture")]
    assert dup.released_frames == 1 and stage.mapped == 0
    image = captured.pixels.to_image()
    assert (image.width(), image.height()) == (MON.w, MON.h)
    assert image.pixelColor(3, 1).name() == "#332211"  # BGRA bytes read as a 32-bit RGB image


def test_an_unchanged_screen_or_a_moved_pointer_gives_no_frame(source):
    src, dup, _, context = source(updated=False)
    assert src.poll() is None
    src, dup, _, context = source(accumulated=0)
    assert src.poll() is None
    assert dup.released_frames == 1 and context.copies == []


def test_lost_duplication_raises_so_the_buffer_reopens(source):
    from recordsteps.win.dda import DuplicationLost

    src, *_ = source(ok=False)
    with pytest.raises(DuplicationLost):
        src.poll()


def test_recycled_memory_is_reused_for_the_next_frame(source):
    src, *_ = source()
    first = src.poll().pixels
    src.recycle(first)
    second = src.poll().pixels
    assert second.data is first.data
    third = src.poll().pixels
    assert third.data is not first.data


def test_only_a_few_spare_buffers_are_kept(source):
    from recordsteps.win import dda

    src, *_ = source()
    frames = [src.poll().pixels for _ in range(dda.SPARE_BUFFERS + 2)]
    for pixels in frames:
        src.recycle(pixels)
    assert len(src._spare) == dda.SPARE_BUFFERS
    src.recycle(dda.Pixels(bytearray(3), 1, 1, 3))  # wrong size: not kept
    assert len(src._spare) == dda.SPARE_BUFFERS


def test_close_releases_the_duplication_and_staging_texture(source):
    src, dup, stage, _ = source()
    src.close()
    assert dup.released and stage.released


def test_windows_clocks_tick_together():
    from recordsteps.frames import calibrate
    from recordsteps.win.dda import windows_clocks

    clocks = windows_clocks()
    assert clocks.freq > 0
    a, b = clocks.qpc(), clocks.qpc()
    assert b >= a and clocks.tick_ms() > 0
    clock = calibrate(clocks.qpc, clocks.tick_ms, clocks.freq, edges=1)
    assert abs(clock.to_ms(clocks.qpc()) - clocks.tick_ms()) < 50


class FakeOutput:
    def __init__(self, *, attached=True, rotation=0, left=0):
        self.attached_to_desktop = attached
        self.rotation_angle = rotation
        coords = type("R", (), dict(left=left, top=0, right=left + 1920, bottom=1080))
        self.desc = type("D", (), dict(DesktopCoordinates=coords))


def test_only_plain_desktop_outputs_become_sources(qapp):
    from recordsteps.win import dda

    class Device:
        im_context = FakeContext()

    made = []

    def duplicator(output, device):
        if output.desc.DesktopCoordinates.left == 9999:
            raise OSError("DXGI_ERROR_UNSUPPORTED")
        made.append(output)
        return FakeDuplicator()

    def stage(output, device):
        return FakeStage()

    outputs = [FakeOutput(), FakeOutput(attached=False), FakeOutput(rotation=90), FakeOutput(left=9999),
               FakeOutput(left=1920)]
    sources = [s for o in outputs if (s := dda.open_output(Device(), o, duplicator, stage))]
    assert [s.monitor for s in sources] == [Rect(0, 0, 1920, 1080), Rect(1920, 0, 1920, 1080)]


def test_a_failed_staging_texture_releases_the_duplication(qapp):
    from recordsteps.win import dda

    dup = FakeDuplicator()

    def stage(output, device):
        raise OSError("out of video memory")

    assert dda.open_output(type("Dev", (), {"im_context": None})(), FakeOutput(), lambda o, d: dup, stage) is None
    assert dup.released


def test_a_frame_without_a_newer_change_time_is_not_backdated(source):
    # Desktop Duplication can report no present time; dxcam then keeps the previous one, which
    # would make the new frame look older than it is
    src, dup, *_ = source(ticks=5000)
    assert src.poll().present_qpc == 5000
    assert src.poll().present_qpc == 0  # same stamp again: the buffer uses the poll time instead
    dup.latest_frame_ticks = 6000
    assert src.poll().present_qpc == 6000


def test_close_releases_the_staging_texture_even_if_the_duplication_fails(source):
    src, dup, stage, _ = source()

    def broken():
        raise OSError("device removed")

    dup.release = broken
    with pytest.raises(OSError):
        src.close()
    assert stage.released


def test_a_snapshot_is_a_gdi_grab_of_the_monitor(source, monkeypatch, qapp):
    from PySide6.QtGui import QColor, QImage

    from recordsteps.win import dda

    grabbers = []

    class Grabber:
        def __init__(self):
            self.closed = False
            grabbers.append(self)

        def grab(self, monitor):
            img = QImage(monitor.w, monitor.h, QImage.Format_RGB32)
            img.fill(QColor("#123456"))
            return img

        def close(self):
            self.closed = True

    monkeypatch.setattr(dda, "ScreenGrabber", Grabber)
    src, *_ = source()
    first = src.snapshot()
    assert first.present_qpc == 0  # no change time: the buffer stamps it when the grab finished
    assert first.pixels.to_image().pixelColor(1, 1).name() == "#123456"
    src.recycle(first.pixels)  # snapshot memory is reused like any frame's
    src.snapshot()
    assert len(grabbers) == 1  # one grabber, made on the capture thread and kept
    src.close()
    assert grabbers[0].closed


def test_a_source_is_not_live_until_duplication_reports_something(source):
    # with the display asleep, Desktop Duplication reports nothing at all; silence then proves nothing
    src, dup, *_ = source(updated=False)
    for _ in range(3):
        assert src.poll() is None
    assert not src.live
    dup.updated, dup.accumulated_frames = True, 0  # the pointer moved: it is reporting
    assert src.poll() is None and src.live


def test_a_source_that_ignores_the_moving_pointer_stops_being_live(source):
    path = iter([(0, 0), (1, 0), (2, 1), (3, 1), (3, 0), (3, 0)])
    src, dup, *_ = source(cursor=lambda: next(path))
    src.poll()
    assert src.live
    dup.updated = False
    src.poll()
    assert src.live  # one silent poll can be a race with the pointer's last move
    src.poll()
    assert not src.live  # the pointer kept moving on this monitor and nothing was reported
    dup.updated = True
    src.poll()
    assert src.live


def test_pointer_moves_on_other_monitors_say_nothing_about_this_one(source):
    path = iter([(0, 0), (500, 0), (900, 0), (1300, 0)])
    src, dup, *_ = source(cursor=lambda: next(path))
    src.poll()
    dup.updated = False
    for _ in range(3):
        src.poll()
    assert src.live


def test_the_cursor_position_is_read_from_windows():
    from recordsteps.win.dda import cursor_pos

    x, y = cursor_pos()
    assert isinstance(x, int) and isinstance(y, int)
