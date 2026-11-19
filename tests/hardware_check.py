"""Opt-in integration check; drives the real cooler, then returns it to idle.

Run before starting the GUI: python tests/hardware_check.py
Uses a harmless ping process as a stand-in for a game; no games are launched.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / ".deps")]
from radiator.device import Cooler
from radiator.runtime import Monitor


def wait_state(events, gear, active, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = events.get(timeout=1)
        except queue.Empty:
            continue
        print(json.dumps(state, ensure_ascii=True), flush=True)
        if state.get("gear") == gear and bool(state.get("games")) == active:
            return state
    raise AssertionError("Timed out waiting for gear=%s active=%s" % (gear, active))


def main():
    with tempfile.TemporaryDirectory() as folder:
        events = queue.Queue()
        config = {"games": [{"id": "test", "name": "integration-ping",
                              "process_names": ["ping.exe"], "enabled": True}],
                  "exit_delay_seconds": 3}
        monitor = Monitor(config, events, Path(folder) / "status.json")
        process = None
        monitor.start()
        try:
            wait_state(events, 2, False)
            process = subprocess.Popen([os.path.join(os.environ["SYSTEMROOT"], "System32", "PING.EXE"),
                                        "-t", "127.0.0.1"], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            wait_state(events, 3, True)
            process.terminate()
            process.wait(timeout=5)
            process = None
            wait_state(events, 2, False)
        finally:
            if process is not None:
                process.terminate()
                process.wait(timeout=5)
            monitor.stopping.set()
            monitor.join(10)
            assert not monitor.is_alive(), "Monitor failed to stop"
        cooler = Cooler()
        try:
            cooler.connect()
            assert cooler.query_gear() == 2
        finally:
            cooler.close()
        print("PASS: idle 2 -> process running 3 -> process exited 2; final readback 2", flush=True)


if __name__ == "__main__":
    main()
