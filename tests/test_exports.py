import csv
import json

import pytest
from PySide6.QtGui import QColor, QImage

from recordsteps import bundle
from recordsteps.export_html import ShotView, render_html
from recordsteps.export_md import render_markdown
from recordsteps.exporter import export_bundle
from recordsteps.images import annotate, to_data_uri
from recordsteps.model import PRIVATE_NOTE, Rect, Target
from tests.conftest import make_guide, make_step

# ---------------------------------------------------------------- markdown


def test_markdown_lists_numbered_steps_with_images():
    guide = make_guide(make_step(1), make_step(2, title="Click **Close**"))
    md = render_markdown(guide, {"step-001": "images/step-001.png", "step-002": "images/step-002.png"})
    assert md.startswith("# Recorded steps\n")
    assert "1. Click **Save** in Excel" in md
    assert "   ![Step 1: Click Save in Excel](images/step-001.png)" in md
    assert "2. Click **Close**" in md


def test_markdown_escapes_markdown_in_names_and_windows():
    step = make_step(1, title="Click **a\\*b** in [Excel]")
    md = render_markdown(make_guide(step), {})
    assert "1. Click **a\\*b** in \\[Excel\\]" in md


def test_markdown_uses_the_users_edited_title():
    md = render_markdown(make_guide(make_step(1, edited_title="Save the workbook")), {})
    assert "1. Save the workbook" in md


def test_markdown_steps_without_images_say_why():
    step = make_step(1, image="", target=Target(), note=PRIVATE_NOTE, title="Click in a private window")
    md = render_markdown(make_guide(step), {})
    assert "1. Click in a private window" in md
    assert f"   _{PRIVATE_NOTE}_" in md


# ---------------------------------------------------------------- html


def shot():
    return ShotView(data_uri="data:image/jpeg;base64,AAAA", ring=(10.0, 20.0, 5.0, 4.0), dot=(12.5, 22.0),
                    full_href="../images/step-001.png")


def test_html_is_a_complete_page_with_the_steps():
    html = render_html(make_guide(make_step(1)), {"step-001": shot()})
    assert html.startswith("<!doctype html>")
    assert "<title>Recorded steps</title>" in html
    assert "Click <strong>Save</strong> in Excel" in html
    assert 'src="data:image/jpeg;base64,AAAA"' in html
    assert "left:calc(10.0% - 6px)" in html
    assert 'href="../images/step-001.png"' in html


def test_html_escapes_everything_from_the_screen():
    step = make_step(1, title="Click **<script>alert(1)</script>**", window="<b>evil</b> & co", app="A&B")
    html = render_html(make_guide(step), {})
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;evil&lt;/b&gt; &amp; co" in html


def test_html_without_a_ring_draws_a_dot():
    view = ShotView(data_uri="data:image/jpeg;base64,AAAA", ring=None, dot=(50.0, 50.0), full_href="")
    html = render_html(make_guide(make_step(1)), {"step-001": view})
    assert 'class="dot"' in html
    assert 'class="ring"' not in html


def test_html_has_no_external_requests():
    html = render_html(make_guide(make_step(1)), {"step-001": shot()})
    assert "http://" not in html and "https://" not in html.replace("https://www.w3.org", "")


# ---------------------------------------------------------------- images


def test_annotate_draws_on_a_copy(screen_image):
    marked = annotate(screen_image, click=(1221, 655), bbox=Rect(1184, 642, 76, 28))
    assert marked is not screen_image
    assert screen_image.pixelColor(1180, 655) == QColor("#F3F3F3")
    ring_pixels = {marked.pixelColor(x, 655).name() for x in range(1170, 1184)}
    assert "#ff5a36" in ring_pixels and "#ffffff" in ring_pixels


def test_annotate_without_a_box_rings_the_click(screen_image):
    marked = annotate(screen_image, click=(400, 400), bbox=None)
    assert any(marked.pixelColor(x, 400).name() == "#ff5a36" for x in range(370, 400))


def test_to_data_uri_downscales_and_encodes(screen_image):
    uri = to_data_uri(screen_image, max_width=800)
    assert uri.startswith("data:image/jpeg;base64,")
    import base64

    raw = base64.b64decode(uri.split(",", 1)[1])
    img = QImage.fromData(raw)
    assert img.width() == 800


# ---------------------------------------------------------------- bundle + full export


@pytest.fixture
def recorded_bundle(tmp_path, screen_image):
    root = bundle.new_bundle_dir(tmp_path, stamp="2026-10-17 0930")
    private = make_step(2, image="", target=Target(), note=PRIVATE_NOTE, title="Click in a private window")
    steps = (make_step(1), private)
    bundle.save_image(root, "step-001", screen_image)
    bundle.save_guide(root, make_guide(*steps))
    return root


def test_new_bundle_dirs_are_unique_and_marked(tmp_path):
    a = bundle.new_bundle_dir(tmp_path, stamp="2026-10-17 0930")
    b = bundle.new_bundle_dir(tmp_path, stamp="2026-10-17 0930")
    assert a != b
    assert (a / bundle.MARKER).exists() and (a / "images").is_dir()


def test_save_and_load_guide_round_trip(recorded_bundle):
    guide = bundle.load_guide(recorded_bundle)
    assert len(guide.steps) == 2
    assert not list(recorded_bundle.glob("*.tmp"))


def test_save_guide_retries_while_windows_holds_the_file(tmp_path, monkeypatch):
    import os

    real = os.replace
    failures = iter([PermissionError("locked"), PermissionError("locked")])

    def flaky(src, dst):
        err = next(failures, None)
        if err:
            raise err
        real(src, dst)

    monkeypatch.setattr(bundle.os, "replace", flaky)
    monkeypatch.setattr(bundle.time, "sleep", lambda s: None)
    bundle.save_guide(tmp_path, make_guide(make_step(1)))
    assert bundle.load_guide(tmp_path).steps[0].id == "step-001"


def test_save_guide_gives_up_eventually(tmp_path, monkeypatch):
    def locked(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr(bundle.os, "replace", locked)
    monkeypatch.setattr(bundle.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        bundle.save_guide(tmp_path, make_guide())


def test_load_guide_rejects_garbage(tmp_path):
    (tmp_path / "guide.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(bundle.BundleError):
        bundle.load_guide(tmp_path)


def test_remove_bundle_only_deletes_marked_folders(tmp_path):
    stranger = tmp_path / "Important"
    stranger.mkdir()
    with pytest.raises(bundle.BundleError):
        bundle.remove_bundle(stranger)
    assert stranger.exists()
    ours = bundle.new_bundle_dir(tmp_path, stamp="x")
    bundle.remove_bundle(ours)
    assert not ours.exists()


def test_export_bundle_writes_html_markdown_and_review(recorded_bundle, qapp):
    result = export_bundle(recorded_bundle)
    html = result.html.read_text(encoding="utf-8")
    md = result.markdown.read_text(encoding="utf-8")
    assert "Click <strong>Save</strong> in Excel" in html
    assert "data:image/jpeg;base64," in html
    assert "![Step 1: Click Save in Excel](images/step-001.png)" in md
    exported = QImage(str(result.markdown.parent / "images" / "step-001.png"))
    assert not exported.isNull() and exported.width() <= 1600
    rows = list(csv.reader(result.review.open(encoding="utf-8")))
    assert rows[0][:4] == ["step", "app", "window", "role"]
    assert rows[1][0] == "1" and rows[1][-2] == ""  # title_ok left for the reviewer


def test_export_keeps_existing_review_answers(recorded_bundle, qapp):
    first = export_bundle(recorded_bundle)
    rows = list(csv.reader(first.review.open(encoding="utf-8")))
    rows[1][-2] = "y"
    with first.review.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    again = export_bundle(recorded_bundle)
    assert list(csv.reader(again.review.open(encoding="utf-8")))[1][-2] == "y"


def test_guide_json_on_disk_is_valid_json(recorded_bundle):
    data = json.loads((recorded_bundle / "guide.json").read_text(encoding="utf-8"))
    assert data["steps"][0]["image"] == "images/step-001.png"
