# Record Steps (Phase 0 prototype)

Record a workflow once and get a step-by-step guide. You click through a task while a red
recording pill is on screen. Each click becomes a step with a screenshot, a ring around what
you clicked, and a title written for you:

> 1. Click **Save report** in Python
> 2. Click the **Remember me** checkbox
> 3. Click the **Email** field
> 4. Open the **Advanced** tab

Press **Stop & build** and you get `guide.html` (one file, screenshots inside), `guide.md`
with images, and the raw `guide.json` that every future export (Word, PDF, click-through
demo, video) will be built from.

This is the Phase 0 prototype from the research blueprint. Its job is to answer one question
before months go into an editor: **are the step titles Windows gives us good enough on real
apps?** It is Windows-only and deliberately small.

## What it promises (and how)

| Promise | How the code keeps it |
|---|---|
| Records only while the pill is visible | The mouse listener exists only between Record/Resume and Pause/Stop (`recorder.py`). Outside a recording the app listens to nothing. |
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

`export` rebuilds the HTML, Markdown and review sheet for a recording (after you edit titles
in guide.json, for example). `stats` prints the Phase 0 numbers across all recordings.

## How it works

```
Raw Input thread ──clicks──▶ queue ──▶ capture worker ──▶ guide.json + images/
  (button presses only)                 1. which window? (skip ours, skip private)
                                        2. screenshot the monitor (mss)
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
  export/guide.md       numbered list
  export/images/        cropped, annotated screenshots for the Markdown
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
- **Screenshots take 115–140 ms** with GDI on that monitor. The click arrives on mouse-down,
  so a fast app can react before the screenshot lands and show the *after* state. Next fix:
  keep a rolling frame buffer (DXGI Desktop Duplication) and save the frame from just before
  the click.
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

242 tests, 96% line coverage. They include real Windows checks that need no input: screen
capture, UI Automation, Windows OCR, the private-window scan, and raw-input parsing.

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

## License

Apache-2.0 (see `LICENSE`), the license recommended in the research. Code adapted from
SnipForge keeps its MIT notice in `NOTICE`.
