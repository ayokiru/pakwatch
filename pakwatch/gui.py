"""The pakwatch window: a page in the default browser, served from 127.0.0.1 by the standard library only.

Every API call must carry the random token from the page's URL and a Host header naming this server, so other
pages open in the browser can't use it (that also covers DNS rebinding). The server stops a little while after the
last open tab stops pinging it."""
from __future__ import annotations

import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import scan, steam
from .__main__ import short

PAGE = Path(__file__).with_name("web") / "index.html"
IDLE_SECONDS = 30


def report_json(r: scan.Report, paks: Path) -> dict:
    mods = []
    for m in r.mods:
        touched = [{"path": short(m.toc, c), "what": "changed"} for c in m.changed] + \
                  [{"path": short(m.toc, c), "what": "removed"} for c in m.removed]
        mods.append({"name": m.toc.path.stem, "where": m.toc.path.parent.name, "status": m.status, "replaced": len(m.replaced),
                     "added": m.added, "touched": touched, "files": sorted(short(m.toc, c) for c in m.replaced)})
    order = {"patch touched": 0, "updated after patch": 1, "ok": 2, "adds only": 3}
    mods.sort(key=lambda x: (order[x["status"]], x["name"].lower()))
    conflicts = sorted(({"path": short(tocs[0], cid), "mods": [t.path.stem for t in tocs]}
                        for cid, tocs in r.conflicts.items()), key=lambda c: c["path"])
    return {"paks": str(paks), "game_files": r.game_files, "patched": r.patched,
            "snapshot": r.snapshot.taken if r.snapshot else None, "since": r.since, "first": r.first, "update": {"changed": r.files_changed, "added": r.files_added, "removed": r.files_removed,
                                          "build_before": r.build_before, "build": r.build}, "mods": mods, "conflicts": conflicts}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.token = secrets.token_urlsafe(24)
        self.hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}
        self.last_ping = time.monotonic()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/#t={self.token}"


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, *args):  # quiet console
        pass

    def send(self, code: int, body: bytes, kind: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def fail(self, code: int, message: str) -> None:
        self.send(code, json.dumps({"error": message}).encode())

    def do_GET(self):
        if self.headers.get("Host") not in self.server.hosts:
            return self.fail(403, "wrong host")
        url = urlparse(self.path)
        if url.path == "/":
            return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if not url.path.startswith("/api/"):
            return self.fail(404, "not found")
        if not secrets.compare_digest(self.headers.get("X-Pakwatch-Token", ""), self.server.token):
            return self.fail(403, "bad token")
        self.server.last_ping = time.monotonic()
        query = parse_qs(url.query)
        try:
            if url.path == "/api/ping":
                return self.send(200, b"{}")
            if url.path == "/api/games":
                games = [{"name": g.name, "folder": str(g.folder), "paks": str(g.paks), "mods": g.mods} for g in steam.games()]
                return self.send(200, json.dumps(games).encode())
            if url.path == "/api/scan":
                paks = scan.find_paks(Path(query.get("folder", [""])[0]))
                return self.send(200, json.dumps(report_json(scan.run(paks), paks)).encode())
        except (FileNotFoundError, ValueError, OSError) as e:
            return self.fail(400, str(e))
        self.fail(404, "not found")


def run(open_browser: bool = True) -> None:
    server = Server()

    def watchdog():
        while time.monotonic() - server.last_ping < IDLE_SECONDS:
            time.sleep(2)
        server.shutdown()

    threading.Thread(target=watchdog, daemon=True).start()
    print(f"pakwatch is open in your browser. If it didn't open, go to {server.url}")
    if open_browser:
        webbrowser.open(server.url)
    server.serve_forever()
