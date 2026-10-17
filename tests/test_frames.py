"""Choosing the frame for a click: pure logic, no Windows."""
import math

import pytest

from recordsteps.frames import ClockMap, Frame, add, calibrate, confirm, pick, unwrap_ms


def frame(t, seen=None, name=None):
    return Frame(t_ms=t, seen_ms=t if seen is None else seen, pixels=name or f"f{t}")


# ---------------------------------------------------------------- picking


def test_the_newest_frame_from_before_the_click_wins():
    frames = (frame(100, 180), frame(200, 280), frame(300, 380))
    chosen = pick(frames, 250, max_gap_ms=100)
    assert chosen.image == "f200"
    assert chosen.age_ms == 50 and chosen.gap_ms == 0


def test_a_frame_whose_content_changed_after_the_click_is_never_used():
    frames = (frame(100, 100), frame(251, 260))  # the app reacted 1 ms after the click
    assert pick(frames, 250, max_gap_ms=200).image == "f100"


def test_a_frame_changed_exactly_at_the_click_counts_as_before_it():
    assert pick((frame(100), frame(250)), 250, max_gap_ms=100).image == "f250"


def test_no_frame_before_the_click_means_no_pick():
    assert pick((frame(300), frame(400)), 250, max_gap_ms=1000) is None
    assert pick((), 250, max_gap_ms=1000) is None


def test_gap_is_how_long_before_the_click_the_frame_was_last_confirmed():
    chosen = pick((frame(100, 170),), 250, max_gap_ms=100)
    assert chosen.gap_ms == 80 and chosen.age_ms == 150


def test_frames_inside_the_safety_margin_before_the_click_are_skipped():
    # clock mapping can make a frame look up to a few ms earlier than it was: stay clear of the click
    frames = (frame(200, 200), frame(240, 245))
    chosen = pick(frames, 250, max_gap_ms=100, margin_ms=20)
    assert chosen.image == "f200" and chosen.age_ms == 50 and chosen.gap_ms == 50
    assert pick((frame(245),), 250, max_gap_ms=100, margin_ms=20) is None


def test_a_stalled_capture_is_not_trusted():
    # the newest frame was last confirmed 400 ms before the click: the screen may have changed since
    assert pick((frame(100, 150),), 550, max_gap_ms=250) is None


# ---------------------------------------------------------------- adding and confirming


def test_confirm_moves_the_newest_frames_seen_time_forward_only():
    frames = (frame(100, 100), frame(200, 200))
    later = confirm(frames, 290)
    assert later[-1].seen_ms == 290 and later[0] == frames[0]
    assert frames[-1].seen_ms == 200  # the original is untouched
    assert confirm(later, 250)[-1].seen_ms == 290
    assert confirm((), 999) == ()


def test_add_keeps_every_frame_that_still_answers_a_recent_click():
    frames = (frame(0), frame(500), frame(900))
    kept, dropped = add(frames, frame(1600), keep_ms=1000, max_frames=10)
    # a click at 600 (within the last second) needs the frame from 500, so it stays
    assert [f.t_ms for f in kept] == [500, 900, 1600]
    assert [f.t_ms for f in dropped] == [0]
    assert len(frames) == 3  # the original is untouched


def test_add_on_a_static_screen_keeps_the_last_frame_however_old():
    kept, dropped = add((), frame(0, 50_000), keep_ms=1000, max_frames=10)
    kept, dropped = add(kept, frame(50_100), keep_ms=1000, max_frames=10)
    assert [f.t_ms for f in kept] == [0, 50_100] and dropped == ()


def test_add_never_holds_more_than_max_frames():
    frames = tuple(frame(t) for t in range(0, 500, 100))
    kept, dropped = add(frames, frame(500), keep_ms=10_000, max_frames=4)
    assert [f.t_ms for f in kept] == [200, 300, 400, 500]
    assert [f.t_ms for f in dropped] == [0, 100]


# ---------------------------------------------------------------- clocks


def test_unwrap_puts_a_32_bit_message_time_on_the_64_bit_clock():
    wrap = 1 << 32
    assert unwrap_ms(1000, 1500) == 1000
    assert unwrap_ms(3, wrap + 5) == wrap + 3  # clicked just after the 49.7-day wrap
    assert unwrap_ms(wrap - 10, wrap + 5) == wrap - 10  # clicked just before it


def test_clock_map_converts_performance_counter_readings():
    clock = ClockMap(offset_ms=-20.0, freq=10_000_000)
    assert clock.to_ms(10_000_000) == pytest.approx(980.0)
    assert clock.to_ms(10_005_000) == pytest.approx(980.5)


class FakeClocks:
    """A 10 MHz performance counter and a tick count that steps every 15.625 ms, like Windows."""

    def __init__(self, offset_ms=-20.0, late_steps=(), stalls=()):
        self.ticks = 50_000_000  # performance-counter units (5 s after boot)
        self.offset_ms = offset_ms
        self.late_steps = list(late_steps)  # extra lag (ms) the next tick steps are noticed with
        self.stalls = set(stalls)  # readings before which the reading thread was paused for 17 ms
        self.reads = 0

    def qpc(self):
        self.reads += 1
        self.ticks += 1_000 + (170_000 if self.reads in self.stalls else 0)  # 0.1 ms between readings
        return self.ticks

    def tick_ms(self):
        now = self.ticks / 10_000 + self.offset_ms
        lag = self.late_steps[0] if self.late_steps else 0.0
        stepped = math.floor((now - lag) // 15.625 * 15.625)  # whole milliseconds, like GetTickCount64
        if self.late_steps and stepped != getattr(self, "_last", stepped):
            self.late_steps.pop(0)
        self._last = stepped
        return stepped


def test_calibrate_lines_the_clocks_up_at_tick_steps():
    fake = FakeClocks(offset_ms=-20.0)
    clock = calibrate(fake.qpc, fake.tick_ms, 10_000_000, edges=3)
    # whole-millisecond ticks make the offset look smaller (frames earlier) by under 1 ms; the
    # margin in pick() covers that
    assert -21.0 <= clock.offset_ms <= -19.9


def test_calibrate_keeps_the_best_of_several_steps():
    # a step the kernel publishes 16 ms late makes the offset look 16 ms smaller (frames look 16 ms
    # earlier than they were, the unsafe direction); the largest of a few steps wins
    fake = FakeClocks(offset_ms=-20.0, late_steps=[16.0])
    assert -21.0 <= calibrate(fake.qpc, fake.tick_ms, 10_000_000, edges=3).offset_ms <= -19.9
    fake = FakeClocks(offset_ms=-20.0, late_steps=[16.0])
    assert calibrate(fake.qpc, fake.tick_ms, 10_000_000, edges=1).offset_ms < -30


def test_calibrate_ignores_a_step_that_went_by_while_the_reader_was_paused():
    # the reading thread lost the CPU (or the GIL) for 17 ms and a step happened meanwhile:
    # where in that gap it happened is unknown, so the reading is thrown away
    fake = FakeClocks(offset_ms=-20.0, stalls={3})
    assert -21.0 <= calibrate(fake.qpc, fake.tick_ms, 10_000_000, edges=1).offset_ms <= -19.9


def test_calibrate_gives_up_on_a_tick_count_that_never_moves():
    with pytest.raises(RuntimeError, match="tick count"):
        calibrate(iter(range(10**6)).__next__, lambda: 42, 10_000_000, max_reads=100)
