"""Game snapshots and the mod report: which game files each mod replaces, which of those a patch changed,
and which files two mods both replace."""
from __future__ import annotations

import gzip
import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .utoc import Toc, read_toc

RECORD = 32  # 12-byte chunk id + 20-byte hash


def is_mod(toc_path: Path, paks_dir: Path) -> bool:
    """Mods are *_P containers (UE loads them after the game's) or anything in a subfolder such as ~mods."""
    return toc_path.stem.endswith("_P") or toc_path.parent != paks_dir


def containers(paks_dir: Path) -> tuple[list[Path], list[Path]]:
    found = sorted(Path(paks_dir).rglob("*.utoc"))
    return [p for p in found if not is_mod(p, paks_dir)], [p for p in found if is_mod(p, paks_dir)]


def fingerprint(game: list[Path]) -> str:
    """Changes whenever a patch rewrites a game container."""
    h = hashlib.sha1()
    for p in game:
        st = p.stat()
        h.update(f"{p.name}|{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()[:16]


def game_chunks(tocs: list[Toc]) -> dict[bytes, bytes]:
    out: dict[bytes, bytes] = {}
    for t in tocs:
        out.update(t.chunks())
    return out


def find_paks(folder: Path) -> Path:
    """The game folder, its Content\\Paks, or anything between: UE games keep containers in <Project>/Content/Paks."""
    folder = Path(folder)
    if any(folder.glob("*.utoc")):
        return folder
    for pattern in ("Content/Paks", "*/Content/Paks"):
        hits = [p for p in folder.glob(pattern) if any(p.glob("*.utoc"))]
        if len(hits) == 1:
            return hits[0]
    raise FileNotFoundError(f"no IoStore containers (.utoc) in {folder} or its Content\\Paks")


# --- snapshots -----------------------------------------------------------------------------------------
def store_dir(paks_dir: Path) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "pakwatch"
    return base / hashlib.sha1(str(Path(paks_dir).resolve()).lower().encode()).hexdigest()[:12]


@dataclass
class Snapshot:
    fingerprint: str
    taken: str
    chunks: dict[bytes, bytes]
    build: str = ""  # Steam build id of this game version, if known

    def save(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.taken.replace(':', '')}_{self.fingerprint}.snap"
        body = b"".join(c + h for c, h in sorted(self.chunks.items()))
        head = " ".join(filter(None, ("pakwatch1", self.fingerprint, self.taken, self.build)))
        with gzip.open(path, "wb") as f:
            f.write(head.encode() + b"\n" + body)
        return path

    @staticmethod
    def load(path: Path) -> Snapshot:
        data = gzip.decompress(Path(path).read_bytes())
        head, body = data.split(b"\n", 1)
        parts = head.decode().split(" ")  # snapshots from 0.1 have no build id
        if parts[0] != "pakwatch1" or len(parts) < 3 or len(body) % RECORD:
            raise ValueError(f"{Path(path).name} is not a pakwatch snapshot")
        chunks = {body[i:i + 12]: body[i + 12:i + RECORD] for i in range(0, len(body), RECORD)}
        return Snapshot(parts[1], parts[2], chunks, parts[3] if len(parts) > 3 else "")


def _snaps(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.snap")) if folder.is_dir() else []  # names start with the UTC time


def baseline(folder: Path, fp: str) -> Snapshot | None:
    """The newest snapshot of an earlier game version: the report keeps showing what the last patch changed
    on every run until the next patch, not only on the first run after it."""
    older = [p for p in _snaps(folder) if not p.stem.endswith("_" + fp)]
    return Snapshot.load(older[-1]) if older else None


# --- report --------------------------------------------------------------------------------------------
@dataclass
class ModReport:
    toc: Toc
    replaced: list[bytes] = field(default_factory=list)   # game files the mod replaces
    changed: list[bytes] = field(default_factory=list)    # ...that the patch changed since the snapshot
    removed: list[bytes] = field(default_factory=list)    # ...that the patch removed
    added: int = 0                                         # files of its own
    newer_than_patch: bool = False                         # the mod file was written after the game's files

    @property
    def status(self) -> str:
        if self.changed or self.removed:
            return "updated after patch" if self.newer_than_patch else "patch touched"
        return "ok" if self.replaced else "adds only"


@dataclass
class Report:
    game_files: int
    snapshot: Snapshot | None
    patched: bool                                          # the game differs from the snapshot
    mods: list[ModReport]
    conflicts: dict[bytes, list[Toc]]                      # file -> mods that all replace it
    since: str = ""                                        # when this version of the game was first seen (UTC)
    first: bool = False                                    # no snapshot at all before this run
    files_changed: int = 0                                 # what the update did to the game as a whole
    files_added: int = 0
    files_removed: int = 0
    build: str = ""                                        # Steam build id now, and before the update
    build_before: str = ""


def build_report(game: dict[bytes, bytes], mods: list[Toc], snap: Snapshot | None, fp: str,
                 patch_time: float = 0.0) -> Report:
    patched = snap is not None and snap.fingerprint != fp
    reports, owners = [], {}
    for m in mods:
        r = ModReport(m, newer_than_patch=patched and m.path.exists() and m.path.stat().st_mtime > patch_time)
        for cid in m.chunks():
            owners.setdefault(cid, []).append(m)
            if cid in game or (snap and cid in snap.chunks):
                r.replaced.append(cid)
                if snap and cid in snap.chunks:
                    if cid not in game:
                        r.removed.append(cid)
                    elif game[cid] != snap.chunks[cid]:
                        r.changed.append(cid)
            else:
                r.added += 1
        reports.append(r)
    conflicts = {cid: ms for cid, ms in owners.items() if len(ms) > 1}
    report = Report(len(game), snap, patched, reports, conflicts)
    if patched:
        old = snap.chunks
        report.files_changed = sum(1 for c, h in game.items() if c in old and old[c] != h)
        report.files_added = len(game.keys() - old.keys())
        report.files_removed = len(old.keys() - game.keys())
        report.build_before = snap.build
    return report


def run(paks_dir: Path, folder: Path | None = None) -> Report:
    """Read the game and its mods, compare with the last snapshot, and store a new snapshot when the game
    changed (or there is none yet), so the next patch is caught too."""
    paks_dir = Path(paks_dir)
    game_paths, mod_paths = containers(paks_dir)
    if not game_paths:
        raise FileNotFoundError(f"no .utoc containers in {paks_dir}")
    folder = folder or store_dir(paks_dir)
    fp = fingerprint(game_paths)
    game = game_chunks([read_toc(p) for p in game_paths])
    patch_time = max(p.stat().st_mtime for p in game_paths)
    report = build_report(game, [read_toc(p) for p in mod_paths], baseline(folder, fp), fp, patch_time)
    from .steam import build_id  # steam.py imports this module
    report.build = build_id(paks_dir)
    snaps = _snaps(folder)
    report.first = not snaps
    mine = [p for p in snaps if p.stem.endswith("_" + fp)]
    if mine:
        t = mine[0].stem.rsplit("_", 1)[0]  # 2026-11-04T104512Z, the name can't hold colons
        report.since = f"{t[:13]}:{t[13:15]}:{t[15:]}"
    else:
        report.since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        Snapshot(fp, report.since, game, report.build).save(folder)
    return report
