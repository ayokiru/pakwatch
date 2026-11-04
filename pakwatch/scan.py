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


# --- snapshots -----------------------------------------------------------------------------------------
def store_dir(paks_dir: Path) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "pakwatch"
    return base / hashlib.sha1(str(Path(paks_dir).resolve()).lower().encode()).hexdigest()[:12]


@dataclass
class Snapshot:
    fingerprint: str
    taken: str
    chunks: dict[bytes, bytes]

    def save(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.taken.replace(':', '')}_{self.fingerprint}.snap"
        body = b"".join(c + h for c, h in sorted(self.chunks.items()))
        with gzip.open(path, "wb") as f:
            f.write(f"pakwatch1 {self.fingerprint} {self.taken}\n".encode() + body)
        return path

    @staticmethod
    def load(path: Path) -> Snapshot:
        data = gzip.decompress(Path(path).read_bytes())
        head, body = data.split(b"\n", 1)
        magic, fp, taken = head.decode().split(" ")
        if magic != "pakwatch1" or len(body) % RECORD:
            raise ValueError(f"{Path(path).name} is not a pakwatch snapshot")
        chunks = {body[i:i + 12]: body[i + 12:i + RECORD] for i in range(0, len(body), RECORD)}
        return Snapshot(fp, taken, chunks)


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
    return Report(len(game), snap, patched, reports, conflicts)


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
    if not any(p.stem.endswith("_" + fp) for p in _snaps(folder)):
        Snapshot(fp, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), game).save(folder)
    return report
