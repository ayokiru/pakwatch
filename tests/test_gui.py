import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from pakwatch import gui, scan
from tests.test_scan import SWORD, NEW, write


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.game = root / "Game"
        paks = self.game / "Proj" / "Content" / "Paks"
        write(paks / "Game-Windows.utoc", {SWORD: b"a" * 20}, time.time() - 100)
        write(paks / "~mods" / "zzz_Mine_P.utoc", {SWORD: b"m" * 20, NEW: b"n" * 20}, time.time() - 50)
        self.store = mock.patch.object(scan, "store_dir", return_value=root / "store")
        self.store.start()
        self.server = gui.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.store.stop()
        self.tmp.cleanup()

    def get(self, path, token=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.server.server_port}"}
        if token is not None:
            headers["X-Pakwatch-Token"] = token
        c.request("GET", path, headers=headers)
        r = c.getresponse()
        return r.status, r.read()

    def test_page_is_served(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"pakwatch", body)

    def test_api_needs_the_token(self):
        self.assertEqual(self.get("/api/ping")[0], 403)
        self.assertEqual(self.get("/api/ping", token="wrong")[0], 403)
        self.assertEqual(self.get("/api/ping", token=self.server.token)[0], 200)

    def test_other_hosts_are_refused(self):  # DNS rebinding: a foreign name pointing at 127.0.0.1
        self.assertEqual(self.get("/api/ping", token=self.server.token, host="evil.example:80")[0], 403)
        self.assertEqual(self.get("/", host="evil.example")[0], 403)

    def test_scan_report(self):
        status, body = self.get("/api/scan?folder=" + str(self.game).replace("\\", "/"), token=self.server.token)
        self.assertEqual(status, 200)
        r = json.loads(body)
        self.assertEqual(r["game_files"], 1)
        self.assertEqual(r["mods"][0]["name"], "zzz_Mine_P")
        self.assertEqual((r["mods"][0]["replaced"], r["mods"][0]["added"], r["mods"][0]["where"]), (1, 1, "~mods"))

    def test_bad_folder_is_a_400(self):
        status, body = self.get("/api/scan?folder=C:/nowhere-at-all", token=self.server.token)
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))


if __name__ == "__main__":
    unittest.main()
