"""Single-file HTML export. Screenshots are embedded; the click ring is drawn with CSS from the
step's box, so it stays crisp at any zoom. No fonts, scripts or images load from the network."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from html import escape

from .emphasis import segments
from .model import Guide, Step, display_title


@dataclass(frozen=True)
class ShotView:
    data_uri: str
    ring: tuple[float, float, float, float] | None  # left, top, width, height in % of the image
    dot: tuple[float, float]  # click point in % of the image
    full_href: str  # link to the full screenshot, relative to the HTML file ("" for none)


STYLE = """
:root{--paper:#FAF8F5;--surface:#FFFFFF;--line:#E5DFD7;--ink:#1C1A18;--ink2:#666461;--accent:#D53100;
--ring:#FF5A36;--badge-ink:#0E1116;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--paper:#0E1116;--surface:#151920;--line:#262B34;--ink:#EBF0F8;
--ink2:#A5AAB1;--accent:#FF5A36;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font:16px/1.55 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif}
main{max-width:980px;margin:0 auto;padding:40px max(16px,4vw) 64px}
header{margin-bottom:32px}
h1{font:700 clamp(26px,4vw,36px)/1.15 "Segoe UI Variable Display","Segoe UI",system-ui,sans-serif;margin:0 0 6px}
.meta{color:var(--ink2);font-size:14px;margin:0}
ol{list-style:none;margin:0;padding:0;display:grid;gap:36px}
.step{display:grid;grid-template-columns:32px minmax(0,1fr);gap:14px;break-inside:avoid}
.num{width:30px;height:30px;border-radius:50%;background:var(--ring);color:var(--badge-ink);
font:700 13px/30px "Segoe UI",system-ui,sans-serif;text-align:center}
.body{min-width:0;display:grid;gap:10px}
h2{font-size:18px;font-weight:500;line-height:1.4;margin:3px 0 0}
h2 strong{font-weight:700}
.where{color:var(--ink2);font-size:13px;margin:0}
figure{margin:0;position:relative;border:1px solid var(--line);border-radius:10px;overflow:hidden;
background:var(--surface)}
figure img{display:block;width:100%;height:auto}
.ring{position:absolute;border:3px solid var(--ring);border-radius:8px;
box-shadow:inset 0 0 0 1px #0E1116,0 0 0 2px #FFFFFF;pointer-events:none}
.dot{position:absolute;width:30px;height:30px;margin:-15px 0 0 -15px;border-radius:50%;
border:3px solid var(--ring);box-shadow:inset 0 0 0 1px #0E1116,0 0 0 2px #FFFFFF;pointer-events:none}
.full{font-size:13px;color:var(--accent)}
.note{color:var(--ink2);font-style:italic;margin:0}
footer{margin-top:48px;color:var(--ink2);font-size:12px}
@media print{body{background:#fff;color:#000}main{padding:0}figure{border-color:#ccc}}
"""


def _title_html(title: str) -> str:
    return "".join(f"<strong>{escape(text)}</strong>" if bold else escape(text) for text, bold in segments(title))


def _where(step: Step) -> str:
    parts = [p for p in (step.app, step.window) if p]
    return escape(" · ".join(parts))


def _figure(number: int, step: Step, view: ShotView) -> str:
    alt = escape(f"Screenshot for step {number}")
    overlay = ""
    if view.ring is not None:
        left, top, width, height = view.ring
        overlay = (f'<span class="ring" style="left:calc({left}% - 6px);top:calc({top}% - 6px);'
                   f'width:calc({width}% + 12px);height:calc({height}% + 12px)"></span>')
    else:
        overlay = f'<span class="dot" style="left:{view.dot[0]}%;top:{view.dot[1]}%"></span>'
    full = (f'<a class="full" href="{escape(view.full_href)}">Full screenshot</a>' if view.full_href else "")
    return (f'<figure><img src="{escape(view.data_uri)}" alt="{alt}" loading="lazy">{overlay}</figure>{full}')


def _step(number: int, step: Step, view: ShotView | None) -> str:
    where = f'<p class="where">{_where(step)}</p>' if _where(step) else ""
    if view is not None:
        visual = _figure(number, step, view)
    elif step.note:
        visual = f'<p class="note">{escape(step.note)}</p>'
    else:
        visual = ""
    return (f'<li class="step"><span class="num" aria-hidden="true">{number}</span><div class="body">'
            f'<h2><span class="sr">Step {number}: </span>{_title_html(display_title(step))}</h2>'
            f"{where}{visual}</div></li>")


def render_html(guide: Guide, shots: Mapping[str, ShotView]) -> str:
    count = len(guide.steps)
    apps: list[str] = []
    for step in guide.steps:
        if step.app and step.app not in apps:
            apps.append(step.app)
    meta = " · ".join(filter(None, [f"Recorded {guide.created[:10]}", f"{count} step{'' if count == 1 else 's'}",
                                    ", ".join(apps)]))
    items = "\n".join(_step(n, s, shots.get(s.id)) for n, s in enumerate(guide.steps, start=1))
    sr = ".sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}"
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{escape(guide.title)}</title><style>{STYLE}{sr}</style></head><body><main>"
        f"<header><h1>{escape(guide.title)}</h1><p class=\"meta\">{escape(meta)}</p></header>"
        f"<ol>\n{items}\n</ol>"
        "<footer>Made with Record Steps (prototype). Screenshots stay inside this file.</footer>"
        "</main></body></html>\n"
    )
