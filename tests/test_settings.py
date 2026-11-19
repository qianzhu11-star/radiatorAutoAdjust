import queue
import unittest
from unittest.mock import MagicMock, patch

from radiator.device import Cooler
from radiator.protocol import build_report
from radiator.runtime import Monitor


def report(mode_byte):
    return build_report(0xEF, bytes((0x6A, mode_byte, 5, 0x8C, 10, 0x8C, 10, 1, 0)))


class DeviceSettingsTests(unittest.TestCase):
    def test_power_on_bit_is_independent_of_smart_mode(self):
        for mode, code in (("off", 0), ("immediate", 1), ("delayed", 2)):
            for power_on in (False, True):
                with self.subTest(mode=mode, power_on=power_on):
                    cooler = Cooler()
                    cooler._receive(report((code << 2) | (2 if power_on else 0)))
                    self.assertEqual(cooler.status["smart_start_stop"], mode)
                    self.assertEqual(cooler.status["power_on_start"], power_on)
        cooler._receive(report(14))
        self.assertIsNone(cooler.status["smart_start_stop"])

    def test_read_ignores_old_queued_settings_and_waits_for_new_status(self):
        cooler = Cooler()
        cooler.handle = MagicMock()
        cooler.handle.read.side_effect = [report(2), [], report(6)]
        self.assertEqual(cooler.read_settings(), {"smart_start_stop": "immediate", "power_on_start": True})

    def test_unknown_mode_and_missing_status_are_errors(self):
        cooler = Cooler()
        cooler.handle = MagicMock()
        cooler.handle.read.side_effect = [[], report(14)]
        with self.assertRaises(OSError):
            cooler.read_settings()
        cooler.handle.read.side_effect = None
        cooler.handle.read.return_value = []
        with self.assertRaises(OSError):
            cooler.read_settings(timeout=0.001)

    def test_unchanged_settings_do_not_write_flash(self):
        cooler = Cooler()
        target = {"smart_start_stop": "immediate", "power_on_start": True}
        with patch.object(cooler, "read_settings", return_value=target), \
                patch.object(cooler, "_write_setting") as write:
            self.assertEqual(cooler.apply_settings("immediate", True), target)
            write.assert_not_called()

    def test_both_settings_written_and_readback_required(self):
        cooler = Cooler()
        before = {"smart_start_stop": "off", "power_on_start": False}
        target = {"smart_start_stop": "delayed", "power_on_start": True}
        with patch.object(cooler, "read_settings", side_effect=[before, target]), \
                patch.object(cooler, "_write_setting") as write:
            self.assertEqual(cooler.apply_settings("delayed", True), target)
            self.assertEqual([call.args for call in write.call_args_list], [(0x0D, 2), (0x0C, 1)])
        with patch.object(cooler, "read_settings", side_effect=[before, before]), \
                patch.object(cooler, "_write_setting"):
            with self.assertRaises(OSError):
                cooler.apply_settings("delayed", True)

    def test_invalid_values_never_send_commands(self):
        cooler = Cooler()
        with patch.object(cooler, "command") as command:
            for mode, enabled in (("bad", True), ("off", 1)):
                with self.assertRaises(ValueError):
                    cooler.apply_settings(mode, enabled)
            command.assert_not_called()

    def test_worker_reports_confirmed_settings_without_resuming_paused_control(self):
        monitor = Monitor({"games": []})
        monitor.enabled = False
        cooler = MagicMock()
        target = {"smart_start_stop": "immediate", "power_on_start": True}
        cooler.apply_settings.return_value = target
        monitor.device_settings_request(cooler, dict(operation="apply", **target))
        self.assertFalse(monitor.enabled)
        event = monitor.events.get_nowait()
        self.assertEqual(event["device_settings"], target)
        self.assertEqual(event["settings_operation"], "apply")
        cooler.apply_settings.side_effect = OSError("readback failed")
        monitor.device_settings_request(cooler, dict(operation="apply", **target))
        event = monitor.events.get_nowait()
        self.assertIn("readback failed", event["settings_error"])
        self.assertNotIn("device_settings", event)


if __name__ == "__main__":
    unittest.main()
