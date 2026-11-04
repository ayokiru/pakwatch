import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from pakwatch import mods, scan
from tests.test_scan import SWORD, NEW, write


class TurnOffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.paks = root / "Game" / "Proj" / "Content" / "Paks"
        write(self.paks / "Game-Windows.utoc", {SWORD: b"a" * 20}, time.time() - 100)
        self.mod = self.paks / "~mods" / "zzz_Mine_P.utoc"
        write(self.mod, {SWORD: b"m" * 20, NEW: b"n" * 20}, time.time() - 50)
        for ext in (".ucas", ".pak"):
            self.mod.with_suffix(ext).write_bytes(b"data")
        (self.paks / "~mods" / "zzz_Mine_P_s1.ucas").write_bytes(b"part")
        (self.paks / "~mods" / "zzz_Mine_Plus_P.pak").write_bytes(b"another mod")  # same prefix, must stay
        self.patch = mock.patch.object(scan, "store_dir", return_value=root / "store")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def names(self, folder):
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    def test_off_moves_every_file_of_the_mod_out_of_paks(self):
        mods.turn_off(self.paks, "zzz_mine_p")  # names match case-insensitively
        self.assertEqual(self.names(self.paks / "~mods"), ["zzz_Mine_Plus_P.pak"])
        away = mods.disabled_dir(self.paks) / "~mods"
        self.assertEqual(self.names(away), ["zzz_Mine_P.pak", "zzz_Mine_P.ucas", "zzz_Mine_P.utoc", "zzz_Mine_P_s1.ucas"])
        self.assertFalse(str(away).startswith(str(self.paks)))  # the game loads anything under Paks
        self.assertEqual(mods.turned_off(self.paks), [{"name": "zzz_Mine_P", "where": "~mods"}])
        self.assertEqual([m.toc.path.stem for m in scan.run(self.paks).mods], [])

    def test_on_puts_it_back(self):
        mods.turn_off(self.paks, "zzz_Mine_P")
        mods.turn_on(self.paks, "zzz_Mine_P")
        self.assertEqual(len(self.names(self.paks / "~mods")), 5)
        self.assertEqual(mods.turned_off(self.paks), [])

    def test_a_failed_move_is_rolled_back(self):
        real = shutil.move
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) == 3:
                raise PermissionError("in use")
            return real(src, dst)

        with mock.patch.object(shutil, "move", flaky), self.assertRaises(PermissionError):
            mods.turn_off(self.paks, "zzz_Mine_P")
        self.assertEqual(len(self.names(self.paks / "~mods")), 5)  # everything is where it was

    def test_never_overwrites(self):
        mods.turn_off(self.paks, "zzz_Mine_P")
        write(self.mod, {SWORD: b"m" * 20}, time.time())  # a new copy installed meanwhile
        with self.assertRaises(FileExistsError):
            mods.turn_on(self.paks, "zzz_Mine_P")

    def test_unknown_mod(self):
        with self.assertRaises(FileNotFoundError):
            mods.turn_off(self.paks, "nope")


if __name__ == "__main__":
    unittest.main()
