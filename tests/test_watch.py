import io
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from pakwatch import __main__ as cli, scan, steam, watch
from tests.test_scan import SHIELD, SWORD, write


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.apps = root / "steamapps"
        self.paks = self.apps / "common" / "Game" / "Proj" / "Content" / "Paks"
        self.t0 = time.time() - 1000
        write(self.paks / "Game-Windows.utoc", {SWORD: b"a" * 20, SHIELD: b"b" * 20}, self.t0)
        write(self.paks / "~mods" / "zzz_Swords_P.utoc", {SWORD: b"m" * 20}, self.t0 + 10)
        self.manifest("100")
        self.game = steam.Game("Game", self.apps / "common" / "Game", self.paks, 1)
        patcher = mock.patch.object(scan, "store_dir", return_value=root / "store")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.toasts = []

    def manifest(self, build: str, flags: str = "4"):
        (self.apps / "appmanifest_1.acf").write_text(
            f'"AppState"\n{{\n\t"name"\t\t"Game"\n\t"StateFlags"\t\t"{flags}"\n\t"installdir"\t\t"Game"\n\t"buildid"\t\t"{build}"\n}}\n')

    def look(self, state):
        return watch.check([self.game], state, notify=lambda t, b: self.toasts.append((t, b)))

    def test_announces_an_update_once(self):
        state = self.look({})
        self.assertEqual((list(state.values()), self.toasts), (["100"], []))  # first look: only remembered
        self.assertEqual(self.look(state), state)
        write(self.paks / "Game-Windows.utoc", {SWORD: b"A" * 20, SHIELD: b"b" * 20}, self.t0 + 100)
        self.manifest("101", flags="1026")  # Steam is still writing the update
        self.assertEqual((self.look(state), self.toasts), (state, []))
        self.manifest("101")
        state = self.look(state)
        self.assertEqual(self.toasts, [("Game updated", "1 mod needs a look. Open pakwatch for the details.")])
        self.look(state)
        self.assertEqual(len(self.toasts), 1)

    def test_summary(self):
        r = scan.run(self.paks)
        self.assertEqual(watch.summary(r), "Your 1 mod looks fine after the update.")
        with mock.patch.object(scan.ModReport, "status", new_callable=mock.PropertyMock, return_value="uses changed"):
            self.assertEqual(watch.summary(r), "1 mod uses changed game files. Open pakwatch for the details.")

    def test_toast_text_stays_out_of_the_script(self):
        calls = []
        watch.toast("Game's \"update\"", "<b>2</b> mods; $(rm)", run=lambda *a, **k: calls.append((a, k)))
        (cmd,), kw = calls[0]
        self.assertEqual(kw["env"]["PAKWATCH_TITLE"], "Game's \"update\"")
        self.assertEqual(kw["env"]["PAKWATCH_BODY"], "<b>2</b> mods; $(rm)")
        self.assertNotIn("$(rm)", " ".join(cmd))
        self.assertIn("ToastNotificationManager", cmd[-1])

    def test_install_and_uninstall(self):
        with mock.patch.dict(os.environ, {"APPDATA": self.tmp.name}):
            link = watch.startup_dir() / watch.SHORTCUT
            calls = []
            self.assertIn("Would create", watch.install(dry_run=True, run=lambda *a, **k: calls.append(k)))
            self.assertEqual(calls, [])
            self.assertIn("Created", watch.install(run=lambda *a, **k: calls.append(k)))
            self.assertEqual(calls[0]["env"]["PAKWATCH_LINK"], str(link))
            self.assertTrue(calls[0]["env"]["PAKWATCH_ARGS"].endswith("watch"))
            self.assertIn("wasn't set", watch.uninstall())
            link.parent.mkdir(parents=True)
            link.write_bytes(b"lnk")
            self.assertIn("Would remove", watch.uninstall(dry_run=True))
            self.assertTrue(link.exists())
            self.assertIn("Removed", watch.uninstall())
            self.assertFalse(link.exists())

    def test_command_line(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"APPDATA": self.tmp.name}), redirect_stdout(out):
            self.assertEqual(cli.main(["watch", "--install", "--dry-run"]), 0)
            self.assertFalse((watch.startup_dir() / watch.SHORTCUT).exists())
        self.assertIn("Would create", out.getvalue())


if __name__ == "__main__":
    unittest.main()
