"""Opt-in real Windows tray test; no cooler access: python tests/tray_check.py."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import queue
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / ".deps")]
from radiator.tray import SystemTray


class NotifyIconIdentifier(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("guidItem", ctypes.c_byte * 16)]


def main():
    events = queue.Queue()
    tray = SystemTray(events)
    tray.start()
    try:
        assert tray.ready.wait(5), "Tray did not become ready: " + str(tray.error)
        assert tray.available
        shell = ctypes.WinDLL("shell32")
        shell.Shell_NotifyIconGetRect.argtypes = [ctypes.POINTER(NotifyIconIdentifier), ctypes.POINTER(wintypes.RECT)]
        shell.Shell_NotifyIconGetRect.restype = ctypes.c_long
        identifier = NotifyIconIdentifier()
        identifier.cbSize = ctypes.sizeof(identifier)
        identifier.hWnd = tray.icon._hwnd
        # pystray 0.19.5 leaves the uID field at zero (its constructor uses hID).
        # Each icon has its own owner HWND, so this is a valid unique pair.
        identifier.uID = 0
        rect = wintypes.RECT()
        result = -1
        deadline = time.monotonic() + 5
        while result < 0 and time.monotonic() < deadline:
            result = shell.Shell_NotifyIconGetRect(ctypes.byref(identifier), ctypes.byref(rect))
            if result < 0:
                time.sleep(0.1)
        print("Shell tray rectangle:", result, rect.left, rect.top, rect.right, rect.bottom, flush=True)
        assert result >= 0, "Shell did not register the tray icon: HRESULT %s" % result
        assert rect.right > rect.left and rect.bottom > rect.top
        tray.update({"gear": 2, "games": [], "paused": False})
        assert "2 档" in tray.icon.title
        tray.update({"paused": True})
        assert "已暂停" in tray.icon.title
        tray.icon()
        received = []
        while not events.empty():
            received.append(events.get_nowait())
        assert {"tray_action": "show"} in received
        items = list(tray.icon.menu)
        assert items[1].text == "恢复自动调档"
        items[1](tray.icon)
        assert events.get(timeout=1) == {"tray_action": "toggle"}
        items[-1](tray.icon)
        assert events.get(timeout=1) == {"tray_action": "quit"}
        print("PASS: Shell registered tray icon; open, pause/resume and exit dispatched; tooltip updated")
    finally:
        tray.stop()
        assert not tray.thread.is_alive(), "Tray message loop did not stop"


if __name__ == "__main__":
    main()
