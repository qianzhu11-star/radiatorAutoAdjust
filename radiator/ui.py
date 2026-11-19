import ctypes
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import winreg

from .games import allow_game, delete_games, discover, merge_games
from .runtime import ROOT, Monitor, atomic_json
from .tray import SystemTray

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "BS2ProGameGear"
SMART_LABELS = {"off": "关闭", "immediate": "即时（推荐）", "delayed": "延时约 1 分钟"}


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return bool(winreg.QueryValueEx(key, RUN_NAME)[0])
    except OSError:
        return False


def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            executable = Path(sys.executable).with_name("pythonw.exe")
            if not executable.exists():
                executable = Path(sys.executable)
            command = '"%s" "%s" --minimized' % (executable, ROOT / "main.py")
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


class Application:
    def __init__(self, root, config, config_path, minimized=False, show_request=None):
        self.root, self.config, self.config_path = root, config, config_path
        self.events = queue.Queue()
        self.monitor = Monitor(config, self.events)
        self.closing = False
        self.scanning = False
        self.tray = None
        self.show_request = show_request
        self.pending_hide = bool(minimized)
        self.settings_loaded = False
        self.settings_dirty = False
        root.title("BS2 Pro 游戏自动调档")
        root.geometry("900x760")
        root.minsize(820, 700)
        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        icon_file = ROOT / "assets/fan.ico"
        if icon_file.is_file():
            root.iconbitmap(str(icon_file))
        style = ttk.Style()
        style.theme_use("vista")
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=5)
        content = ttk.Frame(root, padding=20)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="游戏开启 3 档 · 游戏退出 2 档", font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
        ttk.Label(content, text="每 2 秒检测游戏进程；最后一个游戏退出 10 秒后降档。切到桌面保持 3 档。").pack(anchor="w", pady=(6, 14))
        self.status = tk.StringVar(value="正在连接 BS2 Pro…")
        ttk.Label(content, textvariable=self.status, wraplength=760, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.playing = tk.StringVar(value="")
        ttk.Label(content, textvariable=self.playing).pack(anchor="w", pady=(3, 12))
        device_controls = ttk.LabelFrame(content, text="散热器自身的启停设置", padding=10)
        device_controls.pack(fill="x", pady=(0, 12))
        device_row = ttk.Frame(device_controls)
        device_row.pack(fill="x")
        ttk.Label(device_row, text="智能启停：").pack(side="left")
        previous_settings = config.get("device_settings", {})
        self.smart_mode = tk.StringVar(value=SMART_LABELS.get(previous_settings.get("smart_start_stop"), "即时（推荐）"))
        self.smart_select = ttk.Combobox(device_row, textvariable=self.smart_mode, state="readonly",
                                         values=list(SMART_LABELS.values()), width=20)
        self.smart_select.pack(side="left")
        self.smart_select.bind("<<ComboboxSelected>>", lambda event: self.mark_settings_dirty())
        self.power_on_start = tk.BooleanVar(value=bool(previous_settings.get("power_on_start", True)))
        self.power_start_check = ttk.Checkbutton(device_row, text="通电自启", variable=self.power_on_start,
                                                 command=self.mark_settings_dirty)
        self.power_start_check.pack(side="left", padx=10)
        self.settings_read_button = ttk.Button(device_row, text="读取设备设置", command=self.read_device_settings)
        self.settings_read_button.pack(side="left", padx=(0, 6))
        self.settings_apply_button = ttk.Button(device_row, text="应用到散热器", command=self.apply_device_settings)
        self.settings_apply_button.pack(side="left")
        self.settings_apply_button.state(["disabled"])
        self.device_status = tk.StringVar(value="正在从散热器读取当前启停设置…")
        ttk.Label(device_controls, textvariable=self.device_status, wraplength=820).pack(anchor="w", pady=(6, 2))
        ttk.Label(device_controls, text="即时：蓝牙连接即开、断开即停；延时：蓝牙断开约 1 分钟后停。通电自启指重新接通电源。",
                  foreground="#555555", wraplength=820).pack(anchor="w")
        toolbar = ttk.Frame(content)
        toolbar.pack(fill="x", pady=(0, 8))
        self.scan_button = ttk.Button(toolbar, text="自动搜索游戏", command=self.scan)
        self.scan_button.pack(side="left")
        ttk.Button(toolbar, text="添加游戏 .exe", command=self.add_game).pack(side="left", padx=6)
        ttk.Button(toolbar, text="添加搜索目录", command=self.add_root).pack(side="left")
        management = ttk.Frame(content)
        management.pack(fill="x", pady=(0, 8))
        ttk.Button(management, text="启用 / 停用所选", command=self.toggle_game).pack(side="left")
        self.delete_button = ttk.Button(management, text="删除所选检测程序", command=self.delete_selected)
        self.delete_button.pack(side="left", padx=6)
        ttk.Button(management, text="恢复已排除项", command=self.restore_excluded).pack(side="left")
        self.tree = ttk.Treeview(content, columns=("enabled", "name", "source", "exe"), show="headings", height=8)
        for key, title, width in (("enabled", "检测", 55), ("name", "游戏", 160),
                                  ("source", "来源", 90), ("exe", "游戏进程", 420)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=40)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda event: self.toggle_game())
        self.tree.bind("<Delete>", lambda event: self.delete_selected())
        self.menu = tk.Menu(root, tearoff=False)
        self.menu.add_command(label="启用 / 停用", command=self.toggle_game)
        self.menu.add_command(label="删除检测程序", command=self.delete_selected)
        self.tree.bind("<Button-3>", self.show_menu)
        controls = ttk.Frame(content)
        controls.pack(fill="x", pady=(14, 8))
        self.pause_button = ttk.Button(controls, text="暂停自动调档", command=self.toggle_monitor)
        self.pause_button.pack(side="left")
        ttk.Button(controls, text="测试 3 档", command=lambda: self.test_gear(3)).pack(side="left", padx=6)
        ttk.Button(controls, text="测试 2 档", command=lambda: self.test_gear(2)).pack(side="left")
        ttk.Button(controls, text="退出程序", command=self.quit).pack(side="right")
        self.startup = tk.BooleanVar(value=startup_enabled())
        ttk.Checkbutton(controls, text="登录 Windows 后自动运行", variable=self.startup,
                        command=self.toggle_startup).pack(side="right", padx=12)
        self.scan_status = tk.StringVar(value="")
        ttk.Label(content, textvariable=self.scan_status).pack(anchor="w")
        self.tray_status = tk.StringVar(value="点击 × 收到右下角蓝色风扇托盘图标；单击图标或双击桌面快捷方式可打开。")
        ttk.Label(content, textvariable=self.tray_status, wraplength=840,
                  foreground="#555555").pack(anchor="w", pady=(6, 0))
        self.refresh_games()
        try:
            self.tray = SystemTray(self.events)
            self.tray.start()
        except Exception as exc:
            self.tray = None
            self.tray_status.set("托盘启动失败，将保留任务栏窗口：" + str(exc))
        self.monitor.start()
        root.after(200, self.poll)
        root.after(400, self.scan)
        if minimized:
            root.after(100, self.hide_to_tray)

    def hide_to_tray(self):
        if self.closing:
            return
        self.pending_hide = True
        if self.tray is not None and self.tray.available:
            self.root.withdraw()
        else:
            # Never hide the only way to reopen the app before the tray is ready.
            self.root.iconify()

    def show_window(self):
        self.pending_hide = False
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def save(self):
        try:
            atomic_json(self.config_path, self.config)
            self.monitor.update(self.config)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))

    def mark_settings_dirty(self):
        self.settings_dirty = True
        self.device_status.set("设置已修改，点击“应用到散热器”后生效。")

    def _settings_busy(self):
        self.smart_select.state(["disabled"])
        self.power_start_check.state(["disabled"])
        self.settings_read_button.state(["disabled"])
        self.settings_apply_button.state(["disabled"])

    def read_device_settings(self):
        self._settings_busy()
        self.device_status.set("正在读取设备启停设置…")
        self.monitor.settings_requests.put({"operation": "read"})

    def apply_device_settings(self):
        mode = next((key for key, label in SMART_LABELS.items() if label == self.smart_mode.get()), None)
        if mode is None:
            self.device_status.set("请选择有效的智能启停模式。")
            return
        self._settings_busy()
        self.device_status.set("正在写入散热器并等待设备状态读回确认…")
        self.monitor.settings_requests.put({"operation": "apply", "smart_start_stop": mode,
                                           "power_on_start": bool(self.power_on_start.get())})

    def settings_result(self, event):
        self.smart_select.state(["!disabled", "readonly"])
        self.power_start_check.state(["!disabled"])
        self.settings_read_button.state(["!disabled"])
        if "settings_error" in event:
            self.device_status.set("未确认生效：" + event["settings_error"] + "；可重新读取设备设置。")
            if self.settings_loaded:
                self.settings_apply_button.state(["!disabled"])
            return
        settings = event["device_settings"]
        operation = event.get("settings_operation", "read")
        pending_draft = self.settings_dirty and operation == "sync"
        if not self.settings_dirty or operation != "sync":
            self.smart_mode.set(SMART_LABELS[settings["smart_start_stop"]])
            self.power_on_start.set(settings["power_on_start"])
            self.settings_dirty = False
        self.settings_loaded = True
        self.settings_apply_button.state(["!disabled"])
        self.config["device_settings"] = dict(settings)
        self.save()
        self.device_status.set("设备读回已确认：智能启停 %s；通电自启 %s。%s" %
            (SMART_LABELS[settings["smart_start_stop"]], "开启" if settings["power_on_start"] else "关闭",
             "有未应用的修改。" if pending_draft else "设置已保存到散热器。" if operation == "apply" else ""))

    def refresh_games(self):
        self.tree.delete(*self.tree.get_children())
        for index, game in enumerate(self.config["games"]):
            exes = sorted(set(game.get("process_names", []) + [Path(x).name for x in game.get("executables", [])]))
            self.tree.insert("", "end", iid=str(index), values=("开启" if game.get("enabled", True) else "停用",
                             game["name"], game.get("source", "手动"), ", ".join(exes) or "未找到主程序，请手动添加"))

    def scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.scan_button.state(["disabled"])
        self.scan_status.set("正在搜索平台安装记录、快捷方式和磁盘游戏目录…")
        roots = list(self.config.get("extra_roots", []))
        def work():
            try:
                found = discover(roots, progress=lambda message: self.events.put({"scan_progress": message}))
                self.events.put({"discovered": found})
            except Exception as exc:
                self.events.put({"scan_error": str(exc)})
        threading.Thread(target=work, daemon=True).start()

    def add_game(self):
        exe = filedialog.askopenfilename(title="选择实际游戏程序（避免启动器）", filetypes=[("游戏程序", "*.exe")])
        if not exe:
            return
        path = str(Path(exe))
        identifier = "manual:" + path.casefold()
        game = {"id": identifier, "name": Path(path).stem, "source": "手动添加",
                "executables": [path], "process_names": [], "enabled": True}
        allow_game(self.config, game)
        if not any(g["id"] == identifier for g in self.config["games"]):
            self.config["games"].append(game)
        self.save()
        self.refresh_games()

    def add_root(self):
        folder = filedialog.askdirectory(title="选择游戏安装目录")
        if folder:
            self.config["extra_roots"] = sorted(set(self.config["extra_roots"] + [folder]))
            self.save()
            self.scan()

    def toggle_game(self):
        for index in self.tree.selection():
            game = self.config["games"][int(index)]
            game["enabled"] = not game.get("enabled", True)
        self.save()
        self.refresh_games()

    def toggle_monitor(self):
        self.monitor.enabled = not self.monitor.enabled
        self.pause_button.config(text="暂停自动调档" if self.monitor.enabled else "恢复自动调档")
        if self.tray is not None:
            self.tray.update({"paused": not self.monitor.enabled})

    def delete_selected(self):
        selection = self.tree.selection()
        if not selection:
            self.scan_status.set("请先选择要删除的检测程序（可按 Ctrl 多选）。")
            return
        identifiers = [self.config["games"][int(index)]["id"] for index in selection]
        count = delete_games(self.config, identifiers)
        self.save()
        self.refresh_games()
        self.scan_status.set("已删除 %d 项检测规则；程序文件保留，重新搜索不会再加入。" % count)

    def restore_excluded(self):
        count = len(self.config.get("excluded_games", []))
        restorable = [game for game in self.config.get("excluded_games", []) if game.get("name")]
        self.config["games"] = merge_games(self.config["games"], restorable)
        self.config["excluded_games"] = []
        self.save()
        self.refresh_games()
        self.scan_status.set("已恢复 %d 项排除记录；手动检测程序也可重新加入。" % count)

    def show_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            try:
                self.menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.menu.grab_release()

    def test_gear(self, gear):
        self.monitor.commands.put(gear)
        self.pause_button.config(text="恢复自动调档")

    def toggle_startup(self):
        try:
            set_startup(self.startup.get())
        except OSError as exc:
            self.startup.set(startup_enabled())
            messagebox.showerror("设置自动运行失败", str(exc))

    def poll(self):
        if self.show_request is not None and self.show_request.requested():
            self.show_window()
        try:
            while True:
                event = self.events.get_nowait()
                if "tray_action" in event:
                    if event["tray_action"] == "show":
                        self.show_window()
                    elif event["tray_action"] == "toggle":
                        self.toggle_monitor()
                    elif event["tray_action"] == "quit":
                        self.quit()
                elif "tray_ready" in event:
                    if self.pending_hide:
                        self.hide_to_tray()
                elif "tray_error" in event:
                    self.show_window()
                    self.tray_status.set("系统托盘不可用，窗口已恢复：" + event["tray_error"])
                elif "device_settings" in event or "settings_error" in event:
                    self.settings_result(event)
                elif "scan_progress" in event:
                    self.scan_status.set(event["scan_progress"])
                elif "discovered" in event:
                    self.config["games"] = merge_games(self.config["games"], event["discovered"],
                                                       self.config.get("excluded_games", []))
                    self.save()
                    self.refresh_games()
                    self.scan_status.set(self.scan_status.get() + "；列表共 %d 项，排除 %d 项。" %
                                         (len(self.config["games"]), len(self.config.get("excluded_games", []))))
                    self.scanning = False
                    self.scan_button.state(["!disabled"])
                elif "scan_error" in event:
                    self.scan_status.set("搜索失败：" + event["scan_error"])
                    self.scanning = False
                    self.scan_button.state(["!disabled"])
                else:
                    self.status.set(event["message"])
                    self.playing.set("正在运行：" + ("、".join(event.get("games", [])) or "未检测到游戏") +
                                     ("    |    设备确认：%s 档" % event["gear"] if event.get("gear") else ""))
                    self.pause_button.config(text="恢复自动调档" if event.get("paused") else "暂停自动调档")
                    if self.tray is not None:
                        self.tray.update(event)
        except queue.Empty:
            pass
        if self.closing and not self.monitor.is_alive():
            if self.tray is not None:
                self.tray.stop()
            self.root.destroy()
        else:
            self.root.after(250, self.poll)

    def quit(self):
        if self.closing:
            return
        self.closing = True
        self.monitor.stopping.set()
        self.status.set("正在退出并确认最终档位…")


def run_gui(config, config_path, minimized=False, show_request=None):
    # Give this app its own taskbar group instead of the Python interpreter's.
    try:
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        shell.SetCurrentProcessExplicitAppUserModelID("RadiatorAutoAdjust.BS2Pro.GameGear")
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    app = Application(root, config, config_path, minimized, show_request)
    try:
        root.mainloop()
    finally:
        app.monitor.stopping.set()
        if app.tray is not None:
            app.tray.stop()
