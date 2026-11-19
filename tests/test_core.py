import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radiator.device import Cooler
from radiator.games import KNOWN, candidate_exes, merge_games
from radiator.policy import GearPolicy, active_games
from radiator.protocol import build_report, parse_report


class ProtocolTests(unittest.TestCase):
    def test_known_gear_packets_and_checksum(self):
        self.assertEqual(build_report(0x08, b"\x03")[:7].hex(), "025aa50803030e")
        self.assertEqual(parse_report(build_report(0x08, b"\x02")), (8, b"\x02"))
        data = bytearray(build_report(8, b"\x02"))
        data[6] ^= 1
        self.assertIsNone(parse_report(data))
        self.assertIsNone(parse_report(b"\x5a\xa5\x25\x01\x26"))
        self.assertIsNone(parse_report(b"\x5a\xa5\x25\x05\x01"))

    def test_only_two_allowed_gears_and_readback_required(self):
        cooler = Cooler()
        with self.assertRaises(ValueError):
            cooler.set_gear(4)
        with patch.object(cooler, "query_gear", side_effect=[5, 3]), patch.object(cooler, "command") as command:
            self.assertEqual(cooler.set_gear(3), 3)
            self.assertEqual(command.call_args_list[0].args[0], 0x24)
            self.assertEqual(command.call_args_list[1].args[:2], (0x08, b"\x03"))
        with patch.object(cooler, "query_gear", side_effect=[2, 2]), patch.object(cooler, "command"):
            with self.assertRaises(OSError):
                cooler.set_gear(3)


class PolicyTests(unittest.TestCase):
    def test_multiple_games_and_disabled_rule(self):
        games = copy.deepcopy(KNOWN)
        processes = [{"name": "CS2.EXE"}, {"name": "DeltaForceClient-Win64-Shipping.exe"}]
        self.assertEqual(len(active_games(games, processes)), 2)
        self.assertEqual(len(active_games(games, processes[1:])), 1)
        games[1]["enabled"] = False
        self.assertFalse(active_games(games, processes[1:]))

    def test_exit_grace_and_relaunch(self):
        policy = GearPolicy(10)
        self.assertEqual(policy.desired(False, 0), 2)
        self.assertEqual(policy.desired(True, 1), 3)
        self.assertEqual(policy.desired(False, 10.99), 3)
        self.assertEqual(policy.desired(False, 11), 2)
        self.assertEqual(policy.desired(True, 12), 3)
        self.assertEqual(policy.desired(False, 15), 3)

    def test_paths_and_protected_process_fallback(self):
        games = [{"name": "Test", "executables": [r"D:\Games\Main.exe"]}]
        self.assertTrue(active_games(games, [{"name": "MAIN.EXE", "path": r"d:\games\main.exe"}]))
        self.assertFalse(active_games(games, [{"name": "Main.exe", "path": r"D:\Other\Main.exe"}]))
        self.assertTrue(active_games(games, [{"name": "Main.exe", "path": ""}]))


class DiscoveryTests(unittest.TestCase):
    def test_shipping_preferred_and_support_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for rel in ("Game.exe", "launcher.exe", "Game/Binaries/Win64/Game-Win64-Shipping.exe",
                        "Engine/Binaries/UnrealCEFSubProcess.exe", "tools/Tool.exe"):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"MZ")
            self.assertEqual(candidate_exes(root), [str(root / "Game/Binaries/Win64/Game-Win64-Shipping.exe")])

    def test_rescan_preserves_user_choices_and_manual_additions(self):
        old = [{"id": "steam:1", "enabled": False}, {"id": "manual:x", "enabled": True}]
        new = [{"id": "steam:1", "enabled": True}, {"id": "steam:2", "enabled": True}]
        merged = merge_games(old, new)
        self.assertFalse(merged[0]["enabled"])
        self.assertEqual([x["id"] for x in merged], ["steam:1", "steam:2", "manual:x"])


if __name__ == "__main__":
    unittest.main()
