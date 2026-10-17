import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from recordsteps.model import Guide, Rect, Step, Target, Timing


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def make_step(index: int = 1, **overrides) -> Step:
    fields = dict(
        id=f"step-{index:03d}",
        action="click",
        at="2026-10-17T09:30:00",
        app="Excel",
        process="EXCEL.EXE",
        window="Q3 forecast.xlsx - Excel",
        monitor=Rect(0, 0, 1920, 1080),
        dpi=96,
        image=f"images/step-{index:03d}.png",
        image_size=(1920, 1080),
        click=(1221, 655),
        target=Target(name="Save", role="Button", source="uia", bbox=Rect(1184, 642, 76, 28)),
        title="Click **Save** in Excel",
        timing=Timing(capture_ms=21.5, uia_ms=12.0, ocr_ms=0.0, total_ms=40.2),
    )
    fields.update(overrides)
    return Step(**fields)


def make_guide(*steps: Step) -> Guide:
    return Guide(id="g-1", title="Recorded steps", created="2026-10-17T09:29:00", steps=tuple(steps))


@pytest.fixture
def step_factory():
    return make_step


@pytest.fixture
def guide_factory():
    return make_guide


@pytest.fixture
def screen_image(qapp):
    """A fake 1920x1080 screenshot: light background, a dark 'Save' button where make_step clicks."""
    img = QImage(1920, 1080, QImage.Format_RGB32)
    img.fill(QColor("#F3F3F3"))
    for x in range(1184, 1260):
        for y in range(642, 670):
            img.setPixelColor(x, y, QColor("#1C1A18"))
    return img
