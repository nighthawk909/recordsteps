"""Friendly app names, remote sessions and private windows.

friendly_app_name, APP_NAMES and the version-info lookup are adapted from SnipForge
(github.com/nighthawk909/snipforge, snipforge/winrects.py at 37bb815, MIT license).
"""
from __future__ import annotations

import re

APP_NAMES = {
    "excel": "Excel", "winword": "Word", "powerpnt": "PowerPoint", "outlook": "Outlook", "olk": "Outlook",
    "onenote": "OneNote", "msedge": "Edge", "chrome": "Chrome", "firefox": "Firefox", "ms-teams": "Teams",
    "teams": "Teams", "pbidesktop": "Power BI", "explorer": "File Explorer", "code": "VS Code",
    "saplogon": "SAP GUI", "saplgpad": "SAP GUI", "slack": "Slack", "zoom": "Zoom", "notepad": "Notepad",
    "acrord32": "Acrobat", "acrobat": "Acrobat", "applicationframehost": "", "snipforge": "SnipForge",
    "mstsc": "Remote Desktop", "msrdc": "Remote Desktop", "wfica32": "Citrix", "cdviewer": "Citrix",
    "vmconnect": "Hyper-V", "systemsettings": "Settings",
}
# Programs that show another computer's screen as one picture: UI Automation can't see inside.
REMOTE_PROCESSES = frozenset({"mstsc", "msrdc", "wfica32", "cdviewer", "vmconnect", "vncviewer"})
# Window-title markers of private browsing (Edge, Chrome, Firefox, Brave, Tor). English only for now.
PRIVATE_MARKERS = ("inprivate", "incognito", "private browsing", "private window", "tor browser")


def _stem(exe_path: str) -> str:
    stem = re.split(r"[\\/]", exe_path or "")[-1]
    return re.sub(r"\.exe$", "", stem, flags=re.IGNORECASE)


def friendly_app_name(exe_path: str, description: str = "") -> str:
    """'C:/.../EXCEL.EXE' -> 'Excel'. Unknown programs use their file description, else a
    tidied file name."""
    stem = _stem(exe_path)
    if not stem:
        return ""
    known = APP_NAMES.get(stem.lower())
    if known is not None:
        return known
    if description.strip():
        return description.strip()[:40]
    return " ".join(part.capitalize() for part in re.split(r"[_\-\s]+", stem) if part)


def is_remote(process: str) -> bool:
    return _stem(process).lower() in REMOTE_PROCESSES


def is_private(title: str) -> bool:
    lowered = (title or "").lower()
    return any(marker in lowered for marker in PRIVATE_MARKERS)


def file_description(path: str) -> str:
    """The program's own name from its version info, e.g. 'Battle.net'."""
    if not path:
        return ""
    try:
        import win32api

        lang, codepage = win32api.GetFileVersionInfo(path, r"\VarFileInfo\Translation")[0]
        key = rf"\StringFileInfo\{lang:04x}{codepage:04x}\FileDescription"
        return win32api.GetFileVersionInfo(path, key) or ""
    except Exception:  # no version info, access denied, odd resources: the file name will do
        return ""


_NAMES: dict[str, str] = {}  # program path -> friendly name, kept for the session


def app_name(path: str) -> str:
    """Known apps by file name; others by their version info, read once per program."""
    if path not in _NAMES:
        known = _stem(path).lower() in APP_NAMES
        _NAMES[path] = friendly_app_name(path) if known else friendly_app_name(path, file_description(path))
    return _NAMES[path]
