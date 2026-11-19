"""Opt-in settings read/write/reconnect check; restores the original flags.

Run before starting the GUI: python tests/settings_hardware_check.py
Does not disconnect Windows Bluetooth, cut power, or shut down the computer.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / ".deps")]
from radiator.device import Cooler


def main():
    cooler = Cooler()
    before = None
    try:
        cooler.connect()
        before = cooler.read_settings()
        print("BEFORE", json.dumps(before), flush=True)
        alternate = {"smart_start_stop": "delayed" if before["smart_start_stop"] != "delayed" else "immediate",
                     "power_on_start": not before["power_on_start"]}
        actual = cooler.apply_settings(**alternate)
        assert actual == alternate
        print("WRITE_CONFIRMED", json.dumps(actual), flush=True)
        cooler.close()
        cooler.connect()
        assert cooler.read_settings() == alternate
        print("RECONNECT_CONFIRMED", flush=True)
    finally:
        if before is not None:
            if cooler.handle is None:
                cooler.connect()
            restored = cooler.apply_settings(**before)
            assert restored == before
            print("RESTORED", json.dumps(restored), flush=True)
        cooler.close()
    print("PASS: settings ACK/readback, reconnect retention and original settings restored", flush=True)


if __name__ == "__main__":
    main()
