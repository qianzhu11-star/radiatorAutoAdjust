"""Opt-in Tk layout check (no hardware calls): python tests/gui_check.py."""
import copy
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from radiator.games import KNOWN
from radiator.ui import Application


def main():
    with tempfile.TemporaryDirectory() as folder, patch("radiator.ui.Monitor") as monitor, \
            patch("radiator.ui.SystemTray") as tray:
        monitor.return_value.enabled = True
        tray.return_value.available = True
        root = tk.Tk()
        root.withdraw()
        try:
            app = Application(root, {"games": copy.deepcopy(KNOWN), "extra_roots": [],
                                     "exit_delay_seconds": 10}, Path(folder) / "config.json")
            root.update_idletasks()
            root.deiconify()
            root.update_idletasks()
            assert app.tree.get_children() == ("0", "1")
            assert app.tree.item("0", "values")[1] == "CS2 / CSGO"
            assert app.tree.item("1", "values")[1] == "三角洲行动"
            assert app.scan_button.cget("text") == "自动搜索游戏"
            # Tk's Windows getter does not return the custom ICO filename.
            # Ask the actual top-level HWND for its icon instead.
            user32 = ctypes.WinDLL("user32")
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = wintypes.LPARAM
            hwnd = user32.GetAncestor(root.winfo_id(), 2)
            assert user32.SendMessageW(hwnd, 0x7F, 1, 0), "The native window must expose its large icon"
            assert user32.SendMessageW(hwnd, 0x7F, 0, 0), "The native window must expose its small icon"
            app.events.put({"message": "无游戏运行 → 2 档", "gear": 2, "games": []})
            app.poll()
            assert app.status.get() == "无游戏运行 → 2 档"
            assert "2 档" in app.playing.get()
            confirmed = {"smart_start_stop": "immediate", "power_on_start": True}
            app.events.put({"device_settings": confirmed, "settings_operation": "sync"})
            app.poll()
            assert app.smart_mode.get() == "即时（推荐）"
            assert app.power_on_start.get()
            app.smart_mode.set("延时约 1 分钟")
            app.mark_settings_dirty()
            app.settings_apply_button.invoke()
            app.monitor.settings_requests.put.assert_called_with({"operation": "apply",
                "smart_start_stop": "delayed", "power_on_start": True})
            assert app.config["device_settings"]["smart_start_stop"] == "immediate", "Draft must not be saved before confirmation"
            app.events.put({"settings_error": "readback failed", "settings_operation": "apply"})
            app.poll()
            assert "未确认生效" in app.device_status.get()
            assert app.config["device_settings"]["smart_start_stop"] == "immediate"
            app.events.put({"device_settings": {"smart_start_stop": "delayed", "power_on_start": True},
                            "settings_operation": "apply"})
            app.poll()
            assert app.config["device_settings"]["smart_start_stop"] == "delayed"
            app.settings_read_button.invoke()
            app.monitor.settings_requests.put.assert_called_with({"operation": "read"})
            app.hide_to_tray()
            root.update_idletasks()
            assert root.state() == "withdrawn"
            app.events.put({"tray_action": "show"})
            app.poll()
            root.update_idletasks()
            assert root.state() == "normal"
            app.events.put({"tray_action": "toggle"})
            app.poll()
            assert not app.monitor.enabled
            app.events.put({"tray_action": "toggle"})
            app.poll()
            assert app.monitor.enabled
            app.hide_to_tray()
            app.events.put({"tray_error": "test failure"})
            app.poll()
            root.update_idletasks()
            assert root.state() == "normal", "A failed tray must restore the window"
            assert "test failure" in app.tray_status.get()
            target = Path(folder) / "temporary-test.exe"
            target.write_bytes(b"MZ")
            test_game = {"id": "manual:temporary-test", "name": "Temporary test", "source": "手动添加",
                         "executables": [str(target)], "process_names": [], "enabled": False}
            app.config["games"].append(test_game)
            app.refresh_games()
            app.tree.selection_set("2")
            app.delete_button.invoke()
            assert len(app.config["games"]) == 2
            assert target.exists(), "Deleting a rule must not remove the program file"
            saved = __import__("json").loads((Path(folder) / "config.json").read_text(encoding="utf-8"))
            assert saved["excluded_games"][0]["id"] == test_game["id"]
            # A scan that was already running before deletion cannot add it back.
            app.events.put({"discovered": copy.deepcopy(KNOWN) + [dict(test_game, id="folder:alias")]})
            app.poll()
            assert len(app.config["games"]) == 2
            app.restore_excluded()
            assert any(game["id"] == test_game["id"] for game in app.config["games"])
            assert app.config["excluded_games"] == []
            assert target.exists()
            # Ensure the main frame and controls fit within the client area.
            clipped = []
            def inspect(widget):
                for child in widget.winfo_children():
                    if child.winfo_manager() and child.winfo_ismapped():
                        if child.winfo_x() + child.winfo_width() > widget.winfo_width() + 2:
                            clipped.append(str(child))
                        if child.winfo_y() + child.winfo_height() > widget.winfo_height() + 2:
                            clipped.append(str(child))
                        inspect(child)
            inspect(root)
            assert not clipped, "Controls clipped: " + str(clipped)
            print("PASS: game rows, Chinese text, device state, delete/persist/rescan and control bounds; size=%dx%d" %
                  (root.winfo_width(), root.winfo_height()))
        finally:
            root.destroy()


if __name__ == "__main__":
    main()
