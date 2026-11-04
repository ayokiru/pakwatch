"""Runs a built pakwatch.exe as a stranger's PC would: downloaded (marked as from the internet), under a Cyrillic
path with spaces, empty user folders, no Python on PATH. Exercises the command line and the window's API on a demo
game it patches itself, and reads the real Steam games without changing them.

usage: python dev/clean_pc_test.py dist/pakwatch.exe"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_pak import build_pak  # noqa: E402
from tests.test_utoc import build_toc, chunk_id  # noqa: E402

EXE = Path(sys.argv[1]).resolve()
ROOT = Path(os.environ["USERPROFILE"]) / "Чистый ПК pakwatch"
BIN = ROOT / "Загрузки" / "pakwatch.exe"
LOCAL = ROOT / "Пользователь Иван" / "AppData" / "Local"
GAME = ROOT / "Игры" / "Demo Game"
PAKS = GAME / "Demo" / "Content" / "Paks"
SWORD, SHIELD = chunk_id(1, 1), chunk_id(2, 1)
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""), flush=True)


def utoc(path, files, names, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = list(files)
    path.write_bytes(build_toc(ids, [files[i] for i in ids], names))
    os.utime(path, (mtime, mtime))


ENV = {k: v for k, v in os.environ.items() if k.upper() not in ("PATH", "PYTHONPATH", "PYTHONHOME", "LOCALAPPDATA")}
ENV.update(PATH=r"C:\Windows\System32;C:\Windows", LOCALAPPDATA=str(LOCAL))


def run(*args):
    r = subprocess.run([str(BIN), *map(str, args)], env=ENV, cwd=str(ROOT), capture_output=True, timeout=300)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def main():
    shutil.rmtree(ROOT, ignore_errors=True)
    BIN.parent.mkdir(parents=True)
    LOCAL.mkdir(parents=True)
    shutil.copy(EXE, BIN)
    with open(str(BIN) + ":Zone.Identifier", "w") as ads:
        ads.write("[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://github.com/\r\n")
    t0 = time.time() - 1000
    utoc(PAKS / "Demo-Windows.utoc", {SWORD: b"a" * 20, SHIELD: b"b" * 20}, {}, t0)
    utoc(PAKS / "~mods" / "zzz_Swords_P.utoc", {SWORD: b"m" * 20}, {0: "Weapons/BP_Sword.uasset"}, t0 + 10)
    (PAKS / "~mods" / "zzz_Config_P.pak").write_bytes(build_pak(["Demo/Config/DefaultGame.ini"], 11))

    code, out, err = run("--version")
    check("--version", code == 0 and "pakwatch" in out, out.strip() or err.strip())
    code, out, err = run(GAME)
    check("first check of a game under a Cyrillic path", code == 0 and "First run" in out, out.strip()[:120] or err[-300:])
    utoc(PAKS / "Demo-Windows.utoc", {SWORD: b"A" * 20, SHIELD: b"b" * 20}, {}, t0 + 100)  # the "update"
    code, out, err = run(GAME)
    check("after the update: mod flagged, exit code 1", code == 1 and "patch touched" in out and "zzz_Swords_P" in out, out.strip()[:200])
    check(".pak mod read", "zzz_Config_P" in out, "")
    code, md, err = run(GAME, "--markdown")
    check("--markdown", "**Needs a look**" in md and "Demo Game" in md, md[:120])
    check("no local paths in the shared report", str(ROOT) not in md and "Пользователь" not in md, "")
    steam = Path(r"C:\Programs\Steam\steamapps\common\PBZ")
    if steam.is_dir():
        code, out, err = run(steam)
        check("a real game (read only)", code in (0, 1) and "game files" in out, out.strip()[:100] or err[-200:])

    proc = subprocess.Popen([str(BIN), "--no-browser"], env=ENV, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        line = proc.stdout.readline().decode("utf-8", "replace")
        m = re.search(r"http://127\.0\.0\.1:(\d+)/#t=(\S+)", line)
        check("window mode prints its address", bool(m), line.strip())
        if not m:
            return
        base, token = f"http://127.0.0.1:{m.group(1)}", m.group(2)

        def api(path, method="GET"):
            req = urllib.request.Request(base + path, method=method, headers={"X-Pakwatch-Token": token})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())

        page = urllib.request.urlopen(base + "/", timeout=30).read()
        check("page served from inside the exe", b"<title>pakwatch</title>" in page, f"{len(page)} bytes")
        games = api("/api/games")
        check("Steam games found", isinstance(games, list), ", ".join(g["name"] for g in games)[:120])
        folder = urllib.request.quote(str(GAME))
        r = api(f"/api/scan?folder={folder}")
        check("report over the API", r["patched"] and any(x["status"] == "patch touched" for x in r["mods"]), f"{len(r['mods'])} mods")
        api(f"/api/mod?folder={folder}&name=zzz_Swords_P&action=off", "POST")
        gone = not (PAKS / "~mods" / "zzz_Swords_P.utoc").exists() and (LOCAL / "pakwatch").exists()
        check("Turn Off moves the mod out of the game", gone, "")
        api(f"/api/mod?folder={folder}&name=zzz_Swords_P&action=on", "POST")
        check("Turn On puts it back", (PAKS / "~mods" / "zzz_Swords_P.utoc").exists(), "")
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if results and all(results) else 1)
