"""Reads the tables of an Unreal Engine IoStore .utoc: which chunks a container holds, their content hashes and
(when the index isn't encrypted) their file names. Chunk data in the .ucas is never touched, so this needs no AES
key and takes milliseconds even for large containers. Layout follows UE's FIoStoreTocHeader (as read by retoc)."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"-==--==--==--==-"
HEADER = struct.Struct("<16sBBHIIIIIIIIIQ16sBBHIQII40x")  # 144 bytes
# EIoStoreTocVersion
PERFECT_HASH, PERFECT_HASH_WITH_OVERFLOW, IO_HASH = 4, 5, 8
# EIoContainerFlags
ENCRYPTED, SIGNED, INDEXED = 0x02, 0x04, 0x08
# EIoChunkType (UE5): chunks every container has of its own, so they never mean two mods collide
OWN_CHUNK_TYPES = {5, 6, 8, 9}  # ScriptObjects, ContainerHeader, ShaderCodeLibrary, ShaderCode
CHUNK_TYPES = {1: "package", 2: "bulk data", 3: "optional bulk data", 4: "memory-mapped bulk data", 7: "file",
               10: "package store entry", 13: "package resource"}


class TocError(ValueError):
    pass


@dataclass
class Toc:
    path: Path
    version: int
    encrypted: bool
    chunk_ids: list[bytes]                         # 12 bytes each
    hashes: list[bytes]                            # content hash per chunk (20 or 32 bytes)
    names: dict[int, str] = field(default_factory=dict)  # chunk index -> file path, empty if the index is encrypted

    def chunks(self, skip_own: bool = True) -> dict[bytes, bytes]:
        """chunk id -> content hash, without the chunks that belong to the container itself."""
        return {cid: h for cid, h in zip(self.chunk_ids, self.hashes) if not (skip_own and cid[11] in OWN_CHUNK_TYPES)}

    def name_of(self, chunk_id: bytes) -> str:
        """The file path of a chunk, or a readable stand-in when the container has no readable index."""
        try:
            i = self.chunk_ids.index(chunk_id)
        except ValueError:
            return chunk_id.hex()
        return self.names.get(i) or f"{CHUNK_TYPES.get(chunk_id[11], 'chunk')} {chunk_id[:8][::-1].hex()}"


def _fstring(buf: memoryview, pos: int) -> tuple[str, int]:
    (n,) = struct.unpack_from("<i", buf, pos)
    pos += 4
    if n == 0:
        return "", pos
    if n > 0:
        return bytes(buf[pos:pos + n]).split(b"\0", 1)[0].decode("utf-8", "replace"), pos + n
    return bytes(buf[pos:pos - 2 * n]).decode("utf-16-le", "replace").split("\0", 1)[0], pos - 2 * n


def _directory_index(buf: memoryview) -> dict[int, str]:
    """FIoDirectoryIndexResource -> {chunk index: path}. 0xFFFFFFFF marks 'none' in every link."""
    mount, pos = _fstring(buf, 0)
    (n,) = struct.unpack_from("<I", buf, pos)
    dirs = list(struct.iter_unpack("<IIII", buf[pos + 4:pos + 4 + 16 * n]))  # name, first child, next sibling, first file
    pos += 4 + 16 * n
    (n,) = struct.unpack_from("<I", buf, pos)
    files = list(struct.iter_unpack("<III", buf[pos + 4:pos + 4 + 12 * n]))  # name, next file, chunk index
    pos += 4 + 12 * n
    (n,) = struct.unpack_from("<I", buf, pos)
    pos += 4
    strings = []
    for _ in range(n):
        s, pos = _fstring(buf, pos)
        strings.append(s)
    none, out = 0xFFFFFFFF, {}
    stack = [(0, mount.rstrip("/"))] if dirs else []
    while stack:  # iterative walk; deep trees must not hit the recursion limit
        d, prefix = stack.pop()
        name, child, _, f = dirs[d]
        here = f"{prefix}/{strings[name]}" if name != none else prefix
        while f != none:
            fname, f_next, index = files[f]
            out[index] = f"{here}/{strings[fname]}"
            f = f_next
        while child != none:
            stack.append((child, here))
            child = dirs[child][2]
    return out


def read_toc(path: Path) -> Toc:
    data = memoryview(Path(path).read_bytes())
    if len(data) < HEADER.size or bytes(data[:16]) != MAGIC:
        raise TocError(f"{Path(path).name} is not an IoStore .utoc")
    (_, version, _, _, header_size, entries, blocks, block_size, methods, method_len, _, dir_size, _,
     _, _, flags, _, _, seeds, _, no_hash, _) = HEADER.unpack_from(data)
    if version > IO_HASH:
        raise TocError(f"{Path(path).name}: TOC version {version} is newer than pakwatch knows")
    pos = header_size
    chunk_ids = [bytes(data[pos + 12 * i:pos + 12 * i + 12]) for i in range(entries)]
    pos += 12 * entries + 10 * entries                                   # ids, then offset+length (5+5 bytes)
    pos += 4 * (seeds if version >= PERFECT_HASH else 0)
    pos += 4 * (no_hash if version >= PERFECT_HASH_WITH_OVERFLOW else 0)
    pos += (block_size or 12) * blocks + methods * method_len
    if flags & SIGNED:
        (sig,) = struct.unpack_from("<I", data, pos)
        pos += 4 + 2 * sig + 20 * blocks
    index = data[pos:pos + dir_size]
    pos += dir_size
    meta = 24 if version >= IO_HASH else 33                              # 20-byte hash + flags + pad, or 32 + flags
    hash_len = 20 if version >= IO_HASH else 32
    hashes = [bytes(data[pos + meta * i:pos + meta * i + hash_len]) for i in range(entries)]
    if pos + meta * entries > len(data):
        raise TocError(f"{Path(path).name}: the TOC is shorter than its header says")
    encrypted = bool(flags & ENCRYPTED)
    names = {}
    if dir_size and not encrypted:
        try:
            names = _directory_index(index)
        except (struct.error, IndexError):
            names = {}  # a damaged index only costs the names, not the hashes
    return Toc(Path(path), version, encrypted, chunk_ids, hashes, names)
