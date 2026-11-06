import os
import tempfile
import time
import unittest
from pathlib import Path

from pakwatch import scan
from tests.test_utoc import build_container, build_toc, chunk_id, container_header, zen_package

SWORD, SHIELD, BOW, NEW = chunk_id(1, 1), chunk_id(2, 1), chunk_id(3, 1), chunk_id(9, 1)


def package_id_of(cid: bytes) -> int:
    return int.from_bytes(cid[:8], "little")


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
        self.assertTrue(r.first)
        self.assertEqual(r.game_files, 3)
        again = scan.run(self.paks, self.store)  # same game version: not a first run, and the date is kept
        self.assertEqual((again.first, again.patched, again.since), (False, False, r.since))
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

    def test_the_first_file_name_in_ascii_order_loads(self):  # capital letters sort before small ones
        import io
        from pakwatch import __main__ as cli, gui, markdown
        write(self.paks / "~mods" / "zzz_aSwords_P.utoc", {SWORD: b"x" * 20}, self.t0 + 10)
        write(self.paks / "~mods" / "zzz_ZSwords_P.utoc", {SWORD: b"y" * 20}, self.t0 + 10)
        r = scan.run(self.paks, self.store)
        self.assertEqual([t.path.stem for t in r.conflicts[SWORD]], ["zzz_Swords_P", "zzz_ZSwords_P", "zzz_aSwords_P"])
        out = io.StringIO()
        cli.show(r, out)
        self.assertIn("zzz_Swords_P, zzz_ZSwords_P, zzz_aSwords_P  (loads: zzz_Swords_P)\n", out.getvalue())
        j = gui.report_json(r, self.paks)
        self.assertEqual(j["conflicts"][0]["loads"], "zzz_Swords_P")
        self.assertIn("(loads: `zzz_Swords_P`)", markdown.render(j, "Game"))

    def test_cli_output_and_exit_code(self):
        import io
        from pakwatch import __main__ as cli
        scan.run(self.paks, self.store)
        write(self.paks / "Game-Windows.utoc", {SWORD: b"A" * 20, SHIELD: b"b" * 20}, self.t0 + 100)
        out = io.StringIO()
        code = cli.show(scan.run(self.paks, self.store), out)
        self.assertEqual(code, 1)
        self.assertIn("Needs a look\n! zzz_Swords_P  replaces 1 game file, adds 1\n    changed  package", out.getvalue())
        self.assertIn("The update changed 1 game file, removed 1.", out.getvalue())  # no "added 0"

    def test_mod_that_uses_a_changed_game_file(self):
        import io
        from pakwatch import __main__ as cli, gui, markdown
        from pakwatch.cityhash import chunk_id as package
        trail = package("/Game/FX/NS_Trail")
        write(self.paks / "Game-Windows.utoc", {SWORD: b"a" * 20, trail: b"t" * 20}, self.t0)
        mine = chunk_id(50, 1)
        build_container(self.paks / "~mods", "zzz_Trails_P", {mine: zen_package(["/Game/FX/NS_Trail"]),
                                                              chunk_id(51, 6): container_header({50: [package_id_of(trail)]})})
        os.utime(self.paks / "~mods" / "zzz_Trails_P.utoc", (self.t0 + 10, self.t0 + 10))
        self.assertEqual(self.status(scan.run(self.paks, self.store))["zzz_Trails_P.utoc"], "adds only")
        write(self.paks / "Game-Windows.utoc", {SWORD: b"a" * 20, trail: b"T" * 20}, self.t0 + 100)
        r = scan.run(self.paks, self.store)
        trails = next(m for m in r.mods if m.toc.path.stem == "zzz_Trails_P")
        self.assertEqual((trails.status, trails.uses_changed), ("uses changed", [trail]))
        out = io.StringIO()
        self.assertEqual(cli.show(r, out), 1)
        self.assertIn("Uses changed game files\n! zzz_Trails_P  adds 1\n    uses changed  /Game/FX/NS_Trail\n", out.getvalue())
        j = gui.report_json(r, self.paks)
        self.assertEqual(j["mods"][0]["uses"], [{"path": "/Game/FX/NS_Trail", "what": "changed"}])
        self.assertIn("**Uses changed game files**\n- `zzz_Trails_P`: its own files use a game file the update changed\n"
                      "  - changed `/Game/FX/NS_Trail`", markdown.render(j | {"name": "Game"}, "Game"))

    def test_imports_not_readable(self):
        import io
        from pakwatch import __main__ as cli
        build_container(self.paks / "~mods", "zzz_Packed_P", {chunk_id(50, 1): b"x", chunk_id(51, 6): b"y"}, compress="Oodle")
        scan.run(self.paks, self.store)
        write(self.paks / "Game-Windows.utoc", {SWORD: b"A" * 20, SHIELD: b"b" * 20, BOW: b"c" * 20}, self.t0 + 100)
        out = io.StringIO()
        cli.show(scan.run(self.paks, self.store), out)
        self.assertIn("zzz_Packed_P  adds 1\n    imports not readable: it is compressed with Oodle", out.getvalue())

    def test_find_paks(self):
        from pakwatch.scan import find_paks
        game = Path(self.tmp.name) / "Game"
        write(game / "Proj" / "Content" / "Paks" / "a.utoc", {SWORD: b"a" * 20}, self.t0)
        self.assertEqual(find_paks(game), game / "Proj" / "Content" / "Paks")
        with self.assertRaises(FileNotFoundError):
            find_paks(Path(self.tmp.name) / "store")

    def test_update_totals(self):
        scan.run(self.paks, self.store)
        write(self.paks / "Game-Windows.utoc", {SWORD: b"A" * 20, SHIELD: b"b" * 20, NEW: b"z" * 20}, self.t0 + 100)
        r = scan.run(self.paks, self.store)
        self.assertEqual((r.files_changed, r.files_added, r.files_removed), (1, 1, 1))  # sword, the new file, the bow

    def test_snapshot_round_trip(self):
        snap = scan.Snapshot("abc", "2026-11-04T10:00:00Z", {SWORD: b"a" * 20, BOW: b"c" * 20}, "26266538")
        back = scan.Snapshot.load(snap.save(self.store))
        self.assertEqual((back.chunks, back.build), (snap.chunks, "26266538"))

    def test_snapshot_without_build_id(self):  # written by pakwatch 0.1
        import gzip
        path = self.store / "old.snap"
        self.store.mkdir(parents=True)
        path.write_bytes(gzip.compress(b"pakwatch1 abc 2026-11-04T10:00:00Z\n" + SWORD + b"a" * 20))
        old = scan.Snapshot.load(path)
        self.assertEqual((old.build, old.chunks), ("", {SWORD: b"a" * 20}))


if __name__ == "__main__":
    unittest.main()
