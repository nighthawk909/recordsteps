import pytest

from recordsteps.apps import friendly_app_name, is_private, is_remote
from recordsteps.clicks import RawClick, is_double
from recordsteps.geometry import (
    focus_rect,
    percent_box,
    physical_to_logical,
    relative_point,
    relative_rect,
    useful_bbox,
)
from recordsteps.model import Rect

# ---------------------------------------------------------------- double clicks


def click(x=100, y=100, t=1000, button="left"):
    return RawClick(button=button, x=x, y=y, t_ms=t)


def test_second_quick_click_in_place_is_a_double_click():
    assert is_double(click(t=1000), click(t=1300), max_ms=500, max_dx=4, max_dy=4)


@pytest.mark.parametrize("prev, cur", [
    (None, click()),
    (click(t=1000), click(t=1600)),                 # too slow
    (click(x=100), click(x=110, t=1100)),           # moved
    (click(button="right"), click(button="right", t=1100)),  # right double-clicks are two steps
    (click(button="left"), click(button="right", t=1100)),
])
def test_not_double_clicks(prev, cur):
    assert not is_double(prev, cur, max_ms=500, max_dx=4, max_dy=4)


def test_tick_counter_wraparound_is_not_a_double_click():
    assert not is_double(click(t=4_294_967_000), click(t=100), max_ms=500, max_dx=4, max_dy=4)


# ---------------------------------------------------------------- geometry

MON = Rect(1920, 0, 2560, 1440)


def test_relative_point_and_rect():
    assert relative_point(2000, 100, MON) == (80, 100)
    assert relative_rect(Rect(1900, 10, 100, 50), MON) == Rect(0, 10, 80, 50)  # clipped to the monitor
    assert relative_rect(Rect(0, 0, 100, 100), MON) is None


def test_useful_bbox_drops_boxes_that_cover_most_of_the_screen():
    mon = Rect(0, 0, 1000, 1000)
    assert useful_bbox(Rect(10, 10, 100, 40), mon) == Rect(10, 10, 100, 40)
    assert useful_bbox(Rect(0, 0, 900, 900), mon) is None
    assert useful_bbox(None, mon) is None
    assert useful_bbox(Rect(5000, 5000, 10, 10), mon) is None


def test_focus_rect_centers_on_the_target_and_stays_inside_the_image():
    r = focus_rect((1720, 700), Rect(1700, 690, 40, 20), (3440, 1440), min_width=1280, aspect=1.6)
    assert r.w == 1280 and r.h == 800
    assert r.contains(1720, 700)
    assert r.x >= 0 and r.y >= 0 and r.right <= 3440 and r.bottom <= 1440


def test_focus_rect_clamps_at_edges():
    r = focus_rect((5, 5), None, (3440, 1440), min_width=1280, aspect=1.6)
    assert (r.x, r.y) == (0, 0)


def test_focus_rect_widens_for_big_targets():
    r = focus_rect((1000, 500), Rect(500, 400, 1000, 100), (3440, 1440), min_width=1280, aspect=1.6)
    assert r.w >= 1000 * 1.5


def test_focus_rect_uses_the_whole_image_when_small():
    assert focus_rect((10, 10), None, (800, 600), min_width=1280, aspect=1.6) == Rect(0, 0, 800, 600)


def test_percent_box():
    assert percent_box(Rect(100, 50, 200, 100), Rect(0, 0, 1000, 500)) == (10.0, 10.0, 20.0, 20.0)


def test_physical_to_logical_maps_through_the_right_screen():
    screens = [
        (Rect(0, 0, 3000, 2000), Rect(0, 0, 2000, 1333), 1.5),
        (Rect(3000, 0, 1920, 1080), Rect(3000, 0, 1920, 1080), 1.0),
    ]
    assert physical_to_logical(1500, 1000, screens) == (1000, 667)
    assert physical_to_logical(3100, 50, screens) == (3100, 50)
    assert physical_to_logical(99999, 0, screens) == (99999, 0)


# ---------------------------------------------------------------- apps


@pytest.mark.parametrize("path, expected", [
    (r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE", "Excel"),
    ("msedge.exe", "Edge"),
    (r"C:\Windows\system32\mstsc.exe", "Remote Desktop"),
    ("wfica32.exe", "Citrix"),
    ("my_tool-app.exe", "My Tool App"),
    ("", ""),
])
def test_friendly_app_name(path, expected):
    assert friendly_app_name(path) == expected


def test_friendly_app_name_uses_the_description_for_unknown_programs():
    assert friendly_app_name("bnet.exe", "Battle.net") == "Battle.net"


@pytest.mark.parametrize("process", ["mstsc.exe", "MSRDC.EXE", "wfica32.exe", "CDViewer.exe", "vmconnect.exe"])
def test_remote_sessions_are_detected(process):
    assert is_remote(process)


def test_local_apps_are_not_remote():
    assert not is_remote("EXCEL.EXE")


@pytest.mark.parametrize("title", ["Inbox - Work - Microsoft Edge [InPrivate]", "New Tab - Google Chrome (Incognito)",
                                   "Mozilla Firefox Private Browsing"])
def test_private_windows_are_detected(title):
    assert is_private(title)


def test_normal_windows_are_not_private():
    assert not is_private("Q3 forecast.xlsx - Excel")
