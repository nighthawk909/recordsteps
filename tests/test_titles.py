import pytest

from recordsteps.model import Target
from recordsteps.titles import MAX_NAME, clean_name, describe, title_steps
from tests.conftest import make_step


@pytest.mark.parametrize("raw, expected", [
    ("  Save  ", "Save"),
    ("Save\n  as", "Save as"),
    ("&Save", "Save"),
    ("Fish && Chips", "Fish & Chips"),
    ("File name:", "File name"),
    ("Save (Ctrl+S)", "Save"),
    ("Copy\tCtrl+C", "Copy"),
    ("Undo (Ctrl+Z)", "Undo"),
    ("", ""),
])
def test_clean_name(raw, expected):
    assert clean_name(raw) == expected


def test_clean_name_truncates_long_names():
    cleaned = clean_name("x" * 200)
    assert len(cleaned) == MAX_NAME
    assert cleaned.endswith("…")


@pytest.mark.parametrize("role, expected", [
    ("Button", "Click **Save**"),
    ("SplitButton", "Click **Save**"),
    ("MenuItem", "Select **Save**"),
    ("TabItem", "Open the **Save** tab"),
    ("Hyperlink", "Click the **Save** link"),
    ("CheckBox", "Click the **Save** checkbox"),
    ("RadioButton", "Choose **Save**"),
    ("ListItem", "Select **Save**"),
    ("TreeItem", "Select **Save**"),
    ("DataItem", "Select **Save**"),
    ("Edit", "Click the **Save** field"),
    ("ComboBox", "Open the **Save** list"),
    ("Text", "Click **Save**"),
    ("", "Click **Save**"),
])
def test_click_wording_follows_the_control_type(role, expected):
    assert describe("click", Target(name="Save", role=role, source="uia"), window="") == expected


@pytest.mark.parametrize("action, expected", [
    ("double_click", "Double-click **report.xlsx**"),
    ("right_click", "Right-click **report.xlsx**"),
])
def test_other_buttons(action, expected):
    assert describe(action, Target(name="report.xlsx", role="ListItem", source="uia"), window="") == expected


def test_unnamed_target_points_at_the_window():
    assert describe("click", Target(), window="Untitled - Notepad") == "Click in **Untitled - Notepad**"
    assert describe("right_click", Target(), window="Untitled - Notepad") == "Right-click in **Untitled - Notepad**"


def test_unnamed_target_without_a_window():
    assert describe("click", Target(), window="") == "Click here"


def test_ocr_names_read_like_any_other_name():
    assert describe("click", Target(name="Submit", source="ocr"), window="") == "Click **Submit**"


def test_names_with_markers_are_escaped():
    assert describe("click", Target(name="Total*", role="Button", source="uia"), window="") == "Click **Total\\***"


def test_app_is_named_on_the_first_step_and_when_it_changes():
    steps = [
        make_step(1, app="Excel"),
        make_step(2, app="Excel"),
        make_step(3, app="Edge", target=Target(name="Sign in", role="Button", source="uia")),
        make_step(4, app="Excel"),
    ]
    assert title_steps(steps) == (
        "Click **Save** in Excel",
        "Click **Save**",
        "Click **Sign in** in Edge",
        "Click **Save** in Excel",
    )


def test_unnamed_steps_skip_the_app_suffix_because_the_window_says_it():
    steps = [make_step(1, target=Target(), window="Book1 - Excel")]
    assert title_steps(steps) == ("Click in **Book1 - Excel**",)


def test_skipped_private_steps_get_a_plain_title():
    steps = [make_step(1, target=Target(), image="", window="", note="Private window: details skipped")]
    assert title_steps(steps) == ("Click in a private window",)


def test_missing_app_name_adds_no_suffix():
    assert title_steps([make_step(1, app="")]) == ("Click **Save**",)
