"""Mouse clicks via Raw Input, only while recording.

Why not a low-level mouse hook (WH_MOUSE_LL, as SnipForge uses for its keyboard shortcut)?
A hook runs inside every mouse event: while Python is busy elsewhere, the whole system's mouse
waits, and Windows silently removes hooks that answer slowly. Raw Input is passive: Windows
posts a copy of each mouse event to our own message queue, and nothing waits for us. We read
button presses only; movement is ignored and nothing is stored here.
"""
from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes

from ..clicks import RawClick

log = logging.getLogger(__name__)

WM_INPUT = 0x00FF
WM_QUIT = 0x0012
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100  # receive input even when another app is in front
RIDEV_REMOVE = 0x00000001
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_GENERIC_MOUSE = 0x02
RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
HWND_MESSAGE = wintypes.HWND(-3)
LRESULT = ctypes.c_ssize_t


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT), ("dwFlags", wintypes.DWORD),
                ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD), ("hDevice", wintypes.HANDLE),
                ("wParam", wintypes.WPARAM)]


class _BUTTONS(ctypes.Structure):
    _fields_ = [("usButtonFlags", wintypes.USHORT), ("usButtonData", wintypes.USHORT)]


class _BUTTONS_UNION(ctypes.Union):
    _fields_ = [("ulButtons", wintypes.ULONG), ("s", _BUTTONS)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", wintypes.USHORT), ("u", _BUTTONS_UNION), ("ulRawButtons", wintypes.ULONG),
                ("lLastX", wintypes.LONG), ("lLastY", wintypes.LONG), ("ulExtraInformation", wintypes.ULONG)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
_user32.RegisterClassW.restype = wintypes.ATOM
_user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
_user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                    wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = LRESULT
_user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
_user32.RegisterRawInputDevices.restype = wintypes.BOOL
_user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID, ctypes.POINTER(wintypes.UINT),
                                    wintypes.UINT]
_user32.GetRawInputData.restype = wintypes.UINT
_user32.GetMessagePos.restype = wintypes.DWORD
_user32.GetMessageTime.restype = wintypes.LONG
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE

_FAILED = wintypes.UINT(-1).value


def _signed16(value: int) -> int:
    return ctypes.c_short(value & 0xFFFF).value


class MouseListener:
    """Calls on_click(RawClick) for each left/right button press, from its own thread.
    start() and stop() may be called repeatedly (pause/resume)."""

    def __init__(self, on_click: Callable[[RawClick], None]) -> None:
        self._on_click = on_click
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._ok = False
        self._proc = WNDPROC(self._wndproc)  # keep a reference or it is garbage-collected
        self._class_name = f"RecordStepsInput{id(self):x}"

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return self._ok
        self._ready.clear()
        self._ok = False
        self._thread = threading.Thread(target=self._run, name="recordsteps-input", daemon=True)
        self._thread.start()
        self._ready.wait(5.0)
        return self._ok

    def stop(self) -> None:
        if self._thread is None:
            return
        if self._thread.is_alive() and self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = 0

    def _run(self) -> None:
        hinst, hwnd, registered = None, None, False
        try:
            self._thread_id = _kernel32.GetCurrentThreadId()
            hinst = _kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName=self._class_name)
            registered = bool(_user32.RegisterClassW(ctypes.byref(wc)))
            hwnd = _user32.CreateWindowExW(0, self._class_name, None, 0, 0, 0, 0, 0, HWND_MESSAGE, None, hinst,
                                           None)
            device = RAWINPUTDEVICE(HID_USAGE_PAGE_GENERIC, HID_USAGE_GENERIC_MOUSE, RIDEV_INPUTSINK, hwnd)
            self._ok = bool(hwnd) and bool(_user32.RegisterRawInputDevices(ctypes.byref(device), 1,
                                                                            ctypes.sizeof(device)))
            if not self._ok:
                log.error("raw input registration failed (error %s)", ctypes.get_last_error())
            self._ready.set()
            self._pump()
        except Exception:
            log.exception("the click listener failed")
            self._ok = False
        finally:
            self._ready.set()
            self._teardown(hinst, hwnd, registered)

    def _pump(self) -> None:
        msg = wintypes.MSG()
        while self._ok and _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _teardown(self, hinst, hwnd, registered: bool) -> None:
        try:
            if self._ok or hwnd:
                remove = RAWINPUTDEVICE(HID_USAGE_PAGE_GENERIC, HID_USAGE_GENERIC_MOUSE, RIDEV_REMOVE, None)
                _user32.RegisterRawInputDevices(ctypes.byref(remove), 1, ctypes.sizeof(remove))
            if hwnd:
                _user32.DestroyWindow(hwnd)
            if registered:
                _user32.UnregisterClassW(self._class_name, hinst)
        except Exception:
            log.exception("cleaning up the click listener failed")

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_INPUT:
            try:
                self._read(lparam)
            except Exception:  # never let an exception unwind through Windows' callback
                log.exception("reading raw input failed")
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _read(self, lparam) -> None:
        size = wintypes.UINT(0)
        header = ctypes.sizeof(RAWINPUTHEADER)
        if _user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), header) == _FAILED:
            return
        buf = ctypes.create_string_buffer(max(size.value, ctypes.sizeof(RAWINPUT)))
        if _user32.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size), header) == _FAILED:
            return
        raw = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
        if raw.header.dwType != RIM_TYPEMOUSE:
            return
        flags = raw.mouse.u.s.usButtonFlags
        if flags & RI_MOUSE_LEFT_BUTTON_DOWN:
            button = "left"
        elif flags & RI_MOUSE_RIGHT_BUTTON_DOWN:
            button = "right"
        else:
            return
        pos = _user32.GetMessagePos()  # where the pointer was when this input happened
        click = RawClick(button, _signed16(pos), _signed16(pos >> 16), _user32.GetMessageTime() & 0xFFFFFFFF)
        self._on_click(click)
