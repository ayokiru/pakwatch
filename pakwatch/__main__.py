"""pakwatch <game folder>: which mods the last game patch touched, and which mods replace the same files."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import scan
from .utoc import Toc


def short(toc: Toc, cid: bytes) -> str:
    return toc.name_of(cid).replace("../../../", "")


def show(report: scan.Report, out=sys.stdout) -> int:
    w = out.write
    if report.first:
        w(f"{report.game_files:,} game files. First run: the game is remembered now, so run pakwatch again after the next update.\n")
    elif report.patched:
        w(f"{report.game_files:,} game files. The game changed since {report.snapshot.taken}; mods compared with that version.\n")
    else:
        w(f"{report.game_files:,} game files. No update since {report.since}.\n")
    if not report.mods:
        w("No mods found (*_P containers or anything in a subfolder such as ~mods).\n")
    trouble = 0
    for m in report.mods:
        name = m.toc.path.stem
        w(f"\n{'!' if m.status == 'patch touched' else ' '} {name}: {m.status}, replaces {len(m.replaced)} game files, adds {m.added}\n")
        hit = [(c, "changed") for c in m.changed] + [(c, "removed") for c in m.removed]
        trouble += m.status == "patch touched"
        for cid, what in hit[:20]:
            w(f"    {what}: {short(m.toc, cid)}\n")
        if len(hit) > 20:
            w(f"    ...and {len(hit) - 20} more\n")
    if report.conflicts:
        w(f"\nFiles replaced by more than one mod (only one of them wins):\n")
        for cid, tocs in sorted(report.conflicts.items(), key=lambda kv: short(kv[1][0], kv[0])):
            w(f"  {short(tocs[0], cid)}: {', '.join(t.path.stem for t in tocs)}\n")
    return 1 if trouble or report.conflicts else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pakwatch", description=__doc__.split(": ", 1)[1])
    ap.add_argument("game", type=Path, nargs="?",
                    help="the game's install folder (or its Content\\Paks); without it pakwatch opens in your browser")
    args = ap.parse_args(argv)
    if args.game is None:
        from . import gui
        gui.run()
        return 0
    try:
        report = scan.run(scan.find_paks(args.game))
    except (FileNotFoundError, ValueError) as e:
        print(f"pakwatch: {e}", file=sys.stderr)
        return 2
    return show(report)


if __name__ == "__main__":
    sys.exit(main())
