"""Small Win32 queries: the window under a point, monitor DPI, double-click settings, and
keeping our own windows out of screenshots."""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from functools import cache

from ..apps import is_private
from ..model import Rect
from ..pipeline import WindowHit

log = logging.getLogger(__name__)

GA_ROOT = 2
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0
SM_CXDOUBLECLK = 36
SM_CYDOUBLECLK = 37
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+: the window is left out of every screen capture
SPI_GETCLIENTAREAANIMATION = 0x1042
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TITLE_MAX = 512
DWMWA_CLOAKED = 14

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.WindowFromPoint.argtypes = [wintypes.POINT]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
_user32.MonitorFromPoint.restype = wintypes.HMONITOR
_user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
_user32.GetDoubleClickTime.restype = wintypes.UINT
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_ENUMPROC, wintypes.LPARAM]
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]


@cache
def _shcore():
    try:
        dll = ctypes.WinDLL("shcore")
    except OSError:  # very old Windows: no per-monitor DPI
        return None
    dll.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, ctypes.c_int, ctypes.POINTER(wintypes.UINT),
                                     ctypes.POINTER(wintypes.UINT)]
    dll.GetDpiForMonitor.restype = ctypes.c_long
    return dll


@cache
def _dwm():
    try:
        dll = ctypes.WinDLL("dwmapi")
    except OSError:
        return None
    dll.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    return dll


def process_path(pid: int) -> str:
    """Adapted from SnipForge's winrects._process_path (MIT)."""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        return buf.value if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else ""
    finally:
        _kernel32.CloseHandle(handle)


def window_at(x: int, y: int) -> WindowHit:
    """The top-level window under a physical point: its process and title."""
    hwnd = _user32.WindowFromPoint(wintypes.POINT(x, y))
    root = _user32.GetAncestor(hwnd, GA_ROOT) if hwnd else None
    if not root:
        return WindowHit(pid=0, title="", process_path="")
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(root, ctypes.byref(pid))
    title = ctypes.create_unicode_buffer(TITLE_MAX)
    _user32.GetWindowTextW(root, title, TITLE_MAX)
    return WindowHit(pid=pid.value, title=title.value.strip(), process_path=process_path(pid.value))


def dpi_at(x: int, y: int) -> int:
    shcore = _shcore()
    if shcore is None:
        return 96  # very old Windows: assume 100% scaling
    monitor = _user32.MonitorFromPoint(wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST)
    dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
    if shcore.GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
        return int(dpi_x.value)
    return 96


def _cloaked(hwnd) -> bool:
    """Windows on another virtual desktop (or hidden app frames) are 'cloaked': not on screen."""
    dwm = _dwm()
    if dwm is None:
        return False
    value = ctypes.c_int(0)
    dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    return value.value != 0


def _overlaps(rect: wintypes.RECT, monitor: Rect) -> bool:
    horizontal = rect.left < monitor.right and rect.right > monitor.x
    return horizontal and rect.top < monitor.bottom and rect.bottom > monitor.y


def private_window_on(monitor: Rect) -> bool:
    """True if any visible private-browsing window overlaps the monitor, even one not clicked."""
    found = False
    title = ctypes.create_unicode_buffer(TITLE_MAX)
    rect = wintypes.RECT()

    def visit(hwnd, _lparam):
        nonlocal found
        if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd) or _cloaked(hwnd):
            return True
        _user32.GetWindowTextW(hwnd, title, TITLE_MAX)
        if is_private(title.value) and _user32.GetWindowRect(hwnd, ctypes.byref(rect)) and _overlaps(rect, monitor):
            found = True
            return False  # stop enumerating
        return True

    _user32.EnumWindows(_ENUMPROC(visit), 0)
    return found


def double_click_metrics() -> tuple[int, int, int]:
    """Windows' double-click time (ms) and half the allowed movement box (px)."""
    return (int(_user32.GetDoubleClickTime()), max(1, _user32.GetSystemMetrics(SM_CXDOUBLECLK) // 2),
            max(1, _user32.GetSystemMetrics(SM_CYDOUBLECLK) // 2))


def exclude_from_capture(hwnd: int) -> bool:
    """Keep a window (the recording pill, the click flash) out of our own screenshots. Needs
    Windows 10 2004 or later; it also hides the window from screen sharing."""
    ok = bool(_user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE))
    if not ok:
        log.warning("couldn't exclude a window from capture (error %s); it may appear in screenshots",
                    ctypes.get_last_error())
    return ok


def animations_enabled() -> bool:
    value = wintypes.BOOL(True)
    if _user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0):
        return bool(value.value)
    return True
