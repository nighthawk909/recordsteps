# Record Steps (Phase 0 prototype)

Record a workflow once and get a step-by-step guide. You click through a task while a red
recording pill is on screen. Each click becomes a step with a screenshot, a ring around what
you clicked, and a title written for you:

> 1. Click **Save report** in Python
> 2. Click the **Remember me** checkbox
> 3. Click the **Email** field
> 4. Open the **Advanced** tab

Press **Stop & build** and you get `guide.html` (one file, screenshots inside), `guide.docx`
(editable Word, built on named styles), `guide.pdf` (searchable, a step never splits across
pages), `guide.md` with images, and the raw `guide.json` that every future export
(click-through demo, video) will be built from.

This is the Phase 0 prototype from the research blueprint. Its job is to answer one question
before months go into an editor: **are the step titles Windows gives us good enough on real
apps?** It is Windows-only and deliberately small.

## What it promises (and how)

| Promise | How the code keeps it |
|---|---|
| Records only while the pill is visible | The mouse listener and the screen-frame buffer exist only between Record/Resume and Pause/Stop (`recorder.py`). Outside a recording the app listens to and watches nothing; Pause and Stop drop the buffered frames, which are never written to disk. |
| Never records keystrokes | There is no keyboard listener at all. Only left/right button presses are read (`win/rawinput.py`). |
| Never reads what's typed in a field | Text boxes, combo boxes and documents are never OCR'd; a click there is named from UI Automation or not at all. |
| No screenshots of password fields | If UI Automation reports a password field anywhere under the pointer, the step keeps its title but no screenshot. |
| Skips private browsing windows | A click in an InPrivate/Incognito/Private/Tor window gets a placeholder step with no screenshot and no window title. If such a window is merely visible on the same monitor, the step gets no screenshot. Detection reads English window titles only. |
| Ignores its own windows | Clicks on the pill or launcher are dropped; the pill and click flash are left out of every screenshot (`SetWindowDisplayAffinity`). |
| Never uploads anything | No network code. Recordings live in `Documents\Record Steps`; if Documents syncs to OneDrive (or Dropbox, Google Drive, iCloud), the launcher says so, because that service will upload them. |
| Discard really discards | Deletes the recording folder (retrying while antivirus holds new files), only folders it created, never links. If it can't, it says so and names the folder. |
| Safe to open recordings from others | `guide.json` step ids and image paths are validated, and exports refuse any path outside the recording folder. `review.csv` neutralises spreadsheet formulas. HTML and Markdown escape everything taken from the screen. |

Screenshots are of the whole monitor you clicked on, so anything else on that monitor is in
them. The exports crop around the click; the originals in `images/` are full size, so share
the `export` folder, not the whole recording.

## Run it

```bash
pip install -e .[dev]
```

```bash
python -m recordsteps
```

Ctrl+R or **Record steps** starts a 3-second countdown (or press **Start now**). Pause,
Stop & build, and Discard are on the pill. The finished guide opens in your browser. Clicks
that couldn't be captured are counted in the result message; details go to
`%LOCALAPPDATA%\Record Steps\recordsteps.log`.

```bash
python -m recordsteps export "C:\Users\you\Documents\Record Steps\2026-10-17 0920 Recording"
```

```bash
python -m recordsteps stats
```

`export` rebuilds the HTML, Word, PDF, Markdown and review sheet for a recording (after you
edit titles in guide.json, for example). Add `--word-template brand.docx` to build the Word
file on your own template: its Normal, Title and heading styles (fonts, colors) carry
through, and Record Steps adds two styles of its own, **Step Title** and **Step Note**, that
you can restyle once in Word's Styles pane. `stats` prints the Phase 0 numbers across all
recordings.

## How it works

```
Raw Input thread ──clicks──▶ queue ──▶ capture worker ──▶ guide.json + images/
  (button presses only)                 1. which window? (skip ours, skip private)
                                        2. the frame from just before the click (Desktop Duplication buffer; mss fallback)
                                        3. what was clicked? (UI Automation, MTA thread)
                                        4. no name? read the screen around it (Windows OCR)
                                        5. title it, save atomically
Qt GUI ◀── queued signals (step count, click flash) ──┘
```

- **Element lookup** (`targets.py`): UI Automation returns the deepest element under the
  pointer, often a label inside a button. We walk up to six levels to the nearest control a
  person would name, borrowing the label's text if that control has none.
- **Titles** (`titles.py`): wording follows the control type ("Open the **Advanced** tab",
  "Click the **Email** field"). The app is named on the first step and whenever it changes.
- **Remote desktops and Citrix** (`apps.py`): their windows are one picture to UI Automation,
  so we go straight to OCR around the click.
- **Double-clicks** use Windows' own double-click time and distance and merge into one step.

### Why Raw Input instead of a mouse hook

SnipForge uses a low-level keyboard hook for its shortcut. A low-level *mouse* hook in
Python is risky: Windows runs it inside every mouse event, so while Python is busy saving a
screenshot the whole system's mouse waits, and Windows silently removes hooks that answer
slowly. Raw Input is passive: Windows posts a copy of each button press to our own queue and
nothing waits for us. It also can't block or change anyone's input, which is an easier story
for IT and endpoint-security reviews.

### What came from SnipForge

App-name lookup (`apps.py`), the Windows OCR wrapper (`ocr.py`), process paths
(`win/system.py`) and the private-window markers are adapted from
[SnipForge](https://github.com/nighthawk909/snipforge) (MIT; see `NOTICE`). So are the
dedicated-thread-plus-message-loop pattern and the test layout.

## The recording format

```
2026-10-17 0920 Recording/
  .recordsteps          marks the folder as ours (Discard only deletes marked folders)
  guide.json            the guide; rewritten atomically after every step
  images/step-001.png   full-monitor screenshots, never modified
  export/guide.html     single file, screenshots embedded, ring drawn with CSS
  export/guide.docx     Word: Step Title / Step Note styles, alt text, page numbers
  export/guide.pdf      Letter, searchable text, two steps a page, "Page N of M"
  export/guide.md       numbered list
  export/images/        cropped, annotated screenshots (used by Markdown, Word and PDF)
  review.csv            one row per step for the Phase 0 review
```

`recordsteps/guide.schema.json` documents `guide.json` (JSON Schema 2020-12) so other tools
can read and write it. Coordinates are physical pixels relative to each step's screenshot.

## Phase 0 test protocol

The gate from the research report: **most steps need no retitling.** To measure it:

1. **Use your own apps and accounts only.** Don't record company systems or data for this
   test.
2. **Record about 50 steps in total** across:
   - Excel: ribbon buttons, cells, sheet tabs, dialogs
   - File Explorer: navigation pane, file list, context menu
   - A browser (Edge or Chrome): links, buttons, form fields on a few public sites
   - Remote Desktop to a personal VM, if you have one (tests the OCR fallback)
   - One or two other apps you use daily
3. **Review**: open each recording's `review.csv` in Excel, and in `title_ok` put `y` if
   you'd keep the title as-is, `n` if you'd rewrite it (put your version in `better_title`).
4. **Run** `python -m recordsteps stats`.

Suggested pass marks (adjust as you learn):

| Measure | Pass |
|---|---|
| Titles accepted as-is | 75% or more |
| Steps with a name (UI Automation or OCR) | 85% or more |
| Whole step, 95th percentile | under 500 ms |

If titles fall short, the fallback plan is OCR-first titles before any editor work.

## What we already know

From the first runs on a 3440×1440 monitor:

- UI Automation named every control in the test window correctly, and named items in the
  Claude desktop app's sidebar (Electron).
- **Screenshots took 115–140 ms** with GDI on that monitor. The click arrives on mouse-down,
  so a fast app could react before the screenshot landed and show the *after* state. Fixed with
  a rolling frame buffer (`frames.py`, `framebuffer.py`, `win/dda.py`). While recording, DXGI
  Desktop Duplication (through dxcam, MIT) is polled about 10 times a second. Desktop
  Duplication only hands over a frame when the screen changed, stamped with the time of that
  change. A step uses the newest frame whose content predates the click by at least 20 ms.
  Click and frame times are put on one clock by lining QueryPerformanceCounter up with
  GetTickCount64, and the 20 ms covers what that can get wrong. The log records each frame's
  age.
  - **Fallback.** With no frame from before the click, the step falls back to a GDI screenshot
    taken after the click. That happens when the buffer isn't running, the click is over a
    second old, or capture stalled.
  - **Still screens.** On a screen that never changes, Desktop Duplication may hand over
    nothing at all. A monitor without frames then gets one GDI snapshot, stamped when the
    snapshot finished.
  - **Display asleep or off.** Desktop Duplication then reports nothing, not even pointer
    moves, while GDI screenshots still work. Seen on this PC with the monitor asleep: the
    desktop end-to-end test's clicks changed the test window, but nothing was reported. So
    "nothing changed" is only trusted from a duplication that has reported something.
    Frames stop being vouched for when the pointer keeps moving on a monitor without a
    report, and those steps use the screenshot taken after the click.
  - **CPU.** 7.6% of one core while the screen changed on every poll (the worst case for an
    idle recording); 1.5% on a still screen. It started at 20%: reusing frame memory and
    letting the GPU copy finish before mapping removed most of it.
  - **Speed.** Getting a step's frame takes **4–6.5 ms**, a copy of the frame (`capture_ms`).
  - **Freshness.** For a click handled right away, the chosen frame was last confirmed current a
    median **50–65 ms** before the click (max 120 ms; measured with simulated clicks, no input).
  - **Memory.** About 20 MB per frame. A still screen keeps one or two frames. A constantly
    changing screen keeps up to 12 per monitor (about 240 MB) for the last second.
  - **Kept out of frames.** The pill and click flash (`WDA_EXCLUDEFROMCAPTURE`) are absent from
    duplicated frames, checked by reading an excluded and a normal window out of a frame.
    Frames stay in memory only, and Pause and Stop drop everything. While a private window is
    visible on a monitor, that monitor's frames are dropped. Frames taken up to a second after
    one was last seen are dropped too, so one captured just before it closed isn't kept. The
    private-window scan skips Record Steps' own windows, whose titles can't safely be read from
    another thread.
  - **First second.** The first recording in a session imports dxcam (about 1 s), and Resume
    reopens capture. Clicks in those moments use the fallback. A monitor that Desktop
    Duplication can't open (rotated, or held by another capture app) uses the fallback for the
    whole recording.
- A click on a title bar has no useful name; OCR found nothing there and cost 0.4 s. The
  title falls back to "Click in **window title**".

Known limits:

- The pill is hidden from screen sharing too (Teams, Zoom), because it is excluded from all
  capture. People watching a share won't see that you're recording.
- The pill stays on the primary monitor and doesn't follow virtual-desktop switches; recording
  doesn't pause when the PC locks. Both are on the list.
- Private-window detection matches English window titles (InPrivate, Incognito, Private
  Browsing, Private window, Tor Browser).
- Clicks on windows running as administrator may not be seen (Windows isolates them).
- Chrome builds its accessibility tree lazily; the first click on a page can come back
  unnamed (OCR then fills in).
- No typing steps, no scroll or drag steps, no editor yet. Windows only. Not code-signed.

## Tests

```bash
python -m pytest
```

347 tests, 97% line coverage. They include real Windows checks that need no input: screen
capture (GDI and Desktop Duplication), UI Automation, Windows OCR, the private-window scan, and
raw-input parsing.

```bash
QT_QPA_PLATFORM=windows python -m pytest -m desktop
```

The end-to-end desktop tests **move and click your real mouse** for about ten seconds on a
test window they open. Run them only when you're not using the PC.

## Reviews

Before the first commit the code had a code review and a security review. No critical
issues. Everything rated high or medium was fixed with a regression test
(`tests/test_review_fixes.py`): path validation for `guide.json`, honest discard, password and
text-field handling, the wider private-window check, formula-safe `review.csv`, failure
reporting, and COM/listener cleanup. Still open, by design for Phase 0: unsigned builds, no
event-log entries, unpinned dependencies, auto-pause on lock.

The Word and PDF exports had their own code review. Fixed with tests: a PDF that couldn't be
written no longer reports success (it's written to a temporary file and swapped in), a
company template keeps its own footer and gets any built-in styles it lacks, step text uses
character styles instead of direct formatting, screenshots load one at a time, and a file
left open in Word or a PDF viewer gets a plain "close it and export again" message.

## License

Apache-2.0 (see `LICENSE`), the license recommended in the research. Code adapted from
SnipForge keeps its MIT notice in `NOTICE`.
