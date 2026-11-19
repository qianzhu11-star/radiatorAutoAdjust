import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radiator.games import (KNOWN, allow_game, candidate_exes, delete_games, discover,
                            game_record, merge_games, other_platform_games, steam_games)
from radiator.policy import active_games
from radiator.runtime import atomic_json, load_config


def exe(root, relative):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ" + b"\0" * 16)
    return path


class ImprovedDiscoveryTests(unittest.TestCase):
    def test_unity_without_unreal_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Some Unity Game"
            expected = exe(root, "Play.exe")
            (root / "Play_Data").mkdir()
            exe(root, "Launcher.exe")
            exe(root, "Updater.exe")
            self.assertEqual(game_record(root, "test")["executables"], [str(expected)])

    def test_godot_and_legitimate_steamworld_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "SteamWorld"
            expected = exe(root, "SteamWorld.exe")
            expected.with_suffix(".pck").touch()
            self.assertEqual(game_record(root, "test")["executables"], [str(expected)])

    def test_deep_unreal_game_with_generic_startup_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "洛克王国：世界(2002304)"
            exe(root, "launcher/startup_runner.exe")
            exe(root, "Win64/NRC.exe")
            (root / "Win64/Engine").mkdir()
            expected = exe(root, "Win64/NRC/Binaries/Win64/NRC-Win64-Shipping.exe")
            exe(root, "Win64/NRC/Binaries/Win64/MSDKWebLauncher.exe")
            game = game_record(root, "test")
            self.assertEqual(game["name"], "洛克王国：世界")
            self.assertEqual(game["executables"], [str(expected)])
            self.assertFalse(active_games([game], [{"name": "startup_runner.exe", "path": str(root / "launcher/startup_runner.exe")}]))
            self.assertTrue(active_games([game], [{"name": expected.name, "path": str(expected)}]))

    def test_zero_byte_or_text_exe_not_a_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Bad.exe").write_text("not a program")
            (root / "Bad_Data").mkdir()
            self.assertIsNone(game_record(root, "test"))

    def test_install_record_pointing_to_launcher_uses_parent_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "TencentTitle"
            expected = exe(root, "Main.exe")
            (root / "Main_Data").mkdir()
            launcher = root / "launcher"
            exe(launcher, "LiveBox/es_broadcast_bridge.exe")
            exe(launcher, "common_apps/dependency_shared/dotnetfx35.exe")
            self.assertIsNone(game_record(launcher, "安装记录", trusted=True))
            with patch("radiator.games.shortcuts", return_value=[]), \
                    patch("radiator.games.fixed_drives", return_value=[]), \
                    patch("radiator.games.uninstall_entries", return_value=[("TencentTitle", launcher)]), \
                    patch("radiator.games.reg_value", return_value=""):
                found = discover()
            actual = [g for g in found if g["id"].startswith("folder:")]
            self.assertEqual(len(actual), 1)
            self.assertEqual(actual[0]["executables"], [str(expected)])

    def test_shortcut_to_launcher_resolves_parent_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Some Game"
            target = exe(root, "launcher/startup_runner.exe")
            expected = exe(root, "Main.exe")
            (root / "Main_Data").mkdir()
            with patch("radiator.games.shortcuts", return_value=[{"target": str(target)}]), \
                    patch("radiator.games.fixed_drives", return_value=[]), \
                    patch("radiator.games.uninstall_entries", return_value=[]), \
                    patch("radiator.games.reg_value", return_value=""):
                found = discover()
            actual = [g for g in found if str(expected) in g["executables"]]
            self.assertEqual(len(actual), 1)
            self.assertEqual(actual[0]["source"], "快捷方式")

    def test_disk_container_and_explicit_legacy_game_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            drive = Path(tmp)
            root = drive / "OtherContainer/Subfolder/Game"
            expected = exe(root, "Main.exe")
            (root / "Main_Data").mkdir()
            legacy_root = drive / "LegacyTitle"
            legacy = exe(legacy_root, "LegacyTitle.exe")
            with patch("radiator.games.shortcuts", return_value=[]), \
                    patch("radiator.games.fixed_drives", return_value=[drive]), \
                    patch("radiator.games.uninstall_entries", return_value=[]), \
                    patch("radiator.games.reg_value", return_value=""):
                found = discover([str(legacy_root)])
            paths = {p for game in found for p in game["executables"]}
            self.assertIn(str(expected), paths)
            self.assertIn(str(legacy), paths)

    def test_steam_reads_secondary_library_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Steam"
            library = Path(tmp) / "OtherLibrary"
            (root / "steamapps").mkdir(parents=True)
            (root / "steamapps/libraryfolders.vdf").write_text(
                '"libraryfolders" { "1" { "path" "' + str(library).replace('\\', '\\\\') + '" } }', encoding="utf-8")
            expected = exe(library / "steamapps/common/Example", "Example.exe")
            (library / "steamapps/appmanifest_123.acf").write_text(
                '"AppState" { "appid" "123" "name" "Example Game" "installdir" "Example" }', encoding="utf-8")
            with patch("radiator.games.fixed_drives", return_value=[]), \
                    patch("radiator.games.reg_value", return_value=str(root)):
                found = list(steam_games())
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["id"], "steam:123")
            self.assertEqual(found[0]["executables"], [str(expected)])

    def test_gog_manifest_uses_primary_play_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = exe(root, "bin/RealGame.exe")
            exe(root, root.name + ".exe")
            (root / "goggame-42.info").write_text(json.dumps({"name": "GOG Example", "playTasks": [
                {"isPrimary": True, "path": "bin/RealGame.exe"}]}), encoding="utf-8")
            with patch("radiator.games.registry_children", side_effect=lambda hive, key:
                       [key + r"\42"] if key == r"SOFTWARE\GOG.com\Games" and hive == 0 else []), \
                    patch("radiator.games.reg_value", return_value=str(root)), \
                    patch("radiator.games.winreg.HKEY_CURRENT_USER", 0):
                found = list(other_platform_games())
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["name"], "GOG Example")
            self.assertEqual(found[0]["executables"], [str(expected)])


class RuleRemovalTests(unittest.TestCase):
    def test_old_automatic_launcher_entry_pruned_but_manual_rule_retained(self):
        wrong = {"id": "folder:launcher", "name": "Wrong", "install_dir": r"D:\Title\launcher",
                 "executables": [r"D:\Title\launcher\LiveBox\es_broadcast_bridge.exe"]}
        manual = dict(wrong, id="manual:helper")
        self.assertEqual([g["id"] for g in merge_games([wrong, manual], [])], ["manual:helper"])

    def test_delete_persist_rescan_and_readd(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = exe(Path(tmp), "Test.exe")
            game = {"id": "manual:test", "name": "Test", "executables": [str(target)], "enabled": False}
            config = {"games": [game], "extra_roots": [], "exit_delay_seconds": 10}
            self.assertEqual(delete_games(config, [game["id"]]), 1)
            self.assertTrue(target.exists())
            config_file = Path(tmp) / "config.json"
            atomic_json(config_file, config)
            reloaded = load_config(config_file)
            alias = dict(game, id="folder:changed-source")
            self.assertEqual(merge_games(reloaded["games"], [alias], reloaded["excluded_games"]), [])
            allow_game(reloaded, game)
            self.assertEqual(len(merge_games([], [game], reloaded["excluded_games"])), 1)

    def test_bulk_delete_builtin_and_manual_does_not_resurrect(self):
        config = {"games": copy.deepcopy(KNOWN) + [{"id": "manual:test", "executables": []}]}
        self.assertEqual(delete_games(config, ["known:cs", "manual:test"]), 2)
        merged = merge_games(config["games"], KNOWN, config["excluded_games"])
        self.assertEqual([g["id"] for g in merged], ["known:delta"])

    def test_changed_source_retains_disabled_setting_and_missing_paths(self):
        old = [{"id": "manual:x", "name": "Old", "enabled": False, "executables": [r"D:\Game\Main.exe"]}]
        found = [{"id": "folder:x", "name": "New", "executables": [r"d:\game\main.exe"]}]
        merged = merge_games(old, found)
        self.assertEqual(len(merged), 1)
        self.assertFalse(merged[0]["enabled"])
        old_known = copy.deepcopy(KNOWN)
        old_known[1]["executables"] = [r"D:\Delta\Game.exe"]
        self.assertEqual(merge_games(old_known, KNOWN)[1]["executables"], [r"D:\Delta\Game.exe"])


if __name__ == "__main__":
    unittest.main()
