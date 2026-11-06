"""Reads the tables of an Unreal Engine IoStore .utoc: which chunks a container holds, their content hashes and
(when the index isn't encrypted) their file names. That needs no AES key and takes milliseconds even for large
containers. Layout follows UE's FIoStoreTocHeader (as read by retoc).

For a mod, pakwatch also reads one small chunk from the .ucas: the container header, which lists the packages
each of the mod's packages imports."""
from __future__ import annotations

import ctypes
import struct
import zlib
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
PACKAGE, CONTAINER_HEADER = 1, 6
HEADER_MAGIC = 0x496F436E  # FIoContainerHeader from UE 5.0 on
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
    offsets: bytes = field(default=b"", repr=False)  # FIoOffsetAndLength per chunk, 10 bytes each, kept raw (fast)
    blocks: bytes = field(default=b"", repr=False)   # FIoStoreTocCompressedBlockEntry, 12 bytes each
    methods: list[str] = field(default_factory=list, repr=False)   # compression names; a block's method i is [i - 1]
    block_size: int = 65536
    partition_size: int = 0
    imports: set[bytes] | None = None              # packages the mod's packages import, once read (scan.run)
    imports_note: str = ""                         # why they couldn't be read

    def chunks(self, skip_own: bool = True) -> dict[bytes, bytes]:
        """chunk id -> content hash, without the chunks that belong to the container itself."""
        return {cid: h for cid, h in zip(self.chunk_ids, self.hashes) if not (skip_own and cid[11] in OWN_CHUNK_TYPES)}

    def name_of(self, chunk_id: bytes) -> str:
        """The file path of a chunk, or a readable stand-in when the container has no readable index."""
        try:
            i = self.chunk_ids.index(chunk_id)
        except ValueError:
            return chunk_id.hex()
        return self.names.get(i) or label(chunk_id)


def label(chunk_id: bytes) -> str:
    return f"{CHUNK_TYPES.get(chunk_id[11], 'chunk')} {chunk_id[:8][::-1].hex()}"


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
    (_, version, _, _, header_size, entries, blocks, block_size, methods, method_len, compression_block, dir_size, _,
     _, _, flags, _, _, seeds, partition_size, no_hash, _) = HEADER.unpack_from(data)
    if version > IO_HASH:
        raise TocError(f"{Path(path).name}: TOC version {version} is newer than pakwatch knows")
    pos = header_size
    chunk_ids = [bytes(data[pos + 12 * i:pos + 12 * i + 12]) for i in range(entries)]
    pos += 12 * entries
    offsets = bytes(data[pos:pos + 10 * entries])
    pos += 10 * entries
    pos += 4 * (seeds if version >= PERFECT_HASH else 0)
    pos += 4 * (no_hash if version >= PERFECT_HASH_WITH_OVERFLOW else 0)
    block_size = block_size or 12
    block_list = bytes(data[pos:pos + block_size * blocks]) if block_size == 12 else b""  # other sizes: no chunk reads
    pos += block_size * blocks
    method_names = [bytes(data[p:p + method_len]).split(b"\0", 1)[0].decode("ascii", "replace")
                    for p in range(pos, pos + methods * method_len, method_len)]
    pos += methods * method_len
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
    return Toc(Path(path), version, encrypted, chunk_ids, hashes, names, offsets, block_list, method_names,
               compression_block or 65536, partition_size)


# --- chunk data in the .ucas ------------------------------------------------------------------------------
_oodle: dict[tuple, object] = {}


def _private_copy(dll: Path) -> Path:
    """A copy of the DLL in pakwatch's folder. Windows locks a loaded DLL, and the watcher stays loaded for the whole
    session, so loading the game's own file would make a Steam update that replaces it fail."""
    from .scan import store_root, write_atomic  # scan imports this module
    st = dll.stat()
    copy = store_root() / "oodle" / f"{st.st_size}-{st.st_mtime_ns}-{dll.name}"  # a new game version, a new copy
    if not copy.is_file():
        copy.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(copy, dll.read_bytes())
    return copy


def _oodle_decompress(raw: bytes, size: int, dirs: tuple) -> bytes:
    """Oodle through the game's own oo2core DLL, if the game ships one. pakwatch doesn't carry Oodle itself."""
    if dirs not in _oodle:
        _oodle[dirs] = None
        for dll in (p for d in dirs for p in sorted(Path(d).glob("oo2core_*_win64.dll"))):
            try:
                fn = ctypes.CDLL(str(_private_copy(dll))).OodleLZ_Decompress
            except (OSError, AttributeError):  # can't copy, wrong bitness, not Windows, or not Oodle after all
                continue
            fn.restype = ctypes.c_ssize_t
            fn.argtypes = [ctypes.c_char_p, ctypes.c_ssize_t, ctypes.c_char_p, ctypes.c_ssize_t, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                           ctypes.c_ssize_t, ctypes.c_int]
            _oodle[dirs] = fn
            break
    fn = _oodle[dirs]
    if fn is None:
        raise TocError("it is compressed with Oodle, and the game has no Oodle DLL pakwatch could use")
    out = ctypes.create_string_buffer(size)
    if fn(raw, len(raw), out, size, 1, 0, 0, None, 0, None, None, None, 0, 3) != size:
        raise TocError("Oodle couldn't unpack it")
    return out.raw


def read_chunk(toc: Toc, index: int, limit: int | None = None, oodle_dirs: tuple = ()) -> bytes:
    """One chunk's data (or its first `limit` bytes), read block by block from the .ucas partitions."""
    if toc.encrypted:
        raise TocError("the container is encrypted")
    o = toc.offsets[10 * index:10 * index + 10]
    offset, size = int.from_bytes(o[:5], "big"), int.from_bytes(o[5:], "big")
    size = min(size, limit) if limit else size
    if not size:
        return b""
    first, last = offset // toc.block_size, (offset + size - 1) // toc.block_size
    out, files = bytearray(), {}
    try:
        for at in range(12 * first, 12 * last + 12, 12):
            b = toc.blocks[at:at + 12]
            if len(b) < 12:
                raise TocError("the chunk lies outside the container's block table")
            pos, packed, plain, method = (int.from_bytes(b[:5], "little"), int.from_bytes(b[5:8], "little"),
                                          int.from_bytes(b[8:11], "little"), b[11])
            part, pos = divmod(pos, toc.partition_size) if toc.partition_size else (0, pos)
            if part not in files:
                files[part] = open(toc.path.with_name(toc.path.stem + (f"_s{part}" if part else "") + ".ucas"), "rb")
            files[part].seek(pos)
            raw = files[part].read(plain if method == 0 else packed)
            name = (toc.methods[method - 1] if 0 < method <= len(toc.methods) else "").lower()
            if method == 0:
                out += raw
            elif name == "zlib":
                out += zlib.decompress(raw)
            elif name == "oodle":
                out += _oodle_decompress(raw, plain, oodle_dirs)
            else:
                raise TocError(f"it is compressed with {name or 'an unknown method'}, which pakwatch can't unpack")
    except zlib.error:
        raise TocError("a compressed block is damaged") from None
    finally:
        for f in files.values():
            f.close()
    start = offset - first * toc.block_size
    if len(out) < start + size:
        raise TocError("the .ucas is shorter than its .utoc says")
    return bytes(out[start:start + size])


def package_chunk(package_id: int) -> bytes:
    return struct.pack("<Q", package_id) + b"\0\0\0" + bytes([PACKAGE])


def imports(toc: Toc, oodle_dirs: tuple = ()) -> dict[bytes, list[bytes]]:
    """Package chunk id -> chunk ids of the packages it imports, from the store entries in the container header
    (FFilePackageStoreEntry; the layouts per version are the ones retoc's container_header.rs reads)."""
    index = next((i for i, c in enumerate(toc.chunk_ids) if c[11] == CONTAINER_HEADER), None)
    if index is None:
        return {}
    d = read_chunk(toc, index, oodle_dirs=oodle_dirs)
    try:
        if struct.unpack_from("<I", d)[0] == HEADER_MAGIC:
            version = struct.unpack_from("<I", d, 4)[0]
            if version > 5:
                raise TocError(f"its container header (version {version}) is newer than pakwatch knows")
            pos = 16 + (4 if version < 2 else 0)                     # magic, version, container id, package count
            member, size = (8, 24) if version < 3 else (0, 16)
        else:                                                       # UE 4.27: no magic
            pos = 12
            for _ in range(2):                                      # name batch and its hashes
                pos += 4 + struct.unpack_from("<i", d, pos)[0]
            member, size = 24, 32
        (n,) = struct.unpack_from("<i", d, pos)
        ids = struct.unpack_from(f"<{n}Q", d, pos + 4)
        pos += 4 + 8 * n
        (length,) = struct.unpack_from("<i", d, pos)
        entries = d[pos + 4:pos + 4 + length]
        out = {}
        for k, pid in enumerate(ids):
            at = k * size + member                                   # the array view; its offset counts from itself
            count, rel = struct.unpack_from("<II", entries, at)
            out[package_chunk(pid)] = [package_chunk(x) for x in struct.unpack_from(f"<{count}Q", entries, at + rel)]
        return out
    except struct.error:
        raise TocError("its container header has a layout pakwatch doesn't know") from None


def import_names(toc: Toc, oodle_dirs: tuple = ()) -> dict[bytes, str]:
    """Package chunk id -> package name, from the imported package names in each package header (UE 5.3 and later).
    A name only counts when its CityHash matches, so a header in another layout costs names, never wrong ones."""
    from .cityhash import package_id
    out = {}
    for i, c in enumerate(toc.chunk_ids):
        if c[11] != PACKAGE:
            continue
        try:
            head_size = struct.unpack_from("<I", read_chunk(toc, i, 8, oodle_dirs), 4)[0]
            head = read_chunk(toc, i, min(head_size, 1 << 24), oodle_dirs)
            for name in _name_batch(head, struct.unpack_from("<i", head, 48)[0]):
                out[package_chunk(package_id(name))] = name
        except (TocError, OSError, struct.error, UnicodeDecodeError):
            continue
    return out


def _name_batch(d: bytes, pos: int) -> list[str]:
    """FZenPackageImportedPackageNamesContainer: a name batch, then one FName number per name."""
    (n,) = struct.unpack_from("<I", d, pos)
    if not 0 < n < 100000:
        return []
    pos += 16 + 8 * n                                               # count, byte count, hash version, hashes
    lengths = struct.unpack_from(f">{n}h", d, pos)
    pos += 2 * n
    names = []
    for ln in lengths:
        if ln < 0:                                                  # UTF-16, length stored as count - 32768
            ln += 32768
            names.append(d[pos:pos + 2 * ln].decode("utf-16-le"))
            pos += 2 * ln
        else:
            names.append(d[pos:pos + ln].decode("utf-8"))
            pos += ln
    numbers = struct.unpack_from(f"<{n}i", d, pos)
    return [f"{s}_{k - 1}" if k else s for s, k in zip(names, numbers)]
