"""Word export: an editable .docx built on named styles, so people (or a company template) can
restyle the whole guide from Word's Styles pane instead of fixing each step by hand.

Paragraph styles: Title, Subtitle, Step Title (based on Heading 2, so steps appear in Word's
navigation pane) and Step Note. Character styles: Step Number and Step Element (the clicked
control's name). No direct formatting is applied to step text, so restyling a style restyles
every step.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import docx
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Inches, Pt, RGBColor
from PySide6.QtGui import QImageReader

from .emphasis import plain, segments
from .model import Guide, Step, display_title

STEP_TITLE_STYLE = "Step Title"
STEP_NOTE_STYLE = "Step Note"
STEP_NUMBER_STYLE = "Step Number"
STEP_ELEMENT_STYLE = "Step Element"
MAX_IMAGE_HEIGHT = Inches(3.6)  # two steps fit on a Letter page
INDENT = Inches(0.35)
INK = RGBColor(0x1C, 0x1A, 0x18)
MUTED = RGBColor(0x66, 0x64, 0x61)
EMBER = RGBColor(0xD5, 0x31, 0x00)
BODY_FONT = "Calibri"  # on every Windows PC with Office; Aptos isn't on older versions
# XML 1.0 forbids most control characters and lone surrogates; window titles and OCR text can
# contain them.
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def _clean(text: str) -> str:
    return _CONTROL.sub("", text)


# ------------------------------------------------------------------ styles

def _paragraph_style(document, name: str, base: str | None, size: float, *, bold: bool = False,
                     outline_level: int | None = None):
    """Get a paragraph style, creating a plain version when a template doesn't define it."""
    try:
        return document.styles[name]
    except KeyError:
        pass
    style = document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    if base:
        style.base_style = document.styles[base]
    style.font.size, style.font.bold = Pt(size), bold
    if outline_level is not None:  # what puts a heading in Word's navigation pane
        level = OxmlElement("w:outlineLvl")
        level.set(qn("w:val"), str(outline_level))
        style.element.get_or_add_pPr().append(level)
    return style


def _character_style(document, name: str, *, bold: bool, color: RGBColor | None = None):
    try:
        return document.styles[name]
    except KeyError:
        style = document.styles.add_style(name, WD_STYLE_TYPE.CHARACTER)
        style.font.bold = bold
        if color is not None:
            style.font.color.rgb = color
        return style


def _ensure_styles(document) -> None:
    """Make sure every style the guide uses exists; a company template's own versions win."""
    _paragraph_style(document, "Title", "Normal", 26, bold=True)
    _paragraph_style(document, "Subtitle", "Normal", 11)
    _paragraph_style(document, "Heading 2", "Normal", 13, bold=True, outline_level=1)
    if STEP_TITLE_STYLE not in {s.name for s in document.styles}:
        style = _paragraph_style(document, STEP_TITLE_STYLE, "Heading 2", 13)
        style.font.bold, style.font.color.rgb = False, INK
        fmt = style.paragraph_format
        fmt.space_before, fmt.space_after, fmt.keep_with_next = Pt(18), Pt(6), True
        fmt.tab_stops.add_tab_stop(INDENT, WD_TAB_ALIGNMENT.LEFT)
        fmt.left_indent, fmt.first_line_indent = INDENT, -INDENT
    if STEP_NOTE_STYLE not in {s.name for s in document.styles}:
        style = _paragraph_style(document, STEP_NOTE_STYLE, "Normal", 11)
        style.font.italic, style.font.color.rgb = True, MUTED
        style.paragraph_format.left_indent = INDENT
    _character_style(document, STEP_NUMBER_STYLE, bold=True, color=EMBER)
    _character_style(document, STEP_ELEMENT_STYLE, bold=True)


def _new_document(template: Path | None):
    if template is not None:
        if not Path(template).is_file():
            raise FileNotFoundError(f"Word template not found: {template}")
        return docx.Document(str(template))
    document = docx.Document()
    normal = document.styles["Normal"]
    normal.font.name, normal.font.size, normal.font.color.rgb = BODY_FONT, Pt(11), INK
    document.styles["Title"].font.color.rgb = INK  # the stock template's Office blue isn't ours
    subtitle = document.styles["Subtitle"].font
    subtitle.color.rgb, subtitle.italic, subtitle.size = MUTED, False, Pt(11)
    return document


# ------------------------------------------------------------------ content

def _image_width(path: Path, max_width: int) -> int | None:
    """Widest size that fits the text column and MAX_IMAGE_HEIGHT; None if the file isn't an image."""
    size = QImageReader(str(path)).size()
    if size.width() <= 0 or size.height() <= 0:
        return None
    return int(min(max_width, MAX_IMAGE_HEIGHT * size.width() / size.height()))


def _add_title(document, number: int, step: Step) -> None:
    paragraph = document.add_paragraph(style=STEP_TITLE_STYLE)
    paragraph.add_run(f"{number}\t", style=STEP_NUMBER_STYLE)
    for text, bold in segments(display_title(step)):
        paragraph.add_run(_clean(text), style=STEP_ELEMENT_STYLE if bold else None)


def _add_picture(document, number: int, step: Step, path: Path, max_width: int) -> bool:
    width = _image_width(path, max_width)
    if width is None:
        return False
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = INDENT
    shape = paragraph.add_run().add_picture(str(path), width=Emu(width))
    alt = _clean(f"Screenshot for step {number}: {plain(display_title(step))}")
    shape._inline.docPr.set("descr", alt)  # alt text for screen readers
    return True


def _add_page_numbers(section) -> None:
    """'Made with Record Steps · Page N', unless a template brought its own footer."""
    footer = section.footer
    if any(p.text.strip() for p in footer.paragraphs) or footer._element.xpath(".//w:drawing"):
        return
    paragraph = footer.paragraphs[0]
    label = paragraph.add_run("Made with Record Steps · Page ")
    number = paragraph.add_run("1")  # Word replaces this with the real page number
    for run in (label, number):
        run.font.size, run.font.color.rgb = Pt(9), MUTED
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE \\* MERGEFORMAT")  # MERGEFORMAT keeps the run's size and color on update
    number._r.addprevious(field)
    field.append(number._r)  # the styled run sits inside the field, so the number keeps its look


def _meta(guide: Guide) -> str:
    count = len(guide.steps)
    apps = list(dict.fromkeys(s.app for s in guide.steps if s.app))
    parts = [f"Recorded {guide.created[:10]}", f"{count} step{'' if count == 1 else 's'}", ", ".join(apps)]
    return " · ".join(p for p in parts if p)


def render_docx(guide: Guide, images: Mapping[str, Path], out_path: Path, *, template: Path | None = None) -> Path:
    """images maps step id -> an annotated screenshot file. Returns out_path."""
    document = _new_document(template)
    _ensure_styles(document)
    props, now = document.core_properties, datetime.now()
    props.title, props.author, props.last_modified_by, props.comments = _clean(guide.title), "", "", ""
    props.created = props.modified = now
    document.add_paragraph(_clean(guide.title), style="Title")
    document.add_paragraph(_clean(_meta(guide)), style="Subtitle")
    section = document.sections[-1]  # content is appended to the last section
    max_width = section.page_width - section.left_margin - section.right_margin - INDENT
    for number, step in enumerate(guide.steps, start=1):
        _add_title(document, number, step)
        pictured = step.id in images and _add_picture(document, number, step, Path(images[step.id]), max_width)
        if not pictured and step.note:
            document.add_paragraph(_clean(step.note), style=STEP_NOTE_STYLE)
    _add_page_numbers(section)
    document.save(str(out_path))
    return Path(out_path)
