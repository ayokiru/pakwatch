"""pakwatch watch: check the Steam games with mods or UE4SS again whenever Steam finishes an update (the build id in the
app manifest changes), and say the result in a Windows notification. Opt in with `pakwatch watch --install`, which
puts a shortcut in the user's Startup folder; `--uninstall` removes it."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import scan, steam, ue4ss

INTERVAL = 600  # seconds between looks at the app manifests
SHORTCUT = "pakwatch watch.lnk"
POWERSHELL = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command"]
# Text arrives in environment variables, never inside the script, so a game or mod name can't break out of it.
TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$t = [Security.SecurityElement]::Escape($env:PAKWATCH_TITLE); $b = [Security.SecurityElement]::Escape($env:PAKWATCH_BODY)
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""
LINK = r"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PAKWATCH_LINK)
$s.TargetPath = $env:PAKWATCH_TARGET; $s.Arguments = $env:PAKWATCH_ARGS; $s.WindowStyle = 7
$s.Description = 'pakwatch: check mods after a Steam update'; $s.Save()
"""


def _hidden() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def toast(title: str, body: str, run=subprocess.run) -> None:
    run(POWERSHELL + [TOAST], env={**os.environ, "PAKWATCH_TITLE": title, "PAKWATCH_BODY": body},
        creationflags=_hidden(), capture_output=True, timeout=60)


def summary(report: scan.Report) -> str:
    """One or two sentences for the notification."""
    need = sum(m.status == "patch touched" for m in report.mods)
    uses = sum(m.status == "uses changed" for m in report.mods)
    parts = [f"{need} mod{'s need' if need != 1 else ' needs'} a look"] if need else []
    if uses:
        parts.append(f"{uses} mod{'s use' if uses != 1 else ' uses'} changed game files")
    n = len(report.mods)
    text = (" and ".join(parts) + ". Open pakwatch for the details." if parts
            else f"Your {n} mod{'s look' if n != 1 else ' looks'} fine after the update." if n else "")
    if report.exe_changed and report.ue4ss:
        text = (text + " " if text else "") + "The exe changed too, so check your UE4SS script mods."
    return text or "None of your mods are affected."


def watched() -> list[steam.Game]:
    """Steam games with pak mods or UE4SS."""
    return [g for g in steam.games() if g.mods or ue4ss.find(g.paks)]


def state_file() -> Path:
    return scan.store_root() / "watch.json"


def load_state(path: Path) -> dict:
    """The build ids of the last look; a missing or damaged file just means starting over."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def check(games: list[steam.Game], state: dict[str, dict], notify=toast) -> dict[str, dict]:
    """One look at every game: a game whose build id changed since the last look is checked, and announced when
    its containers changed too. A game seen for the first time is only remembered (pakwatch takes its first
    snapshot then). The state keeps each game's build id and the fingerprint of its containers."""
    state = dict(state)
    for g in games:
        try:
            fields = steam.manifest(g.paks)
            build, key = fields.get("buildid", ""), str(g.paks).lower()
            if not build or fields.get("StateFlags", "4") != "4":  # 4: fully installed, not halfway through an update
                continue
            last = state.get(key)
            last = last if isinstance(last, dict) else {"build": last}  # an older watch.json kept the build id alone
            if last["build"] == build:
                continue
            report = scan.run(g.paks)
            # a build that changed no container leaves the last update's report as it was: don't announce it again
            if key in state and report.patched and report.fingerprint != last.get("containers"):
                notify(f"{g.name} updated", summary(report))
        except Exception:  # a broken file or a hung notification must not stop the watcher; the next look retries
            continue
        state[key] = {"build": build, "containers": report.fingerprint}
    return state


def single_instance(lock: Path):
    """An open file holding a lock while this watcher runs, or None if another one already does."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def run(interval: int = INTERVAL, dry_run: bool = False) -> None:
    """Look every few minutes. A dry run looks once, prints instead of notifying and remembers nothing."""
    path = state_file()
    state = load_state(path)
    # a second logon or a manual start would otherwise give every notification twice
    lock = None if dry_run else single_instance(path.with_name("watch.lock"))
    if not dry_run and lock is None:
        print("pakwatch watch is already running.")
        return
    while True:
        if dry_run:
            games = watched()
            check(games, state, notify=lambda title, body: print(f"{title}: {body}"))
            print(f"Looked at {len(games)} Steam game{'s' if len(games) != 1 else ''} with mods or UE4SS.")
            return
        try:
            new = check(watched(), state)
            if new != state:
                path.parent.mkdir(parents=True, exist_ok=True)
                scan.write_atomic(path, json.dumps(new, indent=1).encode("utf-8"))
                state = new
        except Exception:  # Steam's files half written, a full disk: keep the state and look again later
            pass
        time.sleep(interval)


# --- start at logon ------------------------------------------------------------------------------------------
def startup_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def command() -> tuple[str, str]:
    """What the shortcut starts: pakwatch.exe itself, or pythonw (no console window) for a pip install."""
    if getattr(sys, "frozen", False):
        return sys.executable, "watch"
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    return str(windowless if windowless.is_file() else exe), "-m pakwatch watch"


def install(dry_run: bool = False, run=subprocess.run) -> str:
    link = startup_dir() / SHORTCUT
    target, args = command()
    if not dry_run:
        run(POWERSHELL + [LINK], env={**os.environ, "PAKWATCH_LINK": str(link), "PAKWATCH_TARGET": target,
                                      "PAKWATCH_ARGS": args}, creationflags=_hidden(), check=True, capture_output=True)
    return f"{'Would create' if dry_run else 'Created'} {link}\n  starts: \"{target}\" {args}\n"


def uninstall(dry_run: bool = False) -> str:
    link = startup_dir() / SHORTCUT
    if not link.exists():
        return "pakwatch watch wasn't set to start at logon.\n"
    if not dry_run:
        link.unlink()
    return f"{'Would remove' if dry_run else 'Removed'} {link}\n"
