import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import jsonschema
import pytest

from recordsteps.model import (
    SCHEMA_VERSION,
    Guide,
    GuideFormatError,
    Rect,
    Target,
    add_step,
    display_title,
    guide_from_dict,
    guide_to_dict,
    next_step_id,
    replace_step,
)
from tests.conftest import make_guide, make_step

SCHEMA = json.loads((Path(__file__).parents[1] / "recordsteps" / "guide.schema.json").read_text(encoding="utf-8"))


def test_models_are_immutable():
    step = make_step()
    with pytest.raises(FrozenInstanceError):
        step.title = "changed"
    with pytest.raises(FrozenInstanceError):
        Rect(0, 0, 1, 1).x = 5


def test_add_step_returns_a_new_guide_and_leaves_the_old_one_alone():
    empty = make_guide()
    grown = add_step(empty, make_step(1))
    assert empty.steps == ()
    assert len(grown.steps) == 1
    assert grown is not empty


def test_replace_step_swaps_one_step_only():
    guide = make_guide(make_step(1), make_step(2))
    changed = replace_step(guide, 1, make_step(2, action="double_click"))
    assert changed.steps[1].action == "double_click"
    assert changed.steps[0] == guide.steps[0]
    assert guide.steps[1].action == "click"


def test_replace_step_rejects_a_missing_index():
    with pytest.raises(IndexError):
        replace_step(make_guide(make_step(1)), 3, make_step(4))


def test_next_step_id_counts_from_existing_steps():
    assert next_step_id(make_guide()) == "step-001"
    assert next_step_id(make_guide(make_step(1), make_step(2))) == "step-003"


def test_display_title_prefers_the_users_edit():
    assert display_title(make_step()) == "Click **Save** in Excel"
    assert display_title(make_step(edited_title="Save the workbook")) == "Save the workbook"


def test_round_trip_through_dict_keeps_everything():
    guide = make_guide(make_step(1), make_step(2, target=Target(), note="Private window: details skipped", image=""))
    again = guide_from_dict(json.loads(json.dumps(guide_to_dict(guide))))
    assert again == guide


def test_dict_uses_the_documented_field_names():
    data = guide_to_dict(make_guide(make_step(1)))
    assert data["schema"] == SCHEMA_VERSION
    step = data["steps"][0]
    assert step["element"] == {"name": "Save", "role": "Button", "source": "uia", "bbox": [1184, 642, 76, 28],
                               "isPassword": False}
    assert step["title"] == {"generated": "Click **Save** in Excel", "edited": None}
    assert step["click"] == [1221, 655]
    assert step["imageSize"] == [1920, 1080]
    assert step["timing"]["captureMs"] == 21.5


def test_output_matches_the_published_json_schema():
    guide = make_guide(make_step(1), make_step(2, target=Target(), image=""))
    jsonschema.validate(guide_to_dict(guide), SCHEMA)


def test_schema_rejects_an_unknown_action():
    data = guide_to_dict(make_guide(make_step(1)))
    data["steps"][0]["action"] = "teleport"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, SCHEMA)


@pytest.mark.parametrize("breakage", [
    lambda d: d.pop("steps"),
    lambda d: d.update(schema=99),
    lambda d: d["steps"][0].update(action="teleport"),
    lambda d: d["steps"][0].update(click=[1]),
    lambda d: d["steps"][0]["element"].update(source="magic"),
])
def test_from_dict_refuses_malformed_input(breakage):
    data = guide_to_dict(make_guide(make_step(1)))
    breakage(data)
    with pytest.raises(GuideFormatError):
        guide_from_dict(data)


def test_rect_helpers():
    r = Rect(10, 20, 30, 40)
    assert r.right == 40 and r.bottom == 60
    assert r.contains(10, 20) and r.contains(39, 59)
    assert not r.contains(40, 20)
    assert r.area == 1200
    assert Rect.from_list([1, 2, 3, 4]) == Rect(1, 2, 3, 4)
    assert r.to_list() == [10, 20, 30, 40]


def test_guide_defaults():
    g = Guide(id="x", title="t", created="2026-10-17T09:00:00")
    assert g.steps == () and g.schema == SCHEMA_VERSION and g.platform == "windows"
