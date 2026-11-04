"""Makes docs/demo.gif: real pakwatch output on a demo game, typed into a terminal frame by frame.

A demo Steam library is built in a temp folder (example data: made-up mods on a real game's name), pakwatch runs
on it before and after a made-up update, and the transcript is drawn as a GIF. usage: python dev/make_demo.py"""
import hashlib
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pakwatch import cityhash  # noqa: E402
from tests.test_utoc import build_toc  # noqa: E402

SHOWN = r"C:\Program Files (x86)\Steam\steamapps\common\Oblivion Remastered"
PROJECT = "OblivionRemastered"
MODS = {
    "zzz_ClassicHUD_P": ["Content/UI/HUD/WBP_Compass", "Content/UI/HUD/WBP_HealthBars", "Content/UI/HUD/T_HUD_Atlas"],
    "zzz_QuieterGuards_P": ["Content/Dev/Audio/Dialogue/DT_GuardBarks"],
    "zzz_HUDTweaks_P": ["Content/UI/HUD/WBP_Compass"],
    "zzz_ElvenArmorRetexture_P": ["Content/Art/Characters/Armor/Elven/T_Elven_Cuirass_D"],
    "zzz_LanternsOfCyrodiil_P": ["Content/Art/Props/Lanterns/SM_Lantern_Iron", "+Content/Art/Props/Lanterns/T_Lantern_Glow"],
}
CHANGED = ["Content/UI/HUD/WBP_Compass", "Content/UI/HUD/WBP_HealthBars", "Content/Dev/Audio/Dialogue/DT_GuardBarks"]


def cid(rel: str) -> bytes:
    return cityhash.chunk_id(cityhash.package_of(f"{PROJECT}/{rel}.uasset"))


def h(tag: str) -> bytes:
    return hashlib.sha1(tag.encode()).digest()


def write(path: Path, files: dict, names: dict, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = list(files)
    path.write_bytes(build_toc(ids, [files[i] for i in ids], names, mount="../../../"))
    os.utime(path, (mtime, mtime))


def build(tmp: Path, build_id: str, version: str, mtime: float) -> Path:
    game = tmp / "steamapps" / "common" / "Oblivion Remastered"
    (tmp / "steamapps").mkdir(parents=True, exist_ok=True)
    (tmp / "steamapps" / "appmanifest_2623190.acf").write_text(
        f'"AppState"\n{{\n\t"name"\t\t"The Elder Scrolls IV: Oblivion Remastered"\n\t"installdir"\t\t"Oblivion Remastered"\n'
        f'\t"buildid"\t\t"{build_id}"\n}}\n')
    paks = game / PROJECT / "Content" / "Paks"
    files = {cid(r.lstrip("+")): h(version + r if r in CHANGED else "v1" + r) for m in MODS.values() for r in m if not r.startswith("+")}
    files.update({cid(f"Content/Data/Pkg_{i:05d}"): h(f"{version if i < 1200 else 'v1'}{i}") for i in range(41_230)})
    write(paks / f"{PROJECT}-Windows.utoc", files, {}, mtime)
    return game


def transcript() -> list[str]:
    tmp = Path(tempfile.mkdtemp(prefix="pakwatch-demo-"))
    env = dict(os.environ, LOCALAPPDATA=str(tmp / "local"))
    t0 = 1_760_000_000
    try:
        game = build(tmp, "18263447", "v1", t0)
        paks = game / PROJECT / "Content" / "Paks"
        for i, (mod, rels) in enumerate(MODS.items()):
            names = {k: f"{PROJECT}/{r.lstrip('+')}.uasset" for k, r in enumerate(rels)}
            write(paks / "~mods" / f"{mod}.utoc", {cid(r.lstrip("+")): h(mod + r) for r in rels},
                  {k: n for k, n in names.items()}, t0 + 100 + i)

        def run(*args):
            r = subprocess.run([sys.executable, "-m", "pakwatch", str(game), *args], env=env, cwd=ROOT, capture_output=True)
            return r.stdout.decode("utf-8").replace(str(game), SHOWN).rstrip().splitlines()

        lines = [f'$ pakwatch "{SHOWN}"', *run(), ""]
        build(tmp, "18491202", "v2", t0 + 86_400 * 9)  # the update
        later = t0 + 86_400 * 10
        os.utime(paks / "~mods" / "zzz_HUDTweaks_P.utoc", (later, later))  # its author already caught up
        lines += ["$ # nine days later the game updates", f'$ pakwatch "{SHOWN}"', *run(), ""]
        md = run("--markdown")
        lines += [f'$ pakwatch "{SHOWN}" --markdown', *md[:12]]
        return lines
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- drawing --------------------------------------------------------------------------------------------
W, H, PAD, BAR = 1000, 580, 22, 34
FONT = ImageFont.truetype(r"C:\Windows\Fonts\CascadiaMono.ttf", 15)
LH = 21
ROWS = (H - BAR - 2 * PAD) // LH
BG, BARC, FG, DIM = (22, 22, 24), (38, 38, 42), (230, 230, 235), (142, 142, 147)
GREEN, ORANGE, BLUE, MUTED = (48, 209, 88), (255, 159, 10), (10, 132, 255), (152, 152, 157)
MAXC = (W - 2 * PAD) // int(FONT.getlength("m"))


HEADERS = {"Needs a look": ORANGE, "Updated by their authors": BLUE, "Fine": GREEN, "Only add files": MUTED,
           "Replaced by more than one mod (the game loads one version)": ORANGE}


def colors(lines: list[str]) -> list:
    """One color per line, by the report section it is in, the way the window colors them."""
    out, section = [], None
    for ln in lines:
        s = ln.strip()
        if ln.startswith("$ "):
            out.append(None)
            section = None
        elif ln in HEADERS or s.startswith("**"):
            section = HEADERS.get(ln, ORANGE if "Needs" in s else BLUE if "Updated" in s else MUTED)
            out.append(DIM)
        elif s.startswith(("changed", "removed", "- changed")) or ln.startswith("    "):
            out.append(MUTED)
        elif s and section and not ln.startswith("###"):
            out.append(section)
        else:
            out.append(FG)
    return out


def wrap(line: str) -> list[str]:
    out = []
    while len(line) > MAXC:
        cut = line.rfind(" ", 0, MAXC)
        cut = cut if cut > MAXC // 2 else MAXC
        out.append(line[:cut])
        line = "    " + line[cut:].lstrip()
    return out + [line]


def frame(lines: list[str], cursor: bool) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, BAR], fill=BARC)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse([16 + i * 22, 11, 28 + i * 22, 23], fill=c)
    d.text((W // 2, BAR // 2), "pakwatch", font=FONT, fill=DIM, anchor="mm")
    shown = lines[-ROWS:]
    y = BAR + PAD
    for ln, c in zip(shown, colors(lines)[-ROWS:]):
        if ln.startswith("$ "):
            d.text((PAD, y), "$", font=FONT, fill=GREEN)
            d.text((PAD + FONT.getlength("$ "), y), ln[2:], font=FONT, fill=DIM if ln.startswith("$ #") else FG)
        else:
            d.text((PAD, y), ln, font=FONT, fill=c)
        y += LH
    if cursor:
        last = shown[-1] if shown else ""
        x = PAD + FONT.getlength(last)
        d.rectangle([x + 1, y - LH + 3, x + 9, y - 3], fill=FG)
    return im


def render(script: list[str], out: Path) -> None:
    random.seed(7)
    frames, durations, screen = [], [], []

    def add(cursor=True, ms=60):
        frames.append(frame(screen, cursor))
        durations.append(ms)

    for line in script:
        if line.startswith("$ "):
            screen.append("$ ")
            add(ms=500)
            typed = line[2:]
            for k in range(1, len(typed) + 1, 2):  # two characters a frame keeps the file small
                screen[-1] = "$ " + typed[:k]
                add(ms=random.choice((35, 45, 60)))
            screen[-1] = line
            add(ms=350)
        else:
            for part in wrap(line):
                screen.append(part)
                add(cursor=False, ms=40)
    add(ms=4000)
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=64) for f in frames]
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True, disposal=1)
    print(out, f"{out.stat().st_size // 1024} KB, {len(frames)} frames")


if __name__ == "__main__":
    script = transcript()
    print("\n".join(script))
    render(script, ROOT / "docs" / "demo.gif")
