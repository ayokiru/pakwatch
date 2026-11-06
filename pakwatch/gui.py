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

from . import markdown, mods, scan, steam
from .__main__ import short

PAGE = Path(__file__).with_name("web") / "index.html"
IDLE_SECONDS = 30


def report_json(r: scan.Report, paks: Path) -> dict:
    mods = []
    for m in r.mods:
        touched = [{"path": short(m.toc, c), "what": "changed"} for c in m.changed] + \
                  [{"path": short(m.toc, c), "what": "removed"} for c in m.removed]
        uses = [{"path": m.import_name(c), "what": "changed"} for c in m.uses_changed] + \
               [{"path": m.import_name(c), "what": "removed"} for c in m.uses_removed]
        mods.append({"name": m.toc.path.stem, "where": m.toc.path.parent.name, "status": m.status, "replaced": len(m.replaced),
                     "added": m.added, "touched": touched, "uses": uses, "files": sorted(short(m.toc, c) for c in m.replaced),
                     "imports_note": getattr(m.toc, "imports_note", "") if r.patched else ""})
    order = {"patch touched": 0, "uses changed": 1, "updated after patch": 2, "ok": 3, "adds only": 4}
    mods.sort(key=lambda x: (order[x["status"]], x["name"].lower()))
    conflicts = sorted(({"path": short(tocs[0], cid), "mods": [t.path.stem for t in tocs]}
                        for cid, tocs in r.conflicts.items()), key=lambda c: c["path"])
    return {"paks": str(paks), "game_files": r.game_files, "patched": r.patched,
            "snapshot": r.snapshot.taken if r.snapshot else None, "since": r.since, "first": r.first, "unreadable": [{"name": n, "why": w} for n, w in r.unreadable], "update": {"changed": r.files_changed, "added": r.files_added, "removed": r.files_removed,
                                          "build_before": r.build_before, "build": r.build}, "mods": mods, "conflicts": conflicts,
            "ue4ss": r.ue4ss and {"version": r.ue4ss["version"], "folder": str(r.ue4ss["folder"]), "mods": r.ue4ss["mods"]},
            "exe_changed": r.exe_changed}


def full_report(paks: Path) -> dict:
    """The report plus the game's name and the same report as Markdown, ready to share."""
    r = report_json(scan.run(paks), paks)
    r["name"] = steam.game_name(paks)
    r["markdown"] = markdown.render(r, r["name"])
    r["disabled"] = mods.turned_off(paks)
    return r


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
                return self.send(200, json.dumps(full_report(paks)).encode())
        except (FileNotFoundError, ValueError, OSError) as e:
            return self.fail(400, str(e))
        self.fail(404, "not found")


    def do_POST(self):
        """The only request that changes files: turn a mod off or on. Same host and token checks as GET."""
        if self.headers.get("Host") not in self.server.hosts:
            return self.fail(403, "wrong host")
        if not secrets.compare_digest(self.headers.get("X-Pakwatch-Token", ""), self.server.token):
            return self.fail(403, "bad token")
        url = urlparse(self.path)
        if url.path != "/api/mod":
            return self.fail(404, "not found")
        self.server.last_ping = time.monotonic()
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            paks = scan.find_paks(Path(query.get("folder", "")))
            action = {"off": mods.turn_off, "on": mods.turn_on}.get(query.get("action", ""))
            if action is None:
                return self.fail(400, "action must be off or on")
            action(paks, query.get("name", ""))
        except PermissionError:
            return self.fail(409, "The game is using this mod. Close the game and try again.")
        except (FileNotFoundError, FileExistsError, ValueError, OSError) as e:
            return self.fail(400, str(e))
        self.send(200, b"{}")


def run(open_browser: bool = True) -> None:
    server = Server()

    def watchdog():
        while time.monotonic() - server.last_ping < IDLE_SECONDS:
            time.sleep(2)
        server.shutdown()

    threading.Thread(target=watchdog, daemon=True).start()
    if open_browser:
        print(f"pakwatch is open in your browser. If it didn't open, go to {server.url}", flush=True)
        webbrowser.open(server.url)
    else:
        print(f"pakwatch is running at {server.url}", flush=True)
    print("It stops by itself shortly after you close the tab, or close this window to stop it now.", flush=True)
    server.serve_forever()
