import os
import tempfile
import time
import unittest
from pathlib import Path

from pakwatch import scan
from tests.test_utoc import build_toc, chunk_id

SWORD, SHIELD, BOW, NEW = chunk_id(1, 1), chunk_id(2, 1), chunk_id(3, 1), chunk_id(9, 1)


def write(path: Path, files: dict[bytes, bytes], mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = list(files)
    path.write_bytes(build_toc(ids, [files[i] for i in ids], {}))
    os.utime(path, (mtime, mtime))


class PatchFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.paks, self.store = root / "Paks", root / "store"
        self.t0 = time.time() - 1000
        write(self.paks / "Game-Windows.utoc", {SWORD: b"a" * 20, SHIELD: b"b" * 20, BOW: b"c" * 20}, self.t0)
        write(self.paks / "~mods" / "zzz_Swords_P.utoc", {SWORD: b"m" * 20, NEW: b"n" * 20}, self.t0 + 10)
        write(self.paks / "~mods" / "zzz_Shields_P.utoc", {SHIELD: b"s" * 20}, self.t0 + 10)

    def tearDown(self):
        self.tmp.cleanup()

    def status(self, report):
        return {m.toc.path.name: m.status for m in report.mods}

    def test_first_run_takes_a_snapshot(self):
        r = scan.run(self.paks, self.store)
        self.assertFalse(r.patched)
        self.assertEqual(r.game_files, 3)
        self.assertEqual(self.status(r), {"zzz_Shields_P.utoc": "ok", "zzz_Swords_P.utoc": "ok"})
        self.assertEqual(len(list(self.store.glob("*.snap"))), 1)

    def test_patch_is_reported_until_the_next_one(self):
        scan.run(self.paks, self.store)
        write(self.paks / "Game-Windows.utoc", {SWORD: b"A" * 20, SHIELD: b"b" * 20}, self.t0 + 100)  # sword changed, bow gone
        for _ in range(2):  # the second run still compares with the version before the patch
            r = scan.run(self.paks, self.store)
            self.assertTrue(r.patched)
            swords = next(m for m in r.mods if m.toc.path.name == "zzz_Swords_P.utoc")
            self.assertEqual(swords.status, "patch touched")
            self.assertEqual((swords.changed, swords.added), ([SWORD], 1))
            self.assertEqual(self.status(r)["zzz_Shields_P.utoc"], "ok")
        self.assertEqual(len(list(self.store.glob("*.snap"))), 2)

    def test_mod_updated_after_the_patch(self):
        scan.run(self.paks, self.store)
        write(self.paks / "Game-Windows.utoc", {SWORD: b"A" * 20, SHIELD: b"b" * 20}, self.t0 + 100)
        os.utime(self.paks / "~mods" / "zzz_Swords_P.utoc", (self.t0 + 200, self.t0 + 200))
        self.assertEqual(self.status(scan.run(self.paks, self.store))["zzz_Swords_P.utoc"], "updated after patch")

    def test_two_mods_replacing_one_file(self):
        write(self.paks / "~mods" / "zzz_MoreSwords_P.utoc", {SWORD: b"x" * 20}, self.t0 + 10)
        r = scan.run(self.paks, self.store)
        self.assertEqual(list(r.conflicts), [SWORD])
        self.assertEqual(sorted(t.path.name for t in r.conflicts[SWORD]), ["zzz_MoreSwords_P.utoc", "zzz_Swords_P.utoc"])

    def test_snapshot_round_trip(self):
        snap = scan.Snapshot("abc", "2026-11-04T10:00:00Z", {SWORD: b"a" * 20, BOW: b"c" * 20})
        self.assertEqual(scan.Snapshot.load(snap.save(self.store)).chunks, snap.chunks)


if __name__ == "__main__":
    unittest.main()
