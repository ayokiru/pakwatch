"""pakwatch <game folder>: which mods the last game patch touched, and which mods replace the same files."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, scan
from .utoc import Toc


def short(toc: Toc, cid: bytes) -> str:
    return toc.name_of(cid).replace("../../../", "")


UE4SS_WARNING = ("The game's exe changed in this update. Script mods often break when the exe changes, "
                 "so check for a new UE4SS and new versions of your script mods.")
TOUCHED = ("patch touched", "uses changed")  # statuses that make the exit code 1
GROUPS = [("patch touched", "Needs a look", "!"), ("uses changed", "Uses changed game files", "!"),
          ("updated after patch", "Updated by their authors", "+"),
          ("ok", "Fine", " "), ("adds only", "Only add files", " ")]


def files(n: int) -> str:
    return f"{n:,} game file" + ("" if n == 1 else "s")


def date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").strftime("%d %b %Y, %H:%M UTC").lstrip("0")


def update_line(r: scan.Report) -> str:
    parts = [f"{w} {files(n) if i == 0 else f'{n:,}'}" for i, (w, n) in
             enumerate((("changed", r.files_changed), ("added", r.files_added), ("removed", r.files_removed))) if n]
    build = f" (build {r.build_before} -> {r.build})" if r.build_before and r.build else ""
    return f"The update {', '.join(parts) or 'changed no files'}{build}."


def show(report: scan.Report, out=sys.stdout) -> int:
    w = out.write
    if report.first:
        w(f"{files(report.game_files)}. First check: pakwatch remembers this version, run it again after the next update.\n")
    elif report.patched:
        w(f"{files(report.game_files)}. The game updated after {date(report.snapshot.taken)}. {update_line(report)}\n")
    else:
        w(f"{files(report.game_files)}. No update since {date(report.since)}.\n")
    if not report.mods:
        w("\nNo mods found (*_P containers or anything in a subfolder of Paks, such as ~mods).\n")
    for status, title, mark in GROUPS:
        mods = sorted((m for m in report.mods if m.status == status), key=lambda m: m.toc.path.stem.lower())
        if mods:
            w(f"\n{title}\n")
        for m in mods:
            detail = [f"replaces {files(len(m.replaced))}" if m.replaced else "", f"adds {m.added:,}" if m.added else ""]
            w(f"{mark} {m.toc.path.stem}  {', '.join(d for d in detail if d)}\n")
            hit = [f"changed  {short(m.toc, c)}" for c in m.changed] + [f"removed  {short(m.toc, c)}" for c in m.removed]
            hit += [f"uses changed  {m.import_name(c)}" for c in m.uses_changed]
            hit += [f"uses removed  {m.import_name(c)}" for c in m.uses_removed]
            for line in hit[:20]:
                w(f"    {line}\n")
            if len(hit) > 20:
                w(f"    and {len(hit) - 20} more\n")
            if report.patched and getattr(m.toc, "imports_note", ""):
                w(f"    imports not readable: {m.toc.imports_note}\n")
    if report.unreadable:
        w("\nCouldn't read\n")
        for name, why in report.unreadable:
            w(f"? {name}  {why}\n")
    if report.ue4ss:
        u = report.ue4ss
        w(f"\nUE4SS{' ' + u['version'] if u['version'] else ''}, {len(u['mods'])} script mod{'' if len(u['mods']) == 1 else 's'}\n")
        for m in u["mods"]:
            w(f"  {'on ' if m['on'] else 'off'}  {m['name']}\n")
        if report.exe_changed:
            w(f"! {UE4SS_WARNING}\n")
    if report.conflicts:
        w("\nReplaced by more than one mod (the game loads one version)\n")
        for cid, tocs in sorted(report.conflicts.items(), key=lambda kv: short(kv[1][0], kv[0])):
            w(f"  {short(tocs[0], cid)}  {', '.join(t.path.stem for t in tocs)}  (loads: {tocs[0].path.stem})\n")
    touched = any(m.status in TOUCHED for m in report.mods)
    return 1 if touched or report.conflicts else 0


def watch_main(argv: list[str]) -> int:
    from . import watch
    ap = argparse.ArgumentParser(prog="pakwatch watch", description="Check your Steam games with mods after every "
                                 "Steam update and show the result in a Windows notification.")
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--install", action="store_true", help="start pakwatch watch at every logon (a Startup shortcut)")
    which.add_argument("--uninstall", action="store_true", help="stop starting it at logon")
    ap.add_argument("--dry-run", action="store_true", help="say what would happen, change nothing and show no notification")
    args = ap.parse_args(argv)
    if args.install:
        print(watch.install(args.dry_run), end="")
    elif args.uninstall:
        print(watch.uninstall(args.dry_run), end="")
    else:
        watch.run(dry_run=args.dry_run)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["watch"]:
        return watch_main(argv[1:])
    ap = argparse.ArgumentParser(prog="pakwatch", description=__doc__.split(": ", 1)[1],
                                 epilog="pakwatch watch --help: check after every Steam update")
    ap.add_argument("game", type=Path, nargs="?",
                    help="the game's install folder (or its Content\\Paks); without it pakwatch opens in your browser")
    ap.add_argument("--markdown", action="store_true", help="print the report as Markdown, ready to paste")
    ap.add_argument("--no-browser", action="store_true", help="window mode: print the address instead of opening it")
    ap.add_argument("--version", action="version", version=f"pakwatch {__version__}")
    args = ap.parse_args(argv)
    if args.game is None:
        from . import gui
        gui.run(open_browser=not args.no_browser)
        return 0
    try:
        paks = scan.find_paks(args.game)
        if args.markdown:
            from .gui import full_report
            r = full_report(paks)
            sys.stdout.buffer.write(r["markdown"].encode("utf-8"))  # UTF-8 even on a cp1251 console
            return 1 if r["conflicts"] or any(x["status"] in TOUCHED for x in r["mods"]) else 0
        report = scan.run(paks)
    except (FileNotFoundError, ValueError) as e:
        print(f"pakwatch: {e}", file=sys.stderr)
        return 2
    return show(report)


if __name__ == "__main__":
    sys.exit(main())
