"""Run with pythonw.exe main.py for the desktop tool, or --help for CLI."""
import argparse
import ctypes
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".deps"))


def main():
    parser = argparse.ArgumentParser(description="BS2 Pro：游戏运行 3 档，退出回 2 档")
    parser.add_argument("--scan", action="store_true", help="搜索游戏并保存配置")
    parser.add_argument("--devices", action="store_true", help="只枚举 BS2 Pro")
    parser.add_argument("--status", action="store_true", help="读取当前设备档位")
    parser.add_argument("--gear", type=int, choices=(2, 3), help="设置档位并读取确认")
    parser.add_argument("--watch", action="store_true", help="命令行后台监测")
    parser.add_argument("--minimized", action="store_true", help="最小化启动")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    args = parser.parse_args()
    from radiator.device import Cooler
    from radiator.runtime import Monitor, atomic_json, load_config
    import json
    if args.devices:
        print(json.dumps(Cooler.devices(), ensure_ascii=False, default=lambda x: x.decode(errors="replace"), indent=2))
        return
    # One controller owns the hardware; CLI diagnostics also honor the mutex.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, "Local\\BS2ProGameGearController")
    error = ctypes.get_last_error()
    if not mutex:
        raise ctypes.WinError(error)
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    if error == 183:
        kernel.CloseHandle(mutex)
        if not any((args.status, args.gear, args.scan, args.watch)):
            from radiator.instance import request_show
            import time
            for attempt in range(10):
                if request_show():
                    return
                time.sleep(0.1)
            ctypes.windll.user32.MessageBoxW(None, "程序正在启动，或正在命令行运行；稍后可再次双击快捷方式打开。", "BS2 Pro", 0)
            return
        raise RuntimeError("程序已在运行，请先退出已有实例")
    try:
        if args.status or args.gear:
            cooler = Cooler()
            try:
                cooler.connect()
                gear = cooler.set_gear(args.gear) if args.gear else cooler.query_gear()
                print(json.dumps({"gear": gear, "confirmed": True}))
            finally:
                cooler.close()
            return
        config = load_config(args.config)
        if args.scan:
            from radiator.games import discover, merge_games
            config["games"] = merge_games(config["games"], discover(config["extra_roots"]),
                                           config.get("excluded_games", []))
            atomic_json(args.config, config)
            print(json.dumps(config, ensure_ascii=False, indent=2))
        elif args.watch:
            monitor = Monitor(config, state_path=args.config.with_name(args.config.stem + ".status.json"))
            monitor.start()
            try:
                while monitor.is_alive():
                    monitor.join(1)
            except KeyboardInterrupt:
                monitor.stopping.set()
                monitor.join(8)
        else:
            from radiator.instance import ShowRequest
            from radiator.ui import run_gui
            show_request = ShowRequest()
            try:
                run_gui(config, args.config, args.minimized, show_request)
            finally:
                show_request.close()
    finally:
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        error = traceback.format_exc()
        (ROOT / "error.log").write_text(error, encoding="utf-8")
        if Path(sys.executable).name.lower() == "pythonw.exe":
            ctypes.windll.user32.MessageBoxW(None, error, "BS2 Pro 启动失败", 0x10)
        else:
            print(error, file=sys.stderr)
        sys.exit(1)
