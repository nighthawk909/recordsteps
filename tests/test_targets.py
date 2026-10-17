from recordsteps.model import Rect
from recordsteps.targets import ElementInfo, resolve

BTN = Rect(100, 100, 80, 30)
TXT = Rect(110, 105, 40, 20)


def el(name="", role="", bbox=None, password=False):
    return ElementInfo(name=name, role=role, bbox=bbox, is_password=password)


def test_empty_chain_resolves_to_nothing():
    r = resolve(())
    assert r.name == "" and r.role == "" and r.bbox is None


def test_named_button_under_the_pointer_wins():
    r = resolve((el("Save", "Button", BTN), el("Ribbon", "ToolBar"), el("Book1 - Excel", "Window")))
    assert (r.name, r.role, r.bbox) == ("Save", "Button", BTN)


def test_text_inside_an_unnamed_button_names_the_button():
    r = resolve((el("Save", "Text", TXT), el("", "Button", BTN), el("Dialog", "Window")))
    assert (r.name, r.role, r.bbox) == ("Save", "Button", BTN)


def test_walks_up_past_decoration_to_the_actionable_control():
    r = resolve((el("", "Image", TXT), el("", "Group"), el("Open", "MenuItem", BTN), el("Menu", "Menu")))
    assert (r.name, r.role, r.bbox) == ("Open", "MenuItem", BTN)


def test_stops_walking_after_max_depth():
    chain = (el("", "Group"),) * 7 + (el("Far away", "Button", BTN),)
    r = resolve(chain)
    assert r.name == "" and r.role != "Button"


def test_named_non_actionable_element_is_used_when_nothing_actionable():
    r = resolve((el("Quarterly totals", "Text", TXT), el("", "Pane"), el("Report", "Window")))
    assert (r.name, r.role) == ("Quarterly totals", "Text")


def test_windows_and_panes_are_not_useful_names():
    r = resolve((el("Book1 - Excel", "Window"),))
    assert r.name == ""
    r = resolve((el("Workspace", "Pane"), el("Book1 - Excel", "Window")))
    assert r.name == ""


def test_unnamed_actionable_keeps_role_and_box():
    r = resolve((el("", "Button", BTN), el("Toolbar", "ToolBar")))
    assert (r.name, r.role, r.bbox) == ("", "Button", BTN)


def test_password_flag_comes_from_the_chosen_element():
    r = resolve((el("Password", "Edit", BTN, password=True),))
    assert r.is_password is True


def test_names_are_cleaned():
    r = resolve((el("&Save (Ctrl+S)", "Button", BTN),))
    assert r.name == "Save"


def test_bbox_falls_back_to_the_hit_element():
    r = resolve((el("Save", "Text", TXT),))
    assert r.bbox == TXT
