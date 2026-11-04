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
              seeds: int = 0) -> bytes:
    """A version 8 .utoc in the layout UE writes: header, ids, offsets, seeds, one compression block,
    one method name, directory index, metas. Files are 'dir/name' pairs under the mount point."""
    strings, dirs, file_entries = [], [], []

    def sid(s):
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    none = 0xFFFFFFFF
    folders = sorted({p.split("/")[0] for p in files.values()})
    dirs.append([none, 1 if folders else none, none, none])  # root
    for i, folder in enumerate(folders):
        dirs.append([sid(folder), none, len(dirs) + 1 if i < len(folders) - 1 else none, none])
    for index, p in files.items():
        folder, name = p.split("/")
        d = dirs[1 + folders.index(folder)]
        file_entries.append([sid(name), d[3], index])
        d[3] = len(file_entries) - 1
    index_buf = (fstring("../../../Game/") + struct.pack("<I", len(dirs)) + b"".join(struct.pack("<IIII", *d) for d in dirs)
                 + struct.pack("<I", len(file_entries)) + b"".join(struct.pack("<III", *f) for f in file_entries)
                 + struct.pack("<I", len(strings)) + b"".join(fstring(s) for s in strings))
    n = len(ids)
    header = utoc.HEADER.pack(utoc.MAGIC, utoc.IO_HASH, 0, 0, utoc.HEADER.size, n, 1, 12, 1, 32, 65536, len(index_buf), 1,
                              7, b"\0" * 16, flags, 0, 0, seeds, 0, 0, 0)
    body = (b"".join(ids) + b"\0" * 10 * n + b"\0" * 4 * seeds + b"\0" * 12 + b"Oodle".ljust(32, b"\0")
            + index_buf + b"".join(h + b"\0\0\0\0" for h in hashes))
    return header + body


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

    @unittest.skipUnless(GAME_PAKS.is_dir(), "no installed game to read")
    def test_real_containers(self):
        tocs = [utoc.read_toc(p) for p in sorted(GAME_PAKS.glob("*.utoc"))]
        self.assertTrue(tocs)
        self.assertTrue(all(len(t.chunk_ids) == len(t.hashes) for t in tocs))


if __name__ == "__main__":
    unittest.main()
