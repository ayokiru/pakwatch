"""UE4SS, the script mod loader: where it is, its version and its Lua script mods. pakwatch only reports them;
which script mod breaks after an update depends on code signatures in the exe, not on files pakwatch can compare."""
from __future__ import annotations

import struct
from pathlib import Path

FIXED_FILE_INFO = b"\xbd\x04\xef\xfe"  # VS_FIXEDFILEINFO signature in a PE version resource


def game_exe(paks: Path) -> Path | None:
    """The game's exe: <Project>/Binaries/Win64/*-Shipping.exe, or else the largest exe a few folders deep."""
    paks = Path(paks)
    if paks.parent.name.lower() != "content":
        return None
    project = paks.parent.parent
    shipping = sorted((project / "Binaries" / "Win64").glob("*-Shipping.exe"))
    if shipping:
        return shipping[0]
    found = [p for depth in range(1, 5) for p in project.parent.glob("*/" * (depth - 1) + "*.exe") if p.is_file()]
    return max(found, key=lambda p: p.stat().st_size, default=None)


def exe_signature(paks: Path) -> str:
    """Size and modification time of the game's exe; Steam rewrites the exe only when an update changes it."""
    exe = game_exe(paks)
    if exe is None:
        return ""
    st = exe.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def version(dll: Path) -> str:
    """File version from the DLL's version resource, e.g. 3.0.1; empty when there is none."""
    try:
        data = dll.read_bytes()
    except OSError:
        return ""
    key, at, i = "VS_VERSION_INFO".encode("utf-16-le"), -1, -1
    while i < 0:  # the first key with the fixed info right behind it; the same text can appear in code
        at = data.find(key, at + 1)
        if at < 0:
            return ""
        i = data.find(FIXED_FILE_INFO, at, at + 64)
    if i + 16 > len(data):
        return ""
    ms, ls = struct.unpack_from("<II", data, i + 8)
    parts = [ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF]
    while len(parts) > 2 and parts[-1] == 0:
        parts.pop()
    return ".".join(map(str, parts))


def script_mods(folder: Path) -> list[dict]:
    """Mods/<name> folders. A mod is on when mods.txt says `name : 1` or the folder has an enabled.txt."""
    flags = {}
    txt = folder / "mods.txt"
    if txt.is_file():
        for line in txt.read_text(encoding="utf-8", errors="replace").splitlines():
            name, sep, value = line.strip().partition(":")
            if sep and not name.startswith(";"):
                flags[name.strip().lower()] = value.strip() == "1"
    mods = [{"name": d.name, "on": (d / "enabled.txt").is_file() or flags.get(d.name.lower(), False)}
            for d in folder.iterdir() if d.is_dir() and d.name.lower() != "shared"] if folder.is_dir() else []
    return sorted(mods, key=lambda m: m["name"].lower())


def find(paks: Path) -> dict | None:
    """UE4SS 3 keeps itself in a ue4ss folder next to the exe (loaded by a dwmapi.dll proxy); older versions sit
    right beside the exe. Either way UE4SS.dll or UE4SS-settings.ini marks the folder."""
    paks = Path(paks)
    exe = game_exe(paks)
    places = [exe.parent] if exe else []
    if paks.parent.name.lower() == "content":
        places.append(paks.parent.parent / "Binaries" / "Win64")
    for base in (b for place in dict.fromkeys(places) for b in (place / "ue4ss", place)):
        dll = base / "UE4SS.dll"
        if dll.is_file() or (base / "UE4SS-settings.ini").is_file():
            return {"folder": base, "version": version(dll), "mods": script_mods(base / "Mods")}
    return None
