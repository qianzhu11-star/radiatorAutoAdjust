import copy
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import queue
import threading
import time

from .device import Cooler
from .games import KNOWN
from .policy import GearPolicy, active_games
from .processes import snapshot

ROOT = Path(__file__).resolve().parent.parent


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load_config(path):
    path = Path(path)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    else:
        data = {"games": copy.deepcopy(KNOWN), "extra_roots": [], "exit_delay_seconds": 10}
    if not isinstance(data.get("games"), list):
        raise ValueError("config.json 中 games 必须是列表")
    data.setdefault("extra_roots", [])
    data.setdefault("excluded_games", [])
    delay = float(data.setdefault("exit_delay_seconds", 10))
    if not 0 <= delay <= 300:
        raise ValueError("exit_delay_seconds 必须在 0..300 秒之间")
    return data


def make_logger():
    logger = logging.getLogger("radiator")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(str(ROOT / "radiator.log"), maxBytes=1024 * 1024,
                                      backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


class Monitor(threading.Thread):
    def __init__(self, config, events=None, state_path=None):
        super().__init__(name="BS2Pro-Monitor", daemon=True)
        self.lock = threading.Lock()
        self.config = copy.deepcopy(config)
        self.events = events or queue.Queue()
        self.commands = queue.Queue()
        self.settings_requests = queue.Queue()
        self.stopping = threading.Event()
        self.enabled = True
        self.state_path = state_path or ROOT / "status.json"
        self.logger = make_logger()
        self.last_event = None

    def device_settings_request(self, cooler, request):
        operation = request.get("operation", "read")
        try:
            if cooler.handle is None:
                cooler.connect()
            if operation == "apply":
                settings = cooler.apply_settings(request["smart_start_stop"], request["power_on_start"])
            elif operation in ("read", "sync"):
                settings = cooler.read_settings()
            else:
                raise ValueError("未知的设备设置操作")
            self.events.put({"device_settings": settings, "settings_operation": operation})
            self.logger.info("设备启停设置已读回: %s", json.dumps(settings, ensure_ascii=False))
        except Exception as exc:
            self.events.put({"settings_error": str(exc), "settings_operation": operation})
            self.logger.error("设备启停设置失败: %s", exc)

    def update(self, config):
        with self.lock:
            self.config = copy.deepcopy(config)

    def publish(self, **state):
        state["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.events.put(state)
        try:
            atomic_json(self.state_path, state)
        except OSError as exc:
            self.logger.error("状态文件写入失败: %s", exc)
        key = (state.get("message"), state.get("gear"), tuple(state.get("games", [])))
        if key != self.last_event:
            self.logger.info("%s", json.dumps(state, ensure_ascii=False))
            self.last_event = key

    def run(self):
        cooler = Cooler()
        policy = GearPolicy()
        actual = None
        verify_at = 0
        retry_at = 0
        previous_enabled = True
        conflicts = 0
        try:
            while not self.stopping.is_set():
                with self.lock:
                    config = copy.deepcopy(self.config)
                try:
                    settings_request = self.settings_requests.get_nowait()
                except queue.Empty:
                    settings_request = None
                if settings_request is not None:
                    self.device_settings_request(cooler, settings_request)
                    verify_at = 0
                policy.exit_delay = float(config.get("exit_delay_seconds", 10))
                try:
                    processes = snapshot()
                    games = active_games(config["games"], processes)
                except Exception as exc:
                    self.publish(message="游戏进程读取失败，保留当前档位：" + str(exc),
                                 gear=actual, games=[], error=True)
                    self.stopping.wait(2)
                    continue
                now = time.monotonic()
                desired = policy.desired(bool(games), now)
                manual = None
                try:
                    manual = self.commands.get_nowait()
                except queue.Empty:
                    pass
                if manual is not None:
                    self.enabled = False
                    desired = manual
                    retry_at = 0
                if self.enabled and not previous_enabled:
                    verify_at = retry_at = 0
                    conflicts = 0
                previous_enabled = self.enabled
                if not self.enabled and manual is None:
                    cooler.close()
                    actual = None
                    self.publish(message="已暂停自动调档", gear=None, games=games, paused=True)
                    self.stopping.wait(1)
                    continue
                if now < retry_at:
                    self.stopping.wait(1)
                    continue
                try:
                    newly_connected = cooler.handle is None
                    if newly_connected:
                        cooler.connect()
                        actual = None
                        verify_at = 0
                        self.device_settings_request(cooler, {"operation": "sync"})
                    if now >= verify_at:
                        measured = cooler.query_gear()
                        if actual is not None and measured != actual:
                            conflicts += 1
                            if conflicts >= 3:
                                self.enabled = False
                                raise OSError("档位多次被其他程序改变，已暂停；请退出飞智空间站智能调速后恢复")
                        actual = measured
                        verify_at = now + 15
                    if actual != desired:
                        actual = cooler.set_gear(desired)
                        self.logger.info("设备确认切换至 %d 档", actual)
                    if manual is not None:
                        message = "手动测试已确认 %d 档；自动调档已暂停，点“恢复自动调档”继续" % actual
                    elif games:
                        message = "游戏运行中 → 3 档"
                    elif desired == 3:
                        message = "游戏已退出，等待 %.0f 秒后回 2 档" % policy.exit_delay
                    else:
                        message = "无游戏运行 → 2 档"
                    self.publish(message=message, gear=actual, games=games,
                                 target=desired, paused=not self.enabled,
                                 space_station_running=any(p["name"].casefold() == "flydigispacestation.exe" for p in processes))
                except Exception as exc:
                    cooler.close()
                    actual = None
                    retry_at = now + 5
                    self.publish(message=str(exc), gear=None, games=games,
                                 target=desired, error=True, paused=not self.enabled)
                self.stopping.wait(2)
        finally:
            # Leaving a running game at 3 is preferable to dropping cooling on exit.
            # Only restore idle after a fresh, successful process snapshot.
            try:
                with self.lock:
                    games = active_games(self.config["games"], snapshot())
                if not games:
                    if cooler.handle is None:
                        cooler.connect()
                    cooler.set_gear(2)
                if cooler.handle is None:
                    cooler.connect()
                final_gear = cooler.query_gear()
                self.publish(message="程序已退出", gear=final_gear, games=games, stopped=True)
            except Exception as exc:
                self.publish(message="程序已退出，未能确认最终档位：" + str(exc),
                             gear=None, games=[], stopped=True, error=True)
            finally:
                cooler.close()
