import io
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path

from pakwatch import __main__ as cli, gui, markdown, scan, ue4ss
from tests.test_scan import SWORD, write


def version_dll(major: int, minor: int, patch: int) -> bytes:
    """Enough of a PE version resource: the VS_VERSION_INFO key, then VS_FIXEDFILEINFO."""
    fixed = ue4ss.FIXED_FILE_INFO + struct.pack("<IIIII", 0x10000, (major << 16) | minor, patch << 16, 0, 0)
    return b"MZ" + b"\0" * 300 + "VS_VERSION_INFO".encode("utf-16-le") + b"\0\0\0\0" + fixed + b"\0" * 40


class Ue4ssTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.game, self.store = root / "Game", root / "store"
        self.paks = self.game / "Proj" / "Content" / "Paks"
        self.win64 = self.game / "Proj" / "Binaries" / "Win64"
        self.t0 = time.time() - 1000
        write(self.paks / "Game-Windows.utoc", {SWORD: b"a" * 20}, self.t0)
        write(self.paks / "~mods" / "zzz_Mine_P.utoc", {SWORD: b"m" * 20}, self.t0 + 10)
        self.win64.mkdir(parents=True)
        self.exe = self.win64 / "Proj-Win64-Shipping.exe"
        self.exe.write_bytes(b"MZ" + b"\0" * 1000)
        os.utime(self.exe, (self.t0, self.t0))

    def install_ue4ss(self, layout: str = "ue4ss"):
        base = self.win64 / "ue4ss" if layout == "ue4ss" else self.win64
        mods = base / "Mods"
        for name in ("BPModLoaderMod", "MyLuaMod", "OldMod", "shared"):
            (mods / name / "Scripts").mkdir(parents=True)
        (mods / "OldMod" / "enabled.txt").write_text("")
        (mods / "mods.txt").write_text("; built-in\nBPModLoaderMod : 1\nMyLuaMod : 0\nKeybinds : 1\n")
        (base / "UE4SS.dll").write_bytes(version_dll(3, 0, 1))
        if layout == "ue4ss":
            (self.win64 / "dwmapi.dll").write_bytes(b"MZ")

    def test_nothing_without_ue4ss(self):
        self.assertIsNone(ue4ss.find(self.paks))
        self.assertIsNone(scan.run(self.paks, self.store).ue4ss)

    def test_both_layouts(self):
        for layout in ("ue4ss", "beside the exe"):
            with self.subTest(layout=layout):
                self.setUp()
                self.install_ue4ss(layout)
                found = ue4ss.find(self.paks)
                self.assertEqual(found["version"], "3.0.1")
                self.assertEqual(found["mods"], [{"name": "BPModLoaderMod", "on": True}, {"name": "MyLuaMod", "on": False},
                                                 {"name": "OldMod", "on": True}])

    def test_settings_file_alone_marks_it(self):
        (self.win64 / "ue4ss").mkdir()
        (self.win64 / "ue4ss" / "UE4SS-settings.ini").write_text("[General]\n")
        self.assertEqual(ue4ss.find(self.paks), {"folder": self.win64 / "ue4ss", "version": "", "mods": []})

    def test_largest_exe_when_there_is_no_shipping_exe(self):
        self.exe.unlink()
        (self.game / "launcher").mkdir()
        (self.game / "launcher" / "Small.exe").write_bytes(b"MZ")
        (self.game / "platform" / "steam").mkdir(parents=True)
        (self.game / "platform" / "steam" / "Game.exe").write_bytes(b"MZ" + b"\0" * 5000)
        self.assertEqual(ue4ss.game_exe(self.paks), self.game / "platform" / "steam" / "Game.exe")

    def test_warning_when_the_update_changed_the_exe(self):
        self.install_ue4ss()
        self.assertFalse(scan.run(self.paks, self.store).exe_changed)
        write(self.paks / "Game-Windows.utoc", {SWORD: b"A" * 20}, self.t0 + 100)
        self.exe.write_bytes(b"MZ" + b"\0" * 2000)
        r = scan.run(self.paks, self.store)
        self.assertTrue(r.exe_changed)
        out = io.StringIO()
        cli.show(r, out)
        self.assertIn("UE4SS 3.0.1, 3 script mods\n  on   BPModLoaderMod\n  off  MyLuaMod\n  on   OldMod\n! The game's exe changed",
                      out.getvalue())
        j = gui.report_json(r, self.paks)
        self.assertEqual((j["exe_changed"], j["ue4ss"]["version"]), (True, "3.0.1"))
        md = markdown.render(j, "Game")
        self.assertIn("**UE4SS 3.0.1 script mods**\n- `BPModLoaderMod`\n- `MyLuaMod` (off)", md)
        self.assertIn(cli.UE4SS_WARNING, md)
        self.assertNotIn(self.tmp.name, md)

    def test_no_warning_when_only_the_containers_changed(self):
        self.install_ue4ss()
        scan.run(self.paks, self.store)
        write(self.paks / "Game-Windows.utoc", {SWORD: b"A" * 20}, self.t0 + 100)
        self.assertFalse(scan.run(self.paks, self.store).exe_changed)

    def test_snapshot_keeps_the_exe(self):
        snap = scan.Snapshot("abc", "2026-11-04T10:00:00Z", {SWORD: b"a" * 20}, "", "1000:5")
        back = scan.Snapshot.load(snap.save(self.store))
        self.assertEqual((back.build, back.exe), ("", "1000:5"))


if __name__ == "__main__":
    unittest.main()
