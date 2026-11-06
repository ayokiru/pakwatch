"""Game snapshots and the mod report: which game files each mod replaces, which of those a patch changed,
and which files two mods both replace."""
from __future__ import annotations

import gzip
import hashlib
import os
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import ue4ss, utoc
from .pak import read_pak
from .utoc import Toc, read_toc

RECORD = 32  # 12-byte chunk id + 20-byte hash


def is_mod(toc_path: Path, paks_dir: Path) -> bool:
    """Mods are *_P containers (UE loads them after the game's) or anything in a subfolder such as ~mods."""
    return toc_path.stem.endswith("_P") or toc_path.parent != paks_dir


def containers(paks_dir: Path) -> tuple[list[Path], list[Path]]:
    """(game .utoc files, mods). A mod is a .utoc, or a .pak with no .utoc of the same name next to it (a .pak
    beside a .utoc is only the container's small companion)."""
    found = sorted(Path(paks_dir).rglob("*.utoc"))
    paks = [p for p in sorted(Path(paks_dir).rglob("*.pak")) if is_mod(p, paks_dir) and not p.with_suffix(".utoc").exists()]
    return [p for p in found if not is_mod(p, paks_dir)], sorted([p for p in found if is_mod(p, paks_dir)] + paks)


def read_mod(path: Path):
    return read_toc(path) if path.suffix.lower() == ".utoc" else read_pak(path)


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


def oodle_dirs(paks_dir: Path) -> tuple[Path, ...]:
    """Where a game keeps its Oodle DLL: next to the exe in <Project>/Binaries/Win64, or the install folder."""
    paks_dir = Path(paks_dir)
    if paks_dir.parent.name.lower() != "content":
        return (paks_dir,)
    project = paks_dir.parent.parent
    return (project / "Binaries" / "Win64", project.parent, project.parent / "Engine" / "Binaries" / "Win64")


# --- snapshots -----------------------------------------------------------------------------------------
def store_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "pakwatch"


def store_dir(paks_dir: Path) -> Path:
    return store_root() / hashlib.sha1(str(Path(paks_dir).resolve()).lower().encode()).hexdigest()[:12]


@dataclass
class Snapshot:
    fingerprint: str
    taken: str
    chunks: dict[bytes, bytes]
    build: str = ""  # Steam build id of this game version, if known
    exe: str = ""    # size and time of the game's exe, if found (older snapshots have none)

    def save(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.taken.replace(':', '')}_{self.fingerprint}.snap"
        body = b"".join(c + h for c, h in sorted(self.chunks.items()))
        head = " ".join(filter(None, ("pakwatch1", self.fingerprint, self.taken, self.build, self.exe and "exe=" + self.exe)))
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
        extra = parts[3:]
        build = extra[0] if extra and not extra[0].startswith("exe=") else ""
        return Snapshot(parts[1], parts[2], chunks, build, next((x[4:] for x in extra if x.startswith("exe=")), ""))


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
    uses_changed: list[bytes] = field(default_factory=list)  # game packages its own files import that the patch changed
    uses_removed: list[bytes] = field(default_factory=list)  # ...or removed
    names: dict[bytes, str] = field(default_factory=dict)    # package names for those, where known
    added: int = 0                                         # files of its own
    newer_than_patch: bool = False                         # the mod file was written after the game's files

    @property
    def status(self) -> str:
        if self.changed or self.removed or self.uses_changed or self.uses_removed:
            if self.newer_than_patch:
                return "updated after patch"
            return "patch touched" if self.changed or self.removed else "uses changed"
        return "ok" if self.replaced else "adds only"

    def import_name(self, cid: bytes) -> str:
        return self.names.get(cid) or utoc.label(cid)


@dataclass
class Report:
    game_files: int
    snapshot: Snapshot | None
    patched: bool                                          # the game differs from the snapshot
    mods: list[ModReport]
    conflicts: dict[bytes, list[Toc]]                      # file -> mods that all replace it, the one that loads first
    since: str = ""                                        # when this version of the game was first seen (UTC)
    first: bool = False                                    # no snapshot at all before this run
    unreadable: list[tuple[str, str]] = field(default_factory=list)  # (mod name, why) for mods pakwatch can't read
    files_changed: int = 0                                 # what the update did to the game as a whole
    files_added: int = 0
    files_removed: int = 0
    build: str = ""                                        # Steam build id now, and before the update
    build_before: str = ""
    ue4ss: dict | None = None                              # UE4SS folder, version and script mods (ue4ss.find)
    exe_changed: bool = False                              # the update changed the game's exe


def build_report(game: dict[bytes, bytes], mods: list[Toc], snap: Snapshot | None, fp: str,
                 patch_time: float = 0.0) -> Report:
    patched = snap is not None and snap.fingerprint != fp
    reports, owners = [], {}
    gone = {c for c, h in snap.chunks.items() if c[11] == utoc.PACKAGE and game.get(c) != h} if patched else set()
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
        own = m.chunks().keys()  # an import the mod brings itself doesn't count
        for cid in sorted((getattr(m, "imports", None) or set()) & gone - own):
            (r.uses_changed if cid in game else r.uses_removed).append(cid)
        reports.append(r)
    # Seen in Phantom Blade Zero: of two mods replacing one package, the file name first in ASCII order loads
    conflicts = {cid: sorted(ms, key=lambda t: t.path.name) for cid, ms in owners.items() if len(ms) > 1}
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
    game_tocs = [read_toc(p) for p in game_paths]
    game = game_chunks(game_tocs)
    patch_time = max(p.stat().st_mtime for p in game_paths)
    snap = baseline(folder, fp)
    readable, unreadable = [], []
    for p in mod_paths:
        try:
            m = read_mod(p)
        except (ValueError, OSError, struct.error) as e:  # one broken mod must not hide the others
            unreadable.append((p.stem, str(e)))
            continue
        if getattr(m, "encrypted", False) and not m.chunks():
            unreadable.append((p.stem, "its file list is encrypted"))
            continue
        readable.append(m)
    dirs = oodle_dirs(paks_dir)
    if snap is not None and snap.fingerprint != fp:  # imports only matter after an update
        for m in readable:
            if isinstance(m, Toc):
                try:
                    m.imports = {c for imported in utoc.imports(m, dirs).values() for c in imported}
                except (ValueError, OSError) as e:
                    m.imports_note = str(e)
    report = build_report(game, readable, snap, fp, patch_time)
    for r in report.mods:
        if r.uses_changed or r.uses_removed:
            r.names = utoc.import_names(r.toc, dirs)
            for cid in r.uses_changed + r.uses_removed:  # the game's own index, when it isn't encrypted
                t = next((t for t in game_tocs if t.names and cid in t.chunk_ids), None)
                if cid not in r.names and t:
                    r.names[cid] = t.name_of(cid).replace("../../../", "")
    report.unreadable = unreadable
    from .steam import build_id  # steam.py imports this module
    report.build = build_id(paks_dir)
    exe = ue4ss.exe_signature(paks_dir)
    report.exe_changed = bool(report.patched and snap.exe and exe and snap.exe != exe)
    report.ue4ss = ue4ss.find(paks_dir)
    snaps = _snaps(folder)
    report.first = not snaps
    mine = [p for p in snaps if p.stem.endswith("_" + fp)]
    if mine:
        t = mine[0].stem.rsplit("_", 1)[0]  # 2026-11-04T104512Z, the name can't hold colons
        report.since = f"{t[:13]}:{t[13:15]}:{t[15:]}"
    else:
        report.since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        Snapshot(fp, report.since, game, report.build, exe).save(folder)
    return report
