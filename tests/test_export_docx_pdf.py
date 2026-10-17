"""Word and PDF exports."""
from pathlib import Path

import docx
import pytest
from docx.shared import Inches
from PySide6.QtGui import QColor, QImage

from recordsteps.export_docx import STEP_ELEMENT_STYLE, STEP_NOTE_STYLE, STEP_TITLE_STYLE, render_docx
from recordsteps.export_pdf import plan_pages, render_pdf
from recordsteps.model import PASSWORD_NOTE, PRIVATE_NOTE, Target
from tests.conftest import make_guide, make_step


@pytest.fixture
def step_images(qapp, tmp_path):
    """Annotated crops like the exporter writes: one wide, one tall."""
    paths = {}
    for step_id, (w, h) in {"step-001": (1600, 1000), "step-002": (600, 1400)}.items():
        img = QImage(w, h, QImage.Format_RGB32)
        img.fill(QColor("#DDE3EA"))
        path = tmp_path / f"{step_id}.png"
        img.save(str(path))
        paths[step_id] = path
    return paths


def guide_with_notes():
    return make_guide(
        make_step(1),
        make_step(2, title="Open the **Advanced** tab", target=Target(name="Advanced", role="TabItem", source="uia")),
        make_step(3, image="", target=Target(), note=PRIVATE_NOTE, title="Click in a private window"),
        make_step(4, image="", note=PASSWORD_NOTE, title="Click the **Password** field"),
    )


# ---------------------------------------------------------------- Word


def test_word_document_has_a_title_and_one_titled_block_per_step(step_images, tmp_path):
    out = render_docx(guide_with_notes(), step_images, tmp_path / "guide.docx")
    doc = docx.Document(str(out))
    assert doc.paragraphs[0].style.name == "Title" and doc.paragraphs[0].text == "Recorded steps"
    titles = [p for p in doc.paragraphs if p.style.name == STEP_TITLE_STYLE]
    assert [p.text for p in titles] == ["1\tClick Save in Excel", "2\tOpen the Advanced tab",
                                        "3\tClick in a private window", "4\tClick the Password field"]


def test_element_names_use_a_character_style_not_direct_bold(step_images, tmp_path):
    doc = docx.Document(str(render_docx(guide_with_notes(), step_images, tmp_path / "g.docx")))
    first = next(p for p in doc.paragraphs if p.style.name == STEP_TITLE_STYLE)
    styled = [r.text for r in first.runs if r.style.name == STEP_ELEMENT_STYLE]
    assert styled == ["Save"]
    assert all(r.bold is None for r in first.runs)  # restyling in Word reaches every step
    assert doc.styles[STEP_ELEMENT_STYLE].font.bold is True


def test_step_titles_stay_with_their_screenshot(step_images, tmp_path):
    doc = docx.Document(str(render_docx(guide_with_notes(), step_images, tmp_path / "g.docx")))
    assert doc.styles[STEP_TITLE_STYLE].paragraph_format.keep_with_next is True


def test_screenshots_fit_the_page_and_carry_alt_text(step_images, tmp_path):
    doc = docx.Document(str(render_docx(guide_with_notes(), step_images, tmp_path / "g.docx")))
    shapes = doc.inline_shapes
    assert len(shapes) == 2
    assert all(s.width <= Inches(6.5) + 1 for s in shapes)
    assert shapes[1].height <= Inches(3.7)  # the tall screenshot is limited by height, not width
    descriptions = [s._inline.docPr.get("descr") for s in shapes]
    assert descriptions[0] == "Screenshot for step 1: Click Save in Excel"


def test_steps_without_screenshots_explain_why(step_images, tmp_path):
    doc = docx.Document(str(render_docx(guide_with_notes(), step_images, tmp_path / "g.docx")))
    notes = [p.text for p in doc.paragraphs if p.style.name == STEP_NOTE_STYLE]
    assert notes == [PRIVATE_NOTE, PASSWORD_NOTE]


def test_document_properties_name_the_guide_not_the_library(step_images, tmp_path):
    doc = docx.Document(str(render_docx(guide_with_notes(), step_images, tmp_path / "g.docx")))
    props = doc.core_properties
    assert props.title == "Recorded steps"
    assert "python-docx" not in (props.author + props.comments + props.last_modified_by)


def test_text_from_the_screen_with_control_characters_is_cleaned(step_images, tmp_path):
    step = make_step(1, title="Click **Sa\x00ve\x0b**", window="Bad\x1ftitle")
    doc = docx.Document(str(render_docx(make_guide(step), {}, tmp_path / "g.docx")))
    assert any(p.text == "1\tClick Save" for p in doc.paragraphs)


def test_a_company_word_template_supplies_the_styles(step_images, tmp_path):
    template = tmp_path / "company.docx"
    base = docx.Document()
    base.styles["Normal"].font.name = "Georgia"
    base.save(str(template))
    doc = docx.Document(str(render_docx(make_guide(make_step(1)), step_images, tmp_path / "g.docx",
                                        template=template)))
    assert doc.styles["Normal"].font.name == "Georgia"
    assert any(p.style.name == STEP_TITLE_STYLE for p in doc.paragraphs)


def test_a_missing_template_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        render_docx(make_guide(), {}, tmp_path / "g.docx", template=tmp_path / "nope.docx")


def test_the_footer_numbers_pages(step_images, tmp_path):
    doc = docx.Document(str(render_docx(make_guide(make_step(1)), step_images, tmp_path / "g.docx")))
    footer_xml = doc.sections[0].footer._element.xml
    assert "PAGE" in footer_xml


# ---------------------------------------------------------------- PDF


def test_pagination_never_splits_a_step():
    pages = plan_pages(header=100, blocks=[300, 300, 300, 500, 200], page_height=1000, gap=20)
    assert pages == [[0, 1], [2, 3], [4]]
    assert plan_pages(header=100, blocks=[300, 300, 300, 500, 80], page_height=1000, gap=20) == [[0, 1], [2, 3, 4]]


def test_pagination_puts_an_oversized_block_on_its_own_page():
    assert plan_pages(header=0, blocks=[50, 2000, 50], page_height=1000, gap=0) == [[0], [1], [2]]


def test_pagination_with_no_steps_is_one_page():
    assert plan_pages(header=100, blocks=[], page_height=1000, gap=20) == [[]]


def pdf_text(path: Path) -> tuple[int, str]:
    qtpdf = pytest.importorskip("PySide6.QtPdf")
    document = qtpdf.QPdfDocument()
    document.load(str(path))
    count = document.pageCount()
    return count, "\n".join(document.getAllText(i).text() for i in range(count))


def test_pdf_has_real_text_page_numbers_and_every_step(step_images, tmp_path, qapp):
    out = render_pdf(guide_with_notes(), step_images, tmp_path / "guide.pdf")
    assert out.read_bytes().startswith(b"%PDF")
    pages, text = pdf_text(out)
    assert pages >= 2  # two screenshots don't fit on one Letter page with the header
    for expected in ("Recorded steps", "Click Save in Excel", "Open the Advanced tab", PRIVATE_NOTE,
                     f"Page 1 of {pages}"):
        assert expected in " ".join(text.split()), expected


def test_pdf_of_an_empty_guide_is_one_page(tmp_path, qapp):
    pages, text = pdf_text(render_pdf(make_guide(), {}, tmp_path / "empty.pdf"))
    assert pages == 1 and "0 steps" in text


def test_pdf_skips_unreadable_screenshots(tmp_path, qapp):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a png")
    pages, text = pdf_text(render_pdf(make_guide(make_step(1)), {"step-001": broken}, tmp_path / "g.pdf"))
    assert pages == 1 and "Click Save in Excel" in " ".join(text.split())


# ---------------------------------------------------------------- wiring: exporter, CLI, launcher, controller


@pytest.fixture
def recording(tmp_path, screen_image):
    from recordsteps import bundle

    folder = bundle.new_bundle_dir(tmp_path, stamp="w")
    bundle.save_image(folder, "step-001", screen_image)
    bundle.save_guide(folder, make_guide(make_step(1), make_step(2, image="", note=PRIVATE_NOTE)))
    return folder


def test_export_bundle_writes_word_and_pdf(recording, qapp):
    from recordsteps.exporter import export_bundle

    result = export_bundle(recording)
    assert result.word == recording / "export" / "guide.docx" and result.word.is_file()
    assert result.pdf == recording / "export" / "guide.pdf" and result.pdf.is_file()
    assert result.problems == ()
    assert len(docx.Document(str(result.word)).inline_shapes) == 1


def test_a_failing_word_export_does_not_sink_the_rest(recording, qapp, monkeypatch):
    from recordsteps import exporter

    def locked(*a, **k):
        raise PermissionError("guide.docx is open in Word")

    monkeypatch.setattr(exporter, "render_docx", locked)
    result = exporter.export_bundle(recording)
    assert result.word is None and result.pdf is not None and result.html.is_file()
    assert result.problems == ("Word export failed: guide.docx is open in another program; close it and export "
                               "again",)


def test_cli_export_lists_word_and_pdf_and_uses_a_template(recording, tmp_path, capsys, qapp):
    from recordsteps.__main__ import _cli

    template = tmp_path / "brand.docx"
    base = docx.Document()
    base.styles["Normal"].font.name = "Georgia"
    base.save(str(template))
    assert _cli(["export", str(recording), "--word-template", str(template)]) == 0
    out = capsys.readouterr().out
    assert "Word:" in out and "PDF:" in out
    assert docx.Document(str(recording / "export" / "guide.docx")).styles["Normal"].font.name == "Georgia"


def test_cli_export_reports_problems_with_its_exit_code(recording, tmp_path, capsys, qapp):
    from recordsteps.__main__ import _cli

    assert _cli(["export", str(recording), "--word-template", str(tmp_path / "missing.docx")]) == 3
    assert "Word export failed" in capsys.readouterr().err


def test_launcher_offers_word_and_pdf(qapp, tmp_path):
    from recordsteps.ui.launcher import Launcher

    launcher = Launcher(recordings_dir=tmp_path)
    opened = []
    launcher.open_path.connect(opened.append)
    launcher.show_result("done", word=tmp_path / "g.docx", pdf=tmp_path / "g.pdf")
    assert not launcher.open_word_button.isHidden() and not launcher.open_pdf_button.isHidden()
    launcher.open_word_button.click()
    launcher.open_pdf_button.click()
    assert opened == [tmp_path / "g.docx", tmp_path / "g.pdf"]
    launcher.show_result("again")
    assert launcher.open_word_button.isHidden()


def test_controller_passes_word_pdf_and_problems_to_the_launcher(qapp, tmp_path):
    from recordsteps.exporter import ExportResult
    from recordsteps.ui.controller import Controller
    from recordsteps.ui.launcher import Launcher
    from recordsteps.ui.pill import RecordingPill
    from tests.test_recorder_ui import FakeRecorder

    def exporter(root):
        root = Path(root)
        return ExportResult(html=root / "g.html", markdown=root / "g.md", review=root / "r.csv",
                            word=None, pdf=root / "g.pdf", problems=("Word export failed: locked",))

    ctl = Controller(Launcher(), RecordingPill(), None, recorder_factory=FakeRecorder, exporter=exporter,
                     root=tmp_path, countdown_seconds=0, open_file=lambda p: None,
                     run_async=lambda work, done: done(work()))
    ctl.start_recording()
    ctl.stop()
    assert "Word export failed: locked" in ctl.launcher.result_text()
    assert ctl.launcher.open_word_button.isHidden() and not ctl.launcher.open_pdf_button.isHidden()


# ---------------------------------------------------------------- review follow-ups


def test_pdf_reports_a_file_it_cannot_write(tmp_path, qapp):
    with pytest.raises(OSError):
        render_pdf(make_guide(make_step(1)), {}, tmp_path / "missing-folder" / "g.pdf")


def test_pdf_never_leaves_a_temporary_file(tmp_path, qapp):
    render_pdf(make_guide(make_step(1)), {}, tmp_path / "g.pdf")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["g.pdf"]


def test_pdf_needs_a_gui_application(tmp_path, monkeypatch):
    from recordsteps import export_pdf

    monkeypatch.setattr(export_pdf.QGuiApplication, "instance", staticmethod(lambda: None))
    with pytest.raises(RuntimeError):
        render_pdf(make_guide(), {}, tmp_path / "g.pdf")


def test_a_first_step_that_does_not_fit_under_the_header_moves_to_page_two():
    assert plan_pages(header=500, blocks=[600], page_height=1000, gap=0) == [[], [0]]


def test_pdf_handles_very_long_titles(tmp_path, qapp):
    long_title = "Click **" + "Save " * 400 + "**"
    pages, text = pdf_text(render_pdf(make_guide(make_step(1, title=long_title)), {}, tmp_path / "g.pdf"))
    assert pages == 1 and "Page 1 of 1" in text


def stripped_template(tmp_path, *remove):
    template = tmp_path / "bare.docx"
    base = docx.Document()
    for name in remove:
        element = base.styles[name].element
        element.getparent().remove(element)
    base.save(str(template))
    return template


def test_a_template_without_built_in_styles_still_gets_a_proper_guide(step_images, tmp_path):
    template = stripped_template(tmp_path, "Title", "Subtitle", "Heading 2")
    doc = docx.Document(str(render_docx(make_guide(make_step(1)), step_images, tmp_path / "g.docx",
                                        template=template)))
    assert doc.paragraphs[0].style.name == "Title"
    assert "w:outlineLvl" in doc.styles["Heading 2"].element.xml  # steps stay in the navigation pane


def test_a_templates_own_footer_is_kept(step_images, tmp_path):
    template = tmp_path / "acme.docx"
    base = docx.Document()
    base.sections[0].footer.paragraphs[0].text = "ACME Corp - Confidential"
    base.save(str(template))
    doc = docx.Document(str(render_docx(make_guide(make_step(1)), step_images, tmp_path / "g.docx",
                                        template=template)))
    footer = doc.sections[-1].footer.paragraphs[0].text
    assert footer == "ACME Corp - Confidential"


def test_control_characters_are_cleaned_everywhere(step_images, tmp_path):
    step = make_step(1, app="Ex\x00cel", image="", note="Private\x07 window", title="Click **Sa\x01ve**")
    doc = docx.Document(str(render_docx(make_guide(step), {}, tmp_path / "g.docx")))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Excel" in text and "Private window" in text and "Click Save" in text


def test_word_dates_are_today(step_images, tmp_path):
    from datetime import datetime

    doc = docx.Document(str(render_docx(make_guide(), {}, tmp_path / "g.docx")))
    assert doc.core_properties.created.year == datetime.now().year


def test_unreadable_screenshots_are_reported(recording, qapp):
    from recordsteps.exporter import export_bundle

    (recording / "images" / "step-001.png").write_bytes(b"not a png")
    result = export_bundle(recording)
    assert any("1 screenshot couldn't be exported (step-001)" in p for p in result.problems)


def test_a_file_open_in_another_program_gets_a_plain_explanation(recording, qapp, monkeypatch):
    from recordsteps import exporter

    def locked(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(exporter, "render_pdf", locked)
    result = exporter.export_bundle(recording)
    assert "PDF export failed: guide.pdf is open in another program; close it and export again" in result.problems
