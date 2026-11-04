"""Turning a mod off and on again: its files move out of the game into pakwatch's folder, and back.

Out of the game means outside Paks entirely: Unreal loads containers from every subfolder of Paks, so a
"disabled" subfolder there would still be loaded."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import scan


def disabled_dir(paks: Path) -> Path:
    return scan.store_dir(paks) / "disabled"


def _files(folder: Path, stem: str) -> list[Path]:
    """Every file of one container: name.utoc, name.ucas, name.pak, name.sig and partitions such as name_s1.ucas."""
    part = re.compile(re.escape(stem) + r"(_s\d+)?", re.IGNORECASE)
    return sorted(p for p in folder.iterdir() if p.is_file() and part.fullmatch(p.stem)) if folder.is_dir() else []


def _move(files: list[Path], dest: Path) -> None:
    """All or nothing: if one file can't move (the game has it open), the ones already moved go back."""
    dest.mkdir(parents=True, exist_ok=True)
    clash = [p.name for p in files if (dest / p.name).exists()]
    if clash:
        raise FileExistsError(f"{dest} already has {', '.join(clash)}; pakwatch won't overwrite it")
    moved = []
    try:
        for p in files:
            shutil.move(str(p), str(dest / p.name))
            moved.append(p)
    except OSError:
        for p in reversed(moved):
            shutil.move(str(dest / p.name), str(p))
        raise


def _find(root: Path, name: str) -> Path:
    hits = [p for ext in ("*.utoc", "*.pak") for p in root.rglob(ext) if p.stem.lower() == name.lower()] if root.is_dir() else []
    if not hits:
        raise FileNotFoundError(f"no mod named {name}")
    return hits[0]


def turn_off(paks: Path, name: str) -> None:
    paks = Path(paks)
    _, mods = scan.containers(paks)
    found = next((m for m in mods if m.stem.lower() == name.lower()), None)
    if found is None:
        raise FileNotFoundError(f"no mod named {name} in {paks}")
    _move(_files(found.parent, found.stem), disabled_dir(paks) / found.parent.relative_to(paks))


def turn_on(paks: Path, name: str) -> None:
    paks = Path(paks)
    root = disabled_dir(paks)
    found = _find(root, name)
    _move(_files(found.parent, found.stem), paks / found.parent.relative_to(root))


def turned_off(paks: Path) -> list[dict]:
    """Mods pakwatch turned off for this game: name, and the folder under Paks they return to."""
    root = disabled_dir(paks)
    if not root.is_dir():
        return []
    seen = {}
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() in (".utoc", ".pak") and p.stem.lower() not in seen:
            rel = p.parent.relative_to(root)
            seen[p.stem.lower()] = {"name": p.stem, "where": rel.name if rel.parts else "Paks"}
    return sorted(seen.values(), key=lambda m: m["name"].lower())
