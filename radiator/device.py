import time

from .protocol import build_report, parse_report


class Cooler:
    """Only opens VID 37D7 / PID 1002. Never writes RPM presets or firmware."""

    def __init__(self):
        self.handle = None
        self.info = None
        self.status = {}
        self.status_sequence = 0
        self.last_settings_write = 0

    @staticmethod
    def devices():
        import hid
        return hid.enumerate(0x37D7, 0x1002)

    def connect(self):
        import hid
        self.close()
        errors = []
        for info in self.devices():
            handle = hid.device()
            try:
                handle.open_path(info["path"])
                self.handle, self.info = handle, info
                self.query_gear()
                return
            except (OSError, RuntimeError) as exc:
                errors.append(str(exc))
                handle.close()
                self.handle = None
        raise OSError("BS2 Pro 未连接，请确认蓝牙配对和供电" +
                      ("：" + "; ".join(errors) if errors else ""))

    def command(self, command, payload=b"", accepted=None):
        if self.handle is None:
            raise OSError("设备未连接")
        # Drain already queued notifications before sending a fresh request.
        for _ in range(64):
            data = self.handle.read(64, 1)
            if not data:
                break
            self._receive(data)
        report = build_report(command, payload)
        if self.handle.write(report) < len(report):
            raise OSError("设备指令写入不完整")
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            parsed = self._receive(self.handle.read(64, 100))
            if parsed is None:
                continue
            cmd, data = parsed
            if cmd != command:
                continue
            if accepted is not None and (not data or data[0] not in accepted):
                raise OSError("设备拒绝指令 0x%02X：%s" % (command, data.hex()))
            return data
        raise OSError("设备响应超时 (0x%02X)，请检查蓝牙连接" % command)

    def _receive(self, data):
        parsed = parse_report(data)
        if parsed and parsed[0] == 0xEF and len(parsed[1]) >= 7:
            payload = parsed[1]
            self.status = {
                "gear": {8: 1, 10: 2, 12: 3, 14: 4}.get(payload[0] & 15),
                "realtime": bool(payload[1] & 1),
                "power_on_start": bool(payload[1] & 2),
                # Power-on start is bit 1; smart start/stop is bits 2..3.
                "smart_start_stop": {0: "off", 1: "immediate", 2: "delayed"}.get((payload[1] >> 2) & 3),
                "rpm": int.from_bytes(payload[3:5], "little"),
                "target_rpm": int.from_bytes(payload[5:7], "little"),
            }
            self.status_sequence += 1
        return parsed

    def read_settings(self, timeout=2.5):
        if self.handle is None:
            raise OSError("设备未连接")
        for _ in range(64):
            data = self.handle.read(64, 1)
            if not data:
                break
            self._receive(data)
        sequence = self.status_sequence
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._receive(self.handle.read(64, 100))
            if self.status_sequence > sequence:
                mode = self.status.get("smart_start_stop")
                if mode is None:
                    raise OSError("设备返回了未知的智能启停模式，未修改设置")
                return {"smart_start_stop": mode, "power_on_start": self.status["power_on_start"]}
        raise OSError("读取设备启停设置超时，请检查蓝牙连接")

    def _write_setting(self, command, value):
        # These settings persist in the cooler's flash. Space writes and skip
        # unchanged values in apply_settings rather than replaying on each tick.
        delay = 0.25 - (time.monotonic() - self.last_settings_write)
        if delay > 0:
            time.sleep(delay)
        try:
            self.command(command, bytes((value,)), accepted=(1,))
        finally:
            self.last_settings_write = time.monotonic()

    def apply_settings(self, smart_start_stop, power_on_start):
        modes = {"off": 0, "immediate": 1, "delayed": 2}
        if smart_start_stop not in modes or not isinstance(power_on_start, bool):
            raise ValueError("无效的设备启停设置")
        before = self.read_settings()
        target = {"smart_start_stop": smart_start_stop, "power_on_start": power_on_start}
        if before == target:
            return before
        if before["smart_start_stop"] != smart_start_stop:
            self._write_setting(0x0D, modes[smart_start_stop])
        if before["power_on_start"] != power_on_start:
            self._write_setting(0x0C, 1 if power_on_start else 2)
        actual = self.read_settings()
        if actual != target:
            raise OSError("设备启停设置读回不一致，请重新读取；部分设置可能已生效")
        return actual

    def query_gear(self):
        data = self.command(0x25)
        if not data or data[0] not in (1, 2, 3, 4, 5):
            raise OSError("无法识别设备档位响应")
        return data[0]  # 1..4 fixed gears, 5 realtime mode (BS2 Pro).

    def set_gear(self, gear):
        if gear not in (2, 3):
            raise ValueError("本工具只允许切换 2、3 档")
        if self.query_gear() == 5:
            self.command(0x24, accepted=(1, 2))
        self.command(0x08, bytes((gear,)), accepted=(1,))
        actual = self.query_gear()
        if actual != gear:
            raise OSError("换档未确认：目标 %d 档，设备返回 %d；请退出飞智空间站的智能调速" % (gear, actual))
        return actual

    def close(self):
        if self.handle is not None:
            self.handle.close()
        self.handle = None
        self.status = {}
