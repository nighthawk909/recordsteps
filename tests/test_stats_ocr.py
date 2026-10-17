import csv

from recordsteps.model import PRIVATE_NOTE, Target, Timing
from recordsteps.ocr_target import Word, nearest_text
from recordsteps.stats import format_summary, read_review, summarize
from tests.conftest import make_guide, make_step

# ---------------------------------------------------------------- stats


def test_summarize_counts_where_names_came_from():
    guide = make_guide(
        make_step(1),
        make_step(2, target=Target(name="Submit", source="ocr")),
        make_step(3, target=Target(), window="Book1 - Excel"),
        make_step(4, app="Edge", target=Target(name="Sign in", role="Button", source="uia")),
        make_step(5, image="", target=Target(), note=PRIVATE_NOTE),
    )
    s = summarize([guide])
    assert (s.steps, s.uia, s.ocr, s.unnamed, s.skipped) == (5, 2, 1, 1, 1)
    assert dict((app, (n, named)) for app, n, named in s.by_app) == {"Excel": (4, 2), "Edge": (1, 1)}


def test_summarize_reports_timing_percentiles():
    steps = [make_step(i, timing=Timing(capture_ms=float(i), uia_ms=10.0, total_ms=float(i * 10)))
             for i in range(1, 11)]
    s = summarize([make_guide(*steps)])
    assert s.median_capture_ms == 5.5
    assert s.p95_total_ms >= 95.0


def test_summarize_folds_in_review_answers():
    s = summarize([make_guide(make_step(1), make_step(2), make_step(3))], reviews=[{"1": "y", "2": "n", "3": ""}])
    assert (s.reviewed, s.titles_ok) == (2, 1)


def test_format_summary_is_readable():
    text = format_summary(summarize([make_guide(make_step(1))]))
    assert "1 steps" in text and "UI Automation" in text


def test_read_review_maps_step_numbers_to_answers(tmp_path):
    path = tmp_path / "review.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["step", "app", "window", "role", "element", "source", "title", "title_ok", "better_title"])
        w.writerow(["1", "Excel", "", "Button", "Save", "uia", "Click Save", " Yes ", ""])
        w.writerow(["2", "Excel", "", "Button", "Save", "uia", "Click Save", "n", "Save the file"])
    assert read_review(path) == {"1": "y", "2": "n"}


def test_read_review_tolerates_a_missing_file(tmp_path):
    assert read_review(tmp_path / "nope.csv") == {}


# ---------------------------------------------------------------- ocr fallback


def word(text, x, y, w=60, h=18, line=0):
    return Word(text=text, x=x, y=y, w=w, h=h, line=line)


def test_word_under_the_pointer_brings_its_whole_line():
    words = (word("Submit", 100, 100, line=0), word("order", 165, 100, line=0), word("Cancel", 400, 100, line=1))
    hit = nearest_text(words, (120, 108))
    assert hit is not None
    assert hit.text == "Submit order"
    assert (hit.x, hit.y) == (100, 100) and hit.right == 225


def test_nearby_text_is_used_when_the_click_misses_slightly():
    hit = nearest_text((word("OK", 100, 100),), (95, 125))
    assert hit is not None and hit.text == "OK"


def test_far_away_text_is_ignored():
    assert nearest_text((word("OK", 100, 100),), (600, 600)) is None


def test_no_words_no_text():
    assert nearest_text((), (0, 0)) is None


def test_long_lines_are_trimmed():
    words = tuple(word(f"w{i}", 100 + i * 70, 100) for i in range(30))
    hit = nearest_text(words, (110, 105))
    assert hit is not None and len(hit.text) <= 40
