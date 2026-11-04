"""Unreal Engine games installed through Steam: every library folder, every game that has IoStore containers."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import scan

_PATH = re.compile(r'"path"\s+"([^"]+)"')
_FIELD = r'"{}"\s+"([^"]*)"'


def steam_root() -> Path | None:
    if sys.platform == "win32":
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    value = winreg.QueryValueEx(k, "SteamPath" if hive == winreg.HKEY_CURRENT_USER else "InstallPath")[0]
                    if Path(value).is_dir():
                        return Path(value)
            except OSError:
                continue
    for p in (Path.home() / ".steam" / "steam", Path.home() / ".local" / "share" / "Steam"):
        if p.is_dir():
            return p
    return None


def libraries(root: Path) -> list[Path]:
    """Steam's own folder plus every library in libraryfolders.vdf."""
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        for raw in _PATH.findall(vdf.read_text(encoding="utf-8", errors="replace")):
            p = Path(raw.replace("\\\\", "\\"))
            if p.is_dir() and p not in libs:
                libs.append(p)
    return libs


@dataclass
class Game:
    name: str
    folder: Path
    paks: Path
    mods: int


def games(root: Path | None = None) -> list[Game]:
    root = root or steam_root()
    if root is None:
        return []
    found = []
    for lib in libraries(root):
        apps = lib / "steamapps"
        names = {}
        for acf in apps.glob("appmanifest_*.acf"):
            text = acf.read_text(encoding="utf-8", errors="replace")
            installdir = re.search(_FIELD.format("installdir"), text)
            name = re.search(_FIELD.format("name"), text)
            if installdir and name:
                names[installdir.group(1).lower()] = name.group(1)
        common = apps / "common"
        for folder in sorted(common.iterdir()) if common.is_dir() else []:
            paks = next((p for p in folder.glob("*/Content/Paks") if any(p.glob("*.utoc"))), None)
            if paks is None:
                continue
            game_files, mods = scan.containers(paks)
            if not game_files:  # an uninstalled game: Steam leaves the folder behind when mods are in it
                continue
            found.append(Game(names.get(folder.name.lower(), folder.name), folder, paks, len(mods)))
    return sorted(found, key=lambda g: (-g.mods, g.name.lower()))


if __name__ == "__main__":
    for g in games():
        print(f"{g.name}: {g.mods} mods, {g.paks}")
    if os.environ.get("PAKWATCH_DEBUG"):
        print(steam_root(), libraries(steam_root()) if steam_root() else [])
