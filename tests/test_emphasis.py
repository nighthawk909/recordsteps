import pytest

from recordsteps.emphasis import emphasize, plain, segments


def test_emphasize_wraps_a_name_in_bold_markers():
    assert emphasize("Save") == "**Save**"


def test_emphasize_escapes_markers_inside_the_name():
    assert emphasize("a*b\\c") == "**a\\*b\\\\c**"


def test_segments_split_plain_and_bold_parts():
    assert segments("Click **Save** in Excel") == [("Click ", False), ("Save", True), (" in Excel", False)]


def test_segments_round_trip_escaped_names():
    title = f"Click {emphasize('**Total*')} now"
    assert segments(title) == [("Click ", False), ("**Total*", True), (" now", False)]


def test_unbalanced_markers_read_as_plain_text():
    assert segments("Click **Save") == [("Click ", False), ("Save", False)]


def test_plain_drops_the_markers():
    assert plain("Click **Save** in **Excel**") == "Click Save in Excel"


@pytest.mark.parametrize("title", ["", "No emphasis at all", "**", "\\"])
def test_segments_never_crash(title):
    assert isinstance(segments(title), list)
