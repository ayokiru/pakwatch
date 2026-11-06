"""The report as Markdown, for a comment to a mod author, Discord or a bug report. No local paths in it."""
from __future__ import annotations

from datetime import datetime

from .__main__ import UE4SS_WARNING


def _date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").strftime("%d %b %Y").lstrip("0")


def _files(n: int) -> str:
    return f"{n:,} game file" + ("" if n == 1 else "s")


def render(r: dict, name: str) -> str:
    """r is the report as the window gets it (gui.report_json)."""
    u = r["update"]
    out = [f"### pakwatch: {name}", ""]
    if r["first"]:
        out.append(f"First check, nothing to compare with yet. {_files(r['game_files'])}, {len(r['mods'])} mods.")
    elif r["patched"]:
        build = f" (build {u['build_before']} → {u['build']})" if u["build_before"] and u["build"] else ""
        parts = [f"{w} {_files(n) if i == 0 else f'{n:,}'}" for i, (w, n) in
                 enumerate((("changed", u["changed"]), ("added", u["added"]), ("removed", u["removed"]))) if n]
        out.append(f"The game updated after {_date(r['snapshot'])}{build}. The update {', '.join(parts) or 'changed no files'}.")
    else:
        out.append(f"No game update since {_date(r['since'])}" + (f" (build {u['build']})." if u["build"] else "."))
    groups = [("patch touched", "Needs a look"), ("uses changed", "Uses changed game files"),
              ("updated after patch", "Updated by their authors"),
              ("ok", "Fine"), ("adds only", "Only add files")]
    for status, title in groups:
        mods = [m for m in r["mods"] if m["status"] == status]
        if not mods:
            continue
        out += ["", f"**{title}**"]
        for m in mods:
            if status == "patch touched":
                t, n = len(m["touched"]), m["replaced"]
                what = (f"{t} of the {_files(n)}" if t < n else "the game file" if t == 1
                        else "both game files" if t == 2 else f"all {_files(t)}")
                out.append(f"- `{m['name']}`: the update changed {what} it replaces")
                out += [f"  - {f['what']} `{f['path']}`" for f in m["touched"]]
            elif status == "uses changed":
                u = len(m["uses"])
                out.append(f"- `{m['name']}`: its own files use {'a game file' if u == 1 else f'{u} game files'} the update changed")
                out += [f"  - {f['what']} `{f['path']}`" for f in m["uses"]]
            else:
                out.append(f"- `{m['name']}`")
            if m.get("imports_note"):
                out.append(f"  - imports not readable: {m['imports_note']}")
    if r.get("unreadable"):
        out += ["", "**Couldn't read**"] + [f"- `{x['name']}`: {x['why']}" for x in r["unreadable"]]
    if r.get("ue4ss"):
        u = r["ue4ss"]
        out += ["", f"**UE4SS{' ' + u['version'] if u['version'] else ''} script mods**"]
        out += [f"- `{m['name']}`" + ("" if m["on"] else " (off)") for m in u["mods"]] or ["- none"]
        if r.get("exe_changed"):
            out += ["", UE4SS_WARNING]
    if r["conflicts"]:
        out += ["", "**Replaced by more than one mod**"]
        out += [f"- `{c['path']}`: " + ", ".join(f"`{m}`" for m in c["mods"]) + f" (loads: `{c['loads']}`)" for c in r["conflicts"]]
    out += ["", "<sub>Checked with [pakwatch](https://github.com/ayokiru/pakwatch)</sub>"]
    return "\n".join(out) + "\n"
