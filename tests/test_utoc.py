import os
import struct
import tempfile
import unittest
from pathlib import Path

from pakwatch import utoc

GAME_PAKS = Path(os.environ.get("PAKWATCH_GAME_PAKS", r"C:\Programs\Steam\steamapps\common\PBZ\ProjectPBZ\Content\Paks"))


def fstring(s: str) -> bytes:
    b = s.encode() + b"\0"
    return struct.pack("<i", len(b)) + b


def chunk_id(n: int, kind: int) -> bytes:
    return struct.pack("<Q", n) + b"\0\0\0" + bytes([kind])


def build_toc(ids: list[bytes], hashes: list[bytes], files: dict[int, str], flags: int = utoc.INDEXED,
              seeds: int = 0, mount: str = "../../../Game/", offsets: bytes = b"", blocks: bytes = b"",
              method: str = "Oodle") -> bytes:
    """A version 8 .utoc in the layout UE writes: header, ids, offsets, seeds, compression blocks (one empty
    one by default), one method name, directory index, metas. Files are paths (any depth) under the mount point."""
    strings, file_entries = [], []
    none = 0xFFFFFFFF
    dirs = [[none, none, none, none]]  # root: name, first child, next sibling, first file
    children: dict[tuple[int, str], int] = {}

    def sid(s):
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    for index, p in files.items():
        *folders, name = p.split("/")
        d = 0
        for f in folders:
            if (d, f) not in children:
                dirs.append([sid(f), none, dirs[d][1], none])  # becomes the parent's first child
                dirs[d][1] = children[(d, f)] = len(dirs) - 1
            d = children[(d, f)]
        file_entries.append([sid(name), dirs[d][3], index])
        dirs[d][3] = len(file_entries) - 1
    index_buf = (fstring(mount) + struct.pack("<I", len(dirs)) + b"".join(struct.pack("<IIII", *d) for d in dirs)
                 + struct.pack("<I", len(file_entries)) + b"".join(struct.pack("<III", *f) for f in file_entries)
                 + struct.pack("<I", len(strings)) + b"".join(fstring(s) for s in strings))
    n = len(ids)
    blocks = blocks or b"\0" * 12
    header = utoc.HEADER.pack(utoc.MAGIC, utoc.IO_HASH, 0, 0, utoc.HEADER.size, n, len(blocks) // 12, 12, 1, 32, 65536,
                              len(index_buf), 1, 7, b"\0" * 16, flags, 0, 0, seeds, 2 ** 64 - 1, 0, 0)
    body = (b"".join(ids) + (offsets or b"\0" * 10 * n) + b"\0" * 4 * seeds + blocks + method.encode().ljust(32, b"\0")
            + index_buf + b"".join(h + b"\0\0\0\0" for h in hashes))
    return header + body


def build_container(folder: Path, name: str, chunks: dict[bytes, bytes], hashes: dict[bytes, bytes] | None = None,
                    compress: str = "", flags: int = utoc.INDEXED) -> Path:
    """name.utoc and name.ucas with real chunk data. Each chunk starts on a 64 KB block; compress="Zlib" or "Oodle"
    packs every block with method 1 (Oodle blocks are just raw bytes: there's no DLL to unpack them)."""
    import zlib
    ucas, offsets, blocks, at = b"", b"", b"", 0
    for data in chunks.values():
        offsets += at.to_bytes(5, "big") + len(data).to_bytes(5, "big")
        for i in range(0, max(len(data), 1), 65536):
            plain = data[i:i + 65536]
            packed = zlib.compress(plain) if compress == "Zlib" else plain
            blocks += len(ucas).to_bytes(5, "little") + len(packed).to_bytes(3, "little") + len(plain).to_bytes(3, "little")
            blocks += bytes([1 if compress else 0])
            ucas += packed
        at += -(-max(len(data), 1) // 65536) * 65536
    ids = list(chunks)
    hashes = hashes or {}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.ucas").write_bytes(ucas)
    path = folder / f"{name}.utoc"
    path.write_bytes(build_toc(ids, [hashes.get(c, b"h" * 20) for c in ids], {}, flags, offsets=offsets, blocks=blocks,
                               method=compress or "Oodle"))
    return path


def container_header(imports: dict[int, list[int]], version: int = 5) -> bytes:
    """FIoContainerHeader with its store entries; what follows them is left out (pakwatch stops reading there)."""
    member, size = (8, 24) if version < 3 else (0, 16)
    ids = list(imports)
    entries, arrays = bytearray(size * len(ids)), b""
    for k, pid in enumerate(ids):
        view = k * size + member
        rel = len(ids) * size + len(arrays) - view
        entries[view:view + 8] = struct.pack("<II", len(imports[pid]), rel if imports[pid] else 0)
        arrays += struct.pack(f"<{len(imports[pid])}Q", *imports[pid])
    head = struct.pack("<IIQ", utoc.HEADER_MAGIC, version, 1) + (struct.pack("<I", len(ids)) if version < 2 else b"")
    body = bytes(entries) + arrays
    return head + struct.pack(f"<i{len(ids)}Q", len(ids), *ids) + struct.pack("<i", len(body)) + body


def zen_package(imported_names: list[str]) -> bytes:
    """The start of a zen package header (UE 5.3+) with its imported package names."""
    batch = struct.pack("<IIQ", len(imported_names), sum(map(len, imported_names)), 0) + b"\0" * 8 * len(imported_names)
    batch += b"".join(struct.pack(">h", len(n)) for n in imported_names) + b"".join(n.encode() for n in imported_names)
    batch += b"\0" * 4 * len(imported_names)
    summary = bytearray(64)
    struct.pack_into("<I", summary, 4, 64 + len(batch))   # header size
    struct.pack_into("<i", summary, 48, 64)               # imported package names offset
    return bytes(summary) + batch + b"export data"


class TocTests(unittest.TestCase):
    def read(self, data: bytes) -> utoc.Toc:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.utoc"
            p.write_bytes(data)
            return utoc.read_toc(p)

    def test_header_is_144_bytes(self):
        self.assertEqual(utoc.HEADER.size, 144)

    def test_ids_hashes_and_names(self):
        ids = [chunk_id(1, 1), chunk_id(2, 2), chunk_id(3, 6)]
        hashes = [bytes([i]) * 20 for i in range(3)]
        toc = self.read(build_toc(ids, hashes, {0: "Weapons/Sword.uasset", 1: "Weapons/Sword.ubulk"}, seeds=3))
        self.assertEqual(toc.chunk_ids, ids)
        self.assertEqual(toc.hashes, hashes)
        self.assertEqual(toc.names[0], "../../../Game/Weapons/Sword.uasset")
        self.assertEqual(set(toc.chunks()), set(ids[:2]))  # the container header chunk (type 6) is the container's own
        self.assertEqual(toc.name_of(ids[1]), "../../../Game/Weapons/Sword.ubulk")

    def test_encrypted_index_keeps_hashes(self):
        ids = [chunk_id(5, 1)]
        toc = self.read(build_toc(ids, [b"\x07" * 20], {0: "A/b.uasset"}, flags=utoc.INDEXED | utoc.ENCRYPTED))
        self.assertTrue(toc.encrypted)
        self.assertEqual(toc.names, {})
        self.assertEqual(toc.hashes, [b"\x07" * 20])
        self.assertTrue(toc.name_of(ids[0]).startswith("package "))

    def test_rejects_other_files(self):
        with self.assertRaises(utoc.TocError):
            self.read(b"not a toc" * 30)

    def test_truncated(self):
        data = build_toc([chunk_id(1, 1)], [b"\1" * 20], {0: "A/b.uasset"})
        with self.assertRaises(utoc.TocError):
            self.read(data[:-10])

    def mod(self, compress="", version=5, flags=utoc.INDEXED) -> utoc.Toc:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        big = zen_package(["/Game/FX/NS_Trail"]) + b"x" * 70000  # spans two blocks
        chunks = {chunk_id(10, 1): big, chunk_id(11, 1): b"small",
                  chunk_id(99, 6): container_header({10: [1, 2], 11: []}, version)}
        return utoc.read_toc(build_container(Path(self.tmp.name), "mod_P", chunks, compress=compress, flags=flags))

    def test_imports_from_the_container_header(self):
        for compress in ("", "Zlib"):
            toc = self.mod(compress)
            self.assertEqual(utoc.read_chunk(toc, 1), b"small")
            self.assertEqual(len(utoc.read_chunk(toc, 0)), len(zen_package(["/Game/FX/NS_Trail"])) + 70000)
            self.assertEqual(utoc.imports(toc), {chunk_id(10, 1): [chunk_id(1, 1), chunk_id(2, 1)], chunk_id(11, 1): []})

    def test_older_header_layouts(self):
        for version in (1, 2, 3, 4):
            self.assertEqual(utoc.imports(self.mod(version=version))[chunk_id(10, 1)], [chunk_id(1, 1), chunk_id(2, 1)])
        with self.assertRaisesRegex(utoc.TocError, "newer"):
            utoc.imports(self.mod(version=6))

    def test_import_names_are_checked_by_hash(self):
        from pakwatch.cityhash import chunk_id as package
        self.assertEqual(utoc.import_names(self.mod()), {package("/Game/FX/NS_Trail"): "/Game/FX/NS_Trail"})

    def test_oodle_without_a_dll_and_encrypted_containers(self):
        with self.assertRaisesRegex(utoc.TocError, "Oodle"):
            utoc.imports(self.mod("Oodle"), oodle_dirs=(Path(self.tmp.name),))
        with self.assertRaisesRegex(utoc.TocError, "encrypted"):
            utoc.imports(self.mod(flags=utoc.INDEXED | utoc.ENCRYPTED))

    def test_oodle_loads_a_copy_so_steam_can_replace_the_games_dll(self):
        from unittest import mock
        from pakwatch import scan
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        game, store = Path(tmp.name) / "Win64", Path(tmp.name) / "store"
        game.mkdir()
        (game / "oo2core_9_win64.dll").write_bytes(b"MZ oodle")
        loaded = []

        def cdll(path):
            loaded.append(Path(path))
            return mock.Mock(OodleLZ_Decompress=mock.Mock(return_value=4))
        with mock.patch.object(scan, "store_root", return_value=store), mock.patch.object(utoc.ctypes, "CDLL", cdll):
            self.assertEqual(utoc._oodle_decompress(b"packed", 4, (game,)), b"\0" * 4)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].parent, store / "oodle")
        self.assertEqual(loaded[0].read_bytes(), b"MZ oodle")

    @unittest.skipUnless(GAME_PAKS.is_dir(), "no installed game to read")
    def test_real_containers(self):
        tocs = [utoc.read_toc(p) for p in sorted(GAME_PAKS.glob("*.utoc"))]
        self.assertTrue(tocs)
        self.assertTrue(all(len(t.chunk_ids) == len(t.hashes) for t in tocs))


if __name__ == "__main__":
    unittest.main()
