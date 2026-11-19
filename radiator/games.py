"""Offline discovery from manifests, shortcuts, install records and game engines."""
import copy
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import winreg
from .policy import normalize

KNOWN = [
    {"id": "known:cs", "name": "CS2 / CSGO", "source": "内置识别",
     "process_names": ["cs2.exe", "csgo.exe"], "executables": [], "enabled": True},
    {"id": "known:delta", "name": "三角洲行动", "source": "内置识别",
     "process_names": ["DeltaForceClient-Win64-Shipping.exe", "DeltaForce-Win64-Shipping.exe"],
     "executables": [], "enabled": True},
]
SKIP_DIRS = {"redist", "_commonredist", "directx", "vcredist", "dotnet", "prerequisites",
             "installer", "uninstall", "anticheatexpert", "easyanticheat", "battleye",
             "icreate", "metaperf", "wegamelauncher", "launcher", "webview", "cef",
             "crashreporter", "support", "tools", "engine", "thirdparty", "plugins",
             "node_modules", ".git", "windowsapps", "$recycle.bin", "system volume information",
             "windows", "appdata", "pkgs", "envs", ".minecraft", "screenshots", "livebox", "common_apps"}
SKIP_EXE = re.compile(r"launch|unins|卸载|setup|install|crash|report|service|helper|cef|webview|"
                      r"^steam(?:\.exe|_|client)|anticheat|benchmark|updat|server|editor|worldedit|dxdiag|vcredist|"
                      r"startup_runner|gpu_detect|assistant|tinydl|symchk|ffmpeg|ffprobe|dump|patch|补丁|攻略|功略", re.I)
STEAM_TOOLS = {"228980", "365670", "431960", "1826330", "250820"}
KNOWN_MAIN = {"cs2.exe", "csgo.exe", "war3.exe", "warcraft iii.exe", "frozen throne.exe"}


def read_text(path):
    try:
        data = Path(path).read_bytes()
        encodings = ("utf-16",) if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "gb18030")
        for encoding in encodings:
            try:
                return data.decode(encoding)
            except UnicodeError:
                continue
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def reg_value(hive, key, name):
    try:
        with winreg.OpenKey(hive, key) as handle:
            return winreg.QueryValueEx(handle, name)[0]
    except OSError:
        return ""


def registry_children(hive, key):
    try:
        with winreg.OpenKey(hive, key) as parent:
            return [key + "\\" + winreg.EnumKey(parent, i) for i in range(winreg.QueryInfoKey(parent)[0])]
    except OSError:
        return []


def uninstall_entries():
    """Include programs whose only installation clue is their DisplayIcon."""
    seen = set()
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for base in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            for sub in registry_children(hive, base):
                name = reg_value(hive, sub, "DisplayName")
                location = reg_value(hive, sub, "InstallLocation")
                if not location:
                    icon = str(reg_value(hive, sub, "DisplayIcon"))
                    match = re.match(r'^\s*"?(.+?\.exe)(?:"|,|$)', icon, re.I)
                    if match:
                        location = str(Path(os.path.expandvars(match.group(1))).parent)
                if name and location:
                    path = Path(os.path.expandvars(str(location).strip('"')))
                    key = (name, normalize(str(path)))
                    if key not in seen:
                        seen.add(key)
                        yield name, path


def exe_score(exe, root):
    name = exe.name.casefold()
    if SKIP_EXE.search(name):
        return -10000
    score = 800 if "shipping" in name else 0
    if exe.with_name(exe.stem + "_Data").is_dir():
        score += 650
    if exe.with_suffix(".pck").is_file():
        score += 550
    if name in KNOWN_MAIN:
        score += 600
    comparable = lambda text: re.sub(r"[\W_]+", "", text.casefold())
    if comparable(exe.stem) == comparable(root.name):
        score += 220
    elif comparable(exe.stem) and comparable(exe.stem) in comparable(root.name):
        score += 100
    score += max(0, 90 - (len(exe.relative_to(root).parts) - 1) * 12)
    try:
        score += min(80, exe.stat().st_size // (2 * 1024 * 1024))
    except OSError:
        pass
    return score


def is_executable(path):
    try:
        with Path(path).open("rb") as handle:
            return handle.read(2) == b"MZ"
    except OSError:
        return False


def candidate_exes(root):
    root = Path(root)
    ranked, visited = [], 0
    for current, dirs, files in os.walk(str(root)):
        depth = len(Path(current).relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if depth < 7 and d.casefold() not in SKIP_DIRS
                         and not Path(current, d).is_symlink())
        visited += len(files)
        if visited > 12000:
            break
        for name in files:
            if name.lower().endswith(".exe"):
                exe = Path(current, name)
                score = exe_score(exe, root)
                if score >= 0 and is_executable(exe):
                    ranked.append((score, str(exe)))
    ranked.sort(key=lambda entry: (-entry[0], entry[1].casefold()))
    if not ranked:
        return []
    shipping = [path for _, path in ranked if "shipping" in Path(path).name.casefold()]
    if shipping:
        return shipping[:4]
    warcraft = [path for _, path in ranked if Path(path).name.casefold() in
                {"war3.exe", "warcraft iii.exe", "frozen throne.exe"}]
    if warcraft:
        return warcraft
    best_score, best = ranked[0]
    return [path for score, path in ranked if Path(path).name.casefold() == Path(best).name.casefold()
            and score >= best_score - 50][:4]


def is_game_folder(folder):
    folder = Path(folder)
    try:
        names = {p.name.casefold() for p in folder.iterdir()}
    except OSError:
        return False
    if names & {"unityplayer.dll", "gameassembly.dll", "renpy", "rpg_rt.exe", "war3.exe"}:
        return True
    if (folder / "rail_files/rail_game_identify.json").is_file():
        return True
    if any(n.endswith("_data") and (folder / (n[:-5] + ".exe")).is_file() for n in names) or any(n.endswith(".pck") for n in names):
        return True
    if "engine" in names:
        if "content" in names or "binaries" in names:
            return True
        if any((folder / sub / "Binaries").is_dir() for sub in names if sub not in SKIP_DIRS):
            return True
    return any((folder / sub / "Engine").is_dir() for sub in ("Win64", "Game", "game"))


def game_record(root, source, name=None, identifier=None, trusted=False, preferred=None):
    root = Path(root)
    if root.name.casefold() in SKIP_DIRS or not root.is_dir() or (not trusted and not is_game_folder(root)):
        return None
    exes = candidate_exes(root)
    if preferred and is_executable(preferred) and not SKIP_EXE.search(Path(preferred).name):
        if not any("shipping" in Path(x).name.casefold() for x in exes):
            exes = [str(Path(preferred))]
    if not exes:
        return None
    title = re.sub(r"\(\d{6,}\)$", "", name or root.name).strip()
    return {"id": identifier or "folder:" + normalize(str(root)), "name": title,
            "source": source, "install_dir": str(root), "executables": exes,
            "process_names": [], "enabled": True}


def fixed_drives():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    mask = kernel.GetLogicalDrives()
    return [Path(chr(65 + bit) + ":/") for bit in range(26) if mask & (1 << bit)
            and kernel.GetDriveTypeW(chr(65 + bit) + ":\\") == 3]


def shortcuts():
    script = Path(__file__).with_name("scan_shortcuts.ps1")
    shell = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(shell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=40, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise OSError("无法读取快捷方式：" + result.stderr.decode("utf-8", errors="replace")[:150])
    data = json.loads(result.stdout.decode("utf-8-sig") or "[]")
    return data if isinstance(data, list) else [data]


def steam_games():
    roots = set()
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key in (r"SOFTWARE\Valve\Steam", r"SOFTWARE\WOW6432Node\Valve\Steam"):
            for value in ("SteamPath", "InstallPath"):
                path = reg_value(hive, key, value)
                if path:
                    roots.add(Path(path))
    for drive in fixed_drives():
        for rel in ("Steam", "Program Files (x86)/Steam", "Program Files/Steam"):
            if (drive / rel).is_dir():
                roots.add(drive / rel)
    libraries = set(roots)
    for root in roots:
        for rel in ("steamapps/libraryfolders.vdf", "config/libraryfolders.vdf"):
            libraries.update(Path(x.replace("\\\\", "\\")) for x in
                             re.findall(r'"path"\s*"([^"]+)"', read_text(root / rel)))
    for library in sorted(libraries, key=str):
        for manifest in sorted((library / "steamapps").glob("appmanifest_*.acf")):
            values = dict(re.findall(r'"([^"\r\n]+)"\s*"([^"\r\n]*)"', read_text(manifest)))
            appid = values.get("appid", "")
            if appid in STEAM_TOOLS or not values.get("installdir"):
                continue
            game = game_record(library / "steamapps/common" / values["installdir"], "Steam",
                               values.get("name"), "steam:" + appid, trusted=True)
            if game:
                yield game


def epic_games():
    folders = {Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Epic/EpicGamesLauncher/Data"}
    for key in (r"SOFTWARE\Epic Games\EpicGamesLauncher", r"SOFTWARE\WOW6432Node\Epic Games\EpicGamesLauncher"):
        path = reg_value(winreg.HKEY_LOCAL_MACHINE, key, "AppDataPath")
        if path:
            folders.add(Path(path))
    for folder in folders:
        for manifest in sorted((folder / "Manifests").glob("*.item")):
            try:
                item = json.loads(read_text(manifest))
                root = Path(item["InstallLocation"])
                game = game_record(root, "Epic", item.get("DisplayName"), "epic:" + item["AppName"],
                                   trusted=True, preferred=root / item.get("LaunchExecutable", ""))
                if game:
                    yield game
            except (ValueError, KeyError, TypeError):
                continue


def other_platform_games():
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for prefix in ("SOFTWARE\\", "SOFTWARE\\WOW6432Node\\"):
            for suffix, source in ((r"Ubisoft\Launcher\Installs", "Ubisoft"), (r"Origin Games", "EA / Origin"),
                                    (r"GOG.com\Games", "GOG")):
                for key in registry_children(hive, prefix + suffix):
                    path = next((reg_value(hive, key, field) for field in
                                 ("InstallDir", "InstallLocation", "path") if reg_value(hive, key, field)), "")
                    if path:
                        root = Path(path)
                        preferred = None
                        title = None
                        if source == "GOG":
                            for manifest in root.glob("goggame-*.info"):
                                try:
                                    data = json.loads(read_text(manifest))
                                    primary = next((task for task in data.get("playTasks", [])
                                                    if task.get("isPrimary") and task.get("path")), None)
                                    if primary:
                                        preferred = root / primary["path"]
                                        title = data.get("name")
                                        break
                                except (ValueError, TypeError, AttributeError):
                                    continue
                        game = game_record(root, source, title, trusted=True, preferred=preferred)
                        if game:
                            yield game


def shallow_folders(root, depth):
    root = Path(root)
    for current, dirs, _ in os.walk(str(root)):
        rel_depth = len(Path(current).relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if rel_depth < depth and d.casefold() not in SKIP_DIRS
                         and not Path(current, d).is_symlink())
        yield Path(current), dirs


def deduplicate(games):
    result = []
    for incoming in games:
        game = copy.deepcopy(incoming)
        paths = {normalize(x) for x in game.get("executables", [])}
        names = {Path(x).name.casefold() for x in game.get("executables", [])}
        match = next((g for g in result if g["id"] == game["id"] or
                      paths & {normalize(x) for x in g.get("executables", [])} or
                      names & {x.casefold() for x in g.get("process_names", [])}), None)
        if match:
            by_path = {normalize(x): x for x in match.get("executables", []) + game.get("executables", [])}
            match["executables"] = list(by_path.values())
            if game.get("install_dir"):
                match.setdefault("install_dir", game["install_dir"])
            if match.get("source") == "内置识别":
                match["source"] = game["source"]
        else:
            result.append(game)
    return result


def discover(extra_roots=(), progress=None):
    progress = progress or (lambda message: None)
    games = copy.deepcopy(KNOWN)
    warnings = []
    for label, provider in (("平台安装清单", steam_games), ("Epic 安装清单", epic_games),
                             ("GOG / EA / Ubisoft 安装记录", other_platform_games)):
        progress("正在读取" + label + "…")
        try:
            games.extend(provider())
        except (OSError, ValueError) as exc:
            warnings.append(label + "：" + str(exc))
    progress("正在解析桌面和开始菜单快捷方式…")
    hinted_roots = []
    try:
        for link in shortcuts():
            target = Path(link.get("target", ""))
            if target.suffix.lower() != ".exe" or not target.is_file():
                continue
            for root in list(target.parents)[:3]:
                if root.name.casefold() not in SKIP_DIRS and is_game_folder(root):
                    hinted_roots.append((root, "快捷方式", None))
                    break
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        warnings.append("快捷方式：" + str(exc))
    progress("正在检查安装记录和各磁盘的游戏目录…")
    for name, root in uninstall_entries():
        # Some Tencent uninstall records point at the launcher, not the game root.
        if root.name.casefold() in SKIP_DIRS:
            root = root.parent
        if root.is_dir():
            hinted_roots.append((root, "安装记录", name))
    roots = {(Path(x), 3, True) for x in extra_roots if Path(x).is_dir()}
    for drive in fixed_drives():
        roots.add((drive, 3, False))
        for rel in ("Games", "Game", "PC Games", "GameLibrary", "WeGameApps", "GOG Games",
                    "XboxGames", "Program Files", "Program Files (x86)"):
            if (drive / rel).is_dir():
                roots.add((drive / rel, 3, False))
    scanned = set()
    covered = {normalize(g["install_dir"]) for g in games if g.get("install_dir")}
    def scan_one(root, source, title=None, trusted=False):
        key = normalize(str(root))
        if (key, trusted) in scanned or key in covered:
            return None
        scanned.add((key, trusted))
        game = game_record(root, source, title, trusted=trusted)
        if game:
            games.append(game)
            covered.add(key)
        return game
    for root, source, name in hinted_roots:
        scan_one(root, source, name)
    for root, depth, explicit in sorted(roots, key=lambda entry: (len(entry[0].parts), str(entry[0]))):
        for folder, dirs in shallow_folders(root, depth):
            key = normalize(str(folder))
            if any(key == p or key.startswith(p + os.sep) for p in covered):
                dirs[:] = []
                continue
            direct_exe = explicit and any(folder.glob("*.exe"))
            if scan_one(folder, "指定目录" if explicit else "磁盘游戏目录", trusted=direct_exe):
                dirs[:] = []
    found = deduplicate(games)
    if warnings:
        progress("搜索完成，部分来源不可读：" + "；".join(warnings))
    else:
        progress("搜索完成：检查 %d 个目录，发现 %d 项游戏" % (len(scanned), len(found)))
    return found


def exclusion_matches(game, excluded):
    paths = {normalize(x) for x in game.get("executables", [])}
    return any(game["id"] == entry.get("id") or
               paths & {normalize(x) for x in entry.get("executables", [])} for entry in excluded)


def merge_games(existing, found, excluded=()):
    # Migrate entries produced by older scans of launcher/dependency directories.
    # User-authored detection rules remain valid even for non-game applications.
    existing = [g for g in existing if g["id"].startswith("manual:") or
                Path(g.get("install_dir", "")).name.casefold() not in SKIP_DIRS]
    old = {g["id"]: g for g in existing}
    merged = []
    for game in found:
        game = copy.deepcopy(game)
        previous = old.get(game["id"])
        if previous is None:
            paths = {normalize(x) for x in game.get("executables", [])}
            previous = next((g for g in existing if paths & {normalize(x) for x in g.get("executables", [])}), None)
        if previous is not None:
            game["enabled"] = previous.get("enabled", True)
            if not game.get("executables"):
                game["executables"] = list(previous.get("executables", []))
        merged.append(game)
    ids = {g["id"] for g in merged}
    merged.extend(copy.deepcopy(g) for g in existing if g["id"] not in ids)
    return [g for g in deduplicate(merged) if not exclusion_matches(g, excluded)]


def delete_games(config, identifiers):
    """Delete rules, not program files, and retain an exact-path exclusion."""
    identifiers = set(identifiers)
    removed = [g for g in config["games"] if g["id"] in identifiers]
    config["games"] = [g for g in config["games"] if g["id"] not in identifiers]
    excluded = {g["id"]: g for g in config.setdefault("excluded_games", [])}
    for game in removed:
        excluded[game["id"]] = copy.deepcopy(game)
    config["excluded_games"] = list(excluded.values())
    return len(removed)


def allow_game(config, game):
    config["excluded_games"] = [entry for entry in config.get("excluded_games", [])
                                if not exclusion_matches(game, [entry])]
