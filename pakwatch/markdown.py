"""The report as Markdown, for a comment to a mod author, Discord or a bug report. No local paths in it."""
from __future__ import annotations

from datetime import datetime


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
        out.append(f"The game updated after {_date(r['snapshot'])}{build}. The update changed {u['changed']:,} game files, "
                   f"added {u['added']:,} and removed {u['removed']:,}.")
    else:
        out.append(f"No game update since {_date(r['since'])}" + (f" (build {u['build']})." if u["build"] else "."))
    groups = [("patch touched", "Needs a look"), ("updated after patch", "Updated by their authors"),
              ("ok", "Fine"), ("adds only", "Only add files")]
    for status, title in groups:
        mods = [m for m in r["mods"] if m["status"] == status]
        if not mods:
            continue
        out += ["", f"**{title}**"]
        for m in mods:
            if status == "patch touched":
                out.append(f"- `{m['name']}`: the update changed {len(m['touched'])} of the {_files(m['replaced'])} it replaces")
                out += [f"  - {f['what']} `{f['path']}`" for f in m["touched"]]
            else:
                out.append(f"- `{m['name']}`")
    if r.get("unreadable"):
        out += ["", "**Couldn't read**"] + [f"- `{x['name']}`: {x['why']}" for x in r["unreadable"]]
    if r["conflicts"]:
        out += ["", "**Replaced by more than one mod**"]
        out += [f"- `{c['path']}`: " + ", ".join(f"`{m}`" for m in c["mods"]) for c in r["conflicts"]]
    out += ["", "<sub>Checked with [pakwatch](https://github.com/ayokiru/pakwatch)</sub>"]
    return "\n".join(out) + "\n"
