"""The rolling frame buffer's thread, against fake frame sources and clocks (no Windows)."""
import threading
import time

import pytest

from recordsteps.framebuffer import Captured, Clocks, FrameBuffer, Settings
from recordsteps.model import Rect

MON = Rect(0, 0, 1920, 1080)
OTHER = Rect(1920, 0, 1280, 1024)
FREQ = 10_000_000


def qpc():
    return int(time.perf_counter() * FREQ)


def tick_ms():
    return int(time.perf_counter() * 1000) - 20  # steps every millisecond; 20 ms behind the counter


CLOCKS = Clocks(qpc=qpc, tick_ms=tick_ms, freq=FREQ)
FAST = Settings(interval_s=0.005, keep_ms=200, max_frames=4, max_gap_ms=250, retry_s=0.02, recalibrate_s=60,
                private_hold_s=0.1)


def now_click():
    return tick_ms() & 0xFFFFFFFF  # a click stamped just now, as Windows' 32-bit message time


class Pixels:
    def __init__(self, n):
        self.n = n

    def to_image(self):
        return ("image", self.n)


class FakeSource:
    def __init__(self, monitor=MON, *, busy=True, fail_after=None, present=True, block=None, first=True,
                 snapshot_error=None, live=True):
        self.monitor = monitor
        self.live = live  # whether Desktop Duplication is known to be reporting changes
        self.busy = busy  # a new frame on every poll, like a playing video
        self.pending = first  # whether the first poll hands over a frame (not on a still screen)
        self.snapshot_error = snapshot_error
        self.snapshots = 0
        self.fail_after = fail_after
        self.present = present
        self.block = block  # an Event the second poll waits on, like a driver call that hangs
        self.polls = 0
        self.made = 0
        self.recycled = []
        self.closed = False

    def poll(self):
        self.polls += 1
        if self.block is not None and self.polls == 2:
            self.block.wait(5)
        if self.fail_after is not None and self.polls > self.fail_after:
            raise OSError("duplication lost")
        if not (self.busy or self.pending):
            return None
        self.pending = False
        self.made += 1
        return Captured(Pixels(self.made), qpc() if self.present else 0)

    def snapshot(self):
        self.snapshots += 1
        if self.snapshot_error is not None:
            raise self.snapshot_error
        self.made += 1
        return Captured(Pixels(self.made), 0)

    def recycle(self, pixels):
        self.recycled.append(pixels.n)

    def close(self):
        self.closed = True


class Opener:
    """open_sources(): hands out the next batch of fake sources each time it is called."""

    def __init__(self, *batches, error=None):
        self.batches = list(batches)
        self.calls = 0
        self.error = error

    def __call__(self):
        self.calls += 1
        if self.error is not None and self.calls == 1:
            raise self.error
        return self.batches.pop(0) if self.batches else [FakeSource()]


def wait_for(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def buffers():
    made = []

    def build(opener, private_on=lambda monitor: False, settings=FAST):
        buf = FrameBuffer(opener, private_on=private_on, clocks=CLOCKS, settings=settings)
        made.append(buf)
        return buf

    yield build
    for buf in made:
        buf.stop()


def test_frames_arrive_and_the_newest_before_the_click_is_picked(buffers):
    source = FakeSource()
    buf = buffers(Opener([source]))
    assert buf.frame_before(MON, now_click()) is None  # not started: nothing is captured
    buf.start()
    assert buf.running
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)
    chosen = buf.frame_before(MON, now_click())
    assert chosen.image[0] == "image" and 0 <= chosen.gap_ms <= FAST.max_gap_ms
    assert FAST.margin_ms <= chosen.age_ms < 1000  # never a frame from the last moments before the click


def test_clicks_older_than_the_buffer_or_on_unknown_monitors_get_nothing(buffers):
    buf = buffers(Opener([FakeSource()]))
    buf.start()
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)
    assert buf.frame_before(MON, now_click() - 60_000) is None
    assert buf.frame_before(OTHER, now_click()) is None


def test_stop_drops_every_frame_and_closes_the_sources(buffers):
    source = FakeSource()
    buf = buffers(Opener([source]))
    buf.start()
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)
    buf.stop()
    assert not buf.running and source.closed
    assert buf.frame_before(MON, now_click()) is None
    buf.stop()  # stopping twice is harmless


def test_start_twice_is_one_thread_and_restart_opens_fresh_sources(buffers):
    first, second = FakeSource(), FakeSource()
    opener = Opener([first], [second])
    buf = buffers(opener)
    buf.start()
    buf.start()
    assert wait_for(lambda: first.polls > 2)
    assert opener.calls == 1
    buf.stop()
    buf.start()
    assert wait_for(lambda: second.polls > 0) and first.closed


def test_a_static_screen_keeps_one_frame_confirmed_up_to_date(buffers):
    source = FakeSource(busy=False)
    buf = buffers(Opener([source]))
    buf.start()
    assert wait_for(lambda: source.polls > 3)
    time.sleep(0.3)
    chosen = buf.frame_before(MON, now_click())
    assert chosen.image == ("image", 1) and source.made == 1
    assert chosen.age_ms >= 250  # the screen last changed a while ago...
    assert chosen.gap_ms <= 100  # ...but the loop looked moments ago and nothing had changed


def test_frames_while_a_private_window_is_visible_are_neither_kept_nor_used(buffers):
    private = threading.Event()
    source = FakeSource()
    buf = buffers(Opener([source]), private_on=lambda monitor: private.is_set())
    buf.start()
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)
    private.set()
    made = source.made
    assert wait_for(lambda: source.made > made + 2)
    assert buf.frame_before(MON, now_click()) is None
    assert buf.frame_before(MON, now_click() - 5) is None  # older frames were dropped too
    assert any(n > made for n in source.recycled)  # frames taken while it was visible were never kept
    private.clear()
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)


def test_dropped_frames_go_back_to_their_source_for_reuse(buffers):
    source = FakeSource()
    buf = buffers(Opener([source]))
    buf.start()
    assert wait_for(lambda: len(source.recycled) >= 3)
    assert source.recycled[:2] == [1, 2]


def test_a_lost_source_is_closed_and_opened_again(buffers):
    broken = FakeSource(fail_after=3)
    opener = Opener([broken], [FakeSource()])
    buf = buffers(opener)
    buf.start()
    assert wait_for(lambda: opener.calls == 2)
    assert broken.closed
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)
    assert buf.stats().failures >= 1


def test_sources_that_cannot_open_are_retried(buffers):
    opener = Opener(error=OSError("no duplication in a remote session"))
    buf = buffers(opener)
    buf.start()
    assert buf.running
    assert wait_for(lambda: opener.calls >= 2)
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)


def test_without_a_present_time_the_poll_time_stamps_the_frame(buffers):
    source = FakeSource(present=False)
    buf = buffers(Opener([source]))
    buf.start()
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)


def test_several_monitors_are_buffered_separately(buffers):
    left, right = FakeSource(MON), FakeSource(OTHER, busy=False)
    buf = buffers(Opener([left, right]))
    buf.start()
    assert wait_for(lambda: buf.frame_before(OTHER, now_click()) is not None)
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)
    assert buf.frame_before(OTHER, now_click()).image == ("image", 1)


def test_the_clocks_are_lined_up_again_from_time_to_time(buffers):
    settings = Settings(interval_s=0.005, keep_ms=200, max_frames=4, max_gap_ms=250, retry_s=0.02,
                        recalibrate_s=0.05)
    buf = buffers(Opener([FakeSource(busy=False)]), settings=settings)
    buf.start()
    assert wait_for(lambda: buf.stats().calibrations >= 3)
    stats = buf.stats()
    assert stats.polls > 0 and stats.frames >= 1


def test_a_failing_private_window_check_counts_as_private(buffers):
    def broken(monitor):
        raise OSError("EnumWindows failed")

    source = FakeSource()
    buf = buffers(Opener([source]), private_on=broken)
    buf.start()
    assert wait_for(lambda: source.made > 3)
    assert buf.frame_before(MON, now_click()) is None


def test_a_thread_that_will_not_stop_is_never_doubled(buffers, monkeypatch):
    from recordsteps import framebuffer

    monkeypatch.setattr(framebuffer, "JOIN_TIMEOUT_S", 0.05)
    hang = threading.Event()
    stuck = FakeSource(block=hang)
    buf = buffers(Opener([stuck], [FakeSource()]))
    buf.start()
    assert wait_for(lambda: stuck.polls >= 2)  # now inside the hanging poll
    buf.stop()
    assert not buf.running and buf.frame_before(MON, now_click()) is None
    buf.start()  # the old thread is still alive: no second one beside it
    assert len([t for t in threading.enumerate() if t.name == "recordsteps-frames"]) == 1
    hang.set()
    assert wait_for(lambda: not any(t.name == "recordsteps-frames" for t in threading.enumerate()))
    assert stuck.closed
    assert buf.frame_before(MON, now_click()) is None  # its last frame arrived after stop: not kept
    buf.start()
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)


def test_failing_polls_back_off_instead_of_spinning(buffers):
    opener = Opener(*[[FakeSource(fail_after=0)] for _ in range(50)])
    buf = buffers(opener)
    buf.start()
    time.sleep(0.6)
    buf.stop()
    assert 2 <= opener.calls <= 8  # 20, 40, 80, 160, 320 ms apart; not hundreds of reopens
    assert buf.stats().failures == opener.calls


def test_sources_are_closed_when_the_clocks_cannot_be_lined_up():
    def broken_tick():
        raise OSError("no tick count")

    source = FakeSource()
    buf = FrameBuffer(Opener([source]), private_on=lambda m: False,
                      clocks=Clocks(qpc=qpc, tick_ms=broken_tick, freq=FREQ), settings=FAST)
    buf.start()
    try:
        assert wait_for(lambda: source.closed and buf.stats().failures >= 1)
        assert source.polls == 0
    finally:
        buf.stop()


PRIVATE = Settings(interval_s=0.005, keep_ms=200, max_frames=4, max_gap_ms=250, retry_s=0.02, recalibrate_s=60,
                   private_check_s=0.02, private_hold_s=0.3)


def test_frames_just_after_a_private_window_closes_are_dropped_too(buffers):
    # the window may have been on screen when the frame was taken and gone by the time it was
    # checked, so frames stay unkept until a while after one was last seen
    private = threading.Event()
    private.set()
    source = FakeSource(busy=False)
    buf = buffers(Opener([source]), private_on=lambda monitor: private.is_set(), settings=PRIVATE)
    buf.start()
    assert wait_for(lambda: buf.stats().private_drops >= 1)
    time.sleep(0.1)  # still visible: the still screen is checked again every 20 ms
    private.clear()
    source.pending = True  # the window closes: the screen changes
    assert wait_for(lambda: source.made == 2)
    time.sleep(0.02)
    assert buf.frame_before(MON, now_click()) is None
    assert 2 in source.recycled
    time.sleep(0.35)  # past the hold-off
    source.pending = True
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)


def test_a_private_window_on_a_still_screen_is_noticed_and_its_monitor_emptied(buffers):
    private = threading.Event()
    source = FakeSource(busy=False)
    buf = buffers(Opener([source]), private_on=lambda monitor: private.is_set(), settings=PRIVATE)
    buf.start()
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)
    private.set()  # e.g. dragged onto this monitor between two of our looks
    assert wait_for(lambda: buf.stats().private_drops >= 1)
    assert buf.frame_before(MON, now_click()) is None and source.made == 1


STILL = Settings(interval_s=0.005, keep_ms=200, max_frames=4, max_gap_ms=250, retry_s=0.02, recalibrate_s=60,
                 baseline_s=0.05)


def test_a_screen_that_never_changes_gets_one_snapshot(buffers):
    # Desktop Duplication only reports changes; with the screen still it may hand over nothing
    source = FakeSource(busy=False, first=False)
    buf = buffers(Opener([source]), settings=STILL)
    buf.start()
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)
    time.sleep(0.2)
    assert source.snapshots == 1  # a frame exists now: polls just confirm it
    assert buf.frame_before(MON, now_click()).image == ("image", 1)


def test_no_snapshot_while_a_private_window_is_visible(buffers):
    source = FakeSource(busy=False, first=False)
    buf = buffers(Opener([source]), private_on=lambda monitor: True, settings=STILL)
    buf.start()
    assert wait_for(lambda: source.polls > 20)
    assert source.snapshots == 0 and buf.frame_before(MON, now_click()) is None


def test_a_failing_snapshot_is_retried_now_and_then_not_on_every_poll(buffers):
    source = FakeSource(busy=False, first=False, snapshot_error=OSError("BitBlt failed"))
    buf = buffers(Opener([source]), settings=STILL)
    started = time.monotonic()
    buf.start()
    assert wait_for(lambda: source.polls > 40)
    elapsed = time.monotonic() - started
    assert 1 <= source.snapshots <= elapsed / STILL.baseline_s + 1  # one try per baseline_s, at most
    assert source.snapshots < source.polls
    assert buf.running and buf.stats().failures == 0


def test_frames_are_not_vouched_for_while_duplication_is_silent(buffers):
    # the display asleep: no reports at all, so "nothing changed" can't be trusted
    source = FakeSource(busy=False, live=False)
    buf = buffers(Opener([source]), settings=STILL)
    buf.start()
    assert wait_for(lambda: source.made >= 1 and source.polls > 5)
    time.sleep(FAST.max_gap_ms / 1000 + 0.1)
    assert buf.frame_before(MON, now_click()) is None  # the frame was never confirmed since it was taken
    assert buf.stats().blind_polls > 0
    source.live = True  # reporting again: the newest frame is confirmed from now on
    assert wait_for(lambda: buf.frame_before(MON, now_click()) is not None)
