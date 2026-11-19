"""Windows notification-area icon; callbacks only enqueue actions for Tk."""
from pathlib import Path
import threading


def create_icon():
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 61, 61), radius=15, fill="#087da7")
    draw.ellipse((10, 10, 53, 53), outline="#9ae9fb", width=3)
    for angle in (0, 120, 240):
        blade = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(blade).ellipse((29, 13, 42, 34), fill="white")
        image.alpha_composite(blade.rotate(angle, center=(32, 32)))
    draw = ImageDraw.Draw(image)
    draw.ellipse((27, 27, 37, 37), fill="#9ae9fb", outline="#087da7", width=2)
    return image


class SystemTray:
    def __init__(self, events):
        import pystray
        self.events = events
        self.ready = threading.Event()
        self.error = None
        self.paused = False
        self.last_state = None
        self.thread = None
        self.stopping = False
        icon_file = Path(__file__).resolve().parent.parent / "assets/fan.ico"
        if icon_file.is_file():
            from PIL import Image
            with Image.open(str(icon_file)) as source:
                icon_image = source.convert("RGBA")
        else:
            icon_image = create_icon()
        self.icon = pystray.Icon("BS2ProGameGear", icon_image, "BS2 Pro 自动调档 · 正在连接",
            menu=pystray.Menu(
                pystray.MenuItem("打开控制窗口", lambda icon, item: self.send("show"), default=True),
                pystray.MenuItem(lambda item: "恢复自动调档" if self.paused else "暂停自动调档",
                                 lambda icon, item: self.send("toggle")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出程序", lambda icon, item: self.send("quit"))))

    @property
    def available(self):
        return self.ready.is_set() and self.thread is not None and self.thread.is_alive() and not self.stopping

    def send(self, action):
        self.events.put({"tray_action": action})

    def start(self):
        self.thread = threading.Thread(target=self._run, name="BS2Pro-Tray", daemon=True)
        self.thread.start()

    def _setup(self, icon):
        try:
            if self.stopping:
                icon.stop()
                return
            icon.visible = True
            self.ready.set()
            self.events.put({"tray_ready": True})
        except Exception as exc:
            self.error = str(exc)
            self.events.put({"tray_error": self.error})
            icon.stop()

    def _run(self):
        try:
            self.icon.run(setup=self._setup)
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.ready.clear()
            if not self.stopping:
                self.events.put({"tray_error": self.error or "系统托盘图标已停止"})

    def update(self, state):
        paused = bool(state.get("paused"))
        key = (state.get("gear"), paused, bool(state.get("error")), bool(state.get("games")))
        if key == self.last_state or not self.available:
            return
        self.last_state = key
        self.paused = paused
        if state.get("error"):
            label = "连接异常，请打开窗口查看"
        elif paused:
            label = "自动调档已暂停"
        else:
            gear = "%s 档" % state["gear"] if state.get("gear") else "正在连接"
            label = gear + (" · 游戏中" if state.get("games") else " · 空闲")
        self.icon.title = "BS2 Pro 自动调档 · " + label
        self.icon.update_menu()

    def stop(self):
        self.stopping = True
        self.icon.stop()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
