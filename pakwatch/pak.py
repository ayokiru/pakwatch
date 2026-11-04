"""Reads the file list of a legacy Unreal .pak (versions 8 to 11) and turns it into the same shape as a .utoc,
so .pak-only mods take part in the report. Only the footer and the index are read, never file data.

A .pak mod has no content hashes in its index (UE5 encodes the entries without them), so it can say which game
files a mod replaces and which mods collide, which is all the report needs from a mod."""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .cityhash import chunk_id, package_of

MAGIC = 0x5A6F12E1
PATH_HASH_INDEX = 10  # v10+: the file names live in a separate full directory index


class PakError(ValueError):
    pass


class _Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.d, self.p = data, pos

    def take(self, fmt: str):
        v = struct.unpack_from("<" + fmt, self.d, self.p)
        self.p += struct.calcsize("<" + fmt)
        return v[0] if len(v) == 1 else v

    def fstring(self) -> str:
        n = self.take("i")
        if n == 0:
            return ""
        if n > 0:
            raw, self.p = self.d[self.p:self.p + n], self.p + n
            return raw.split(b"\0", 1)[0].decode("utf-8", "replace")
        raw, self.p = self.d[self.p:self.p - 2 * n], self.p - 2 * n
        return raw.decode("utf-16-le", "replace").split("\0", 1)[0]


@dataclass
class PakToc:
    """What the report needs from a mod: its path, its chunks and readable names. Same interface as utoc.Toc."""
    path: Path
    version: int
    encrypted: bool
    files: list[str] = field(default_factory=list)  # paths inside the pak, mount point applied
    _ids: dict[bytes, str] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        for f in self.files:
            pkg = package_of(f)
            if pkg:  # a package: matches the game's IoStore chunk of the same package
                self._ids[chunk_id(pkg)] = f
            elif not f.lower().endswith((".uexp", ".ubulk", ".uptnl")):  # parts of a package count with it
                self._ids[b"pak:" + hashlib.sha1(f.lower().encode()).digest()[:8]] = f  # .ini, .locres...: by path

    def chunks(self, skip_own: bool = True) -> dict[bytes, bytes]:
        return {cid: b"" for cid in self._ids}

    def name_of(self, cid: bytes) -> str:
        return self._ids.get(cid, cid.hex())


def _footer(data: bytes) -> tuple[int, bool, int, int]:
    """(version, encrypted index, index offset, index size). The footer's length depends on the version, so look
    for the magic in the last few hundred bytes. The encrypted-index flag in front of it exists from version 4."""
    tail = data[-300:]
    i = tail.rfind(struct.pack("<I", MAGIC))
    if i < 1:
        raise PakError("not an Unreal .pak")
    version, offset, size = struct.unpack_from("<iqq", tail, i + 4)
    encrypted = version >= 4 and tail[i - 1] == 1
    return version, encrypted, offset, size


def read_pak(path: Path) -> PakToc:
    path = Path(path)
    with open(path, "rb") as f:
        f.seek(0, 2)
        length = f.tell()
        f.seek(max(0, length - 300))
        version, encrypted, offset, size = _footer(f.read())
        if not 3 <= version <= 12:  # 3: old tools still write it; 12: UE 5.6
            raise PakError(f"{path.name}: .pak version {version} isn't supported")
        if encrypted:
            return PakToc(path, version, True)  # the names need the game's AES key
        if offset < 0 or size < 0 or offset + size > length:
            raise PakError(f"{path.name}: the index points outside the file")
        f.seek(offset)
        index = f.read(size)
        if version < PATH_HASH_INDEX:
            return PakToc(path, version, False, _old_index(index, version))
        r = _Reader(index)
        mount = r.fstring()
        r.take("i")   # entries
        r.take("Q")   # path hash seed
        if r.take("I"):
            r.take("qq20s")  # path hash index: offset, size, hash
        if not r.take("I"):
            raise PakError(f"{path.name} has no full directory index")
        dir_offset, dir_size, _ = r.take("qq20s")
        f.seek(dir_offset)
        return PakToc(path, version, False, _directory_index(f.read(dir_size), mount))


def _join(mount: str, rel: str) -> str:
    return (mount + rel).replace("../../../", "").lstrip("/")


def _directory_index(data: bytes, mount: str) -> list[str]:
    r = _Reader(data)
    out = []
    for _ in range(r.take("i")):
        folder = r.fstring()
        for _ in range(r.take("i")):
            name = r.fstring()
            r.take("i")  # where the encoded entry is
            out.append(_join(mount, folder.lstrip("/") + name))
    return out


def _old_index(data: bytes, version: int) -> list[str]:
    """Versions 3 to 9: the file name sits in front of each full FPakEntry."""
    r = _Reader(data)
    mount = r.fstring()
    out = []
    for _ in range(r.take("i")):
        out.append(_join(mount, r.fstring()))
        r.take("qqqI20s")              # offset, size, uncompressed size, compression method, hash
        method = struct.unpack_from("<I", data, r.p - 24)[0]
        if method:
            blocks = r.take("i")       # not `r.p += 16 * r.take(...)`: that loses take's own move
            r.p += 16 * blocks         # compression blocks
        r.take("BI")                   # flags, compression block size
    return out
