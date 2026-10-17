"""UI Automation: what is under a screen point, and its ancestors.

Create and use a UiaClient on one thread (the capture worker). It joins that thread to COM's
multithreaded apartment, which UI Automation recommends for clients that aren't UI threads,
and keeps comtypes away from the Qt main thread (Qt needs that thread single-threaded).
"""
from __future__ import annotations

import logging
import sys

from ..model import Rect
from ..targets import LOOKUP_DEPTH, ElementInfo

log = logging.getLogger(__name__)
CLSID_CUIAutomation = "{ff48dba4-60ef-4201-aa87-54103eef594e}"
CONNECTION_TIMEOUT_MS = 1000  # an app that doesn't answer in time costs a name, not a frozen recorder
TRANSACTION_TIMEOUT_MS = 2000

CONTROL_TYPES = {
    50000: "Button", 50001: "Calendar", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
    50006: "Image", 50007: "ListItem", 50008: "List", 50009: "Menu", 50010: "MenuBar", 50011: "MenuItem",
    50012: "ProgressBar", 50013: "RadioButton", 50014: "ScrollBar", 50015: "Slider", 50016: "Spinner",
    50017: "StatusBar", 50018: "Tab", 50019: "TabItem", 50020: "Text", 50021: "ToolBar", 50022: "ToolTip",
    50023: "Tree", 50024: "TreeItem", 50025: "Custom", 50026: "Group", 50027: "Thumb", 50028: "DataGrid",
    50029: "DataItem", 50030: "Document", 50031: "SplitButton", 50032: "Window", 50033: "Pane", 50034: "Header",
    50035: "HeaderItem", 50036: "Table", 50037: "TitleBar", 50038: "Separator", 50039: "SemanticZoom",
    50040: "AppBar",
}


def prewarm() -> None:
    """Generate comtypes' UI Automation wrapper ahead of the first recording (it takes a few
    seconds once). Call on a throwaway thread so COM settings never touch the Qt thread."""
    try:
        _comtypes().client.GetModule("UIAutomationCore.dll")
    except Exception as exc:
        log.info("UI Automation prewarm failed (the first recording will do it): %s", exc)


def _comtypes():
    if "comtypes" not in sys.modules:
        sys.coinit_flags = 0  # COINIT_MULTITHREADED for the thread that first imports comtypes
    import comtypes
    import comtypes.client

    return comtypes


class UiaClient:
    def __init__(self) -> None:
        # Importing comtypes already initializes COM on the importing thread; this explicit call
        # covers later recordings on new worker threads, and close() balances it.
        comtypes = _comtypes()
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        self._com = comtypes
        try:
            self._m = comtypes.client.GetModule("UIAutomationCore.dll")
            self._auto = comtypes.client.CreateObject(CLSID_CUIAutomation, interface=self._m.IUIAutomation)
            self._tune_timeouts()
            self._walker = self._auto.ControlViewWalker
            self._root = self._auto.GetRootElement()
        except Exception:
            comtypes.CoUninitialize()
            raise

    def _tune_timeouts(self) -> None:
        try:
            tuned = self._auto.QueryInterface(self._m.IUIAutomation2)
            tuned.ConnectionTimeout = CONNECTION_TIMEOUT_MS
            tuned.TransactionTimeout = TRANSACTION_TIMEOUT_MS
        except Exception as exc:  # before Windows 8 there is no IUIAutomation2: default timeouts
            log.debug("UI Automation timeouts not set: %s", exc)

    def chain_at(self, x: int, y: int, depth: int = LOOKUP_DEPTH) -> tuple[ElementInfo, ...]:
        element = None
        for attempt in range(2):  # an element can vanish mid-call; Microsoft suggests one retry
            try:
                element = self._auto.ElementFromPoint(self._m.tagPOINT(x, y))
                break
            except self._com.COMError as exc:
                if attempt:
                    log.info("ElementFromPoint failed: %s", exc)
                    return ()
        chain: list[ElementInfo] = []
        while element and len(chain) < depth:
            chain.append(self._info(element))
            try:
                parent = self._walker.GetParentElement(element)
                if not parent or self._auto.CompareElements(parent, self._root):
                    break
            except self._com.COMError:
                break
            element = parent
        return tuple(chain)

    def _info(self, element) -> ElementInfo:
        name, role, bbox, password = "", "", None, False
        try:
            name = element.CurrentName or ""
            role = CONTROL_TYPES.get(element.CurrentControlType, "Custom")
            r = element.CurrentBoundingRectangle
            if r.right > r.left and r.bottom > r.top:
                bbox = Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)
            password = bool(element.CurrentIsPassword)
        except self._com.COMError as exc:
            log.debug("element property read failed: %s", exc)
        return ElementInfo(name=name, role=role, bbox=bbox, is_password=password)

    def close(self) -> None:
        self._walker = self._root = self._auto = None
        self._com.CoUninitialize()
