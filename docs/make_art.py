"""Draws the README banner (dark and light) and the social preview: python docs/make_art.py (Windows fonts).

Same layout as the other ayokiru tools; the right side is a small pakwatch window instead of a terminal."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent
FONTS = Path(r"C:\Windows\Fonts")
S = 2  # drawn at twice the size, so it stays sharp on high-DPI screens

THEMES = {  # the window's own palette (pakwatch/web/index.html)
    "dark": dict(bg=(16, 16, 18), bg2=(24, 24, 28), dot=(44, 44, 50), title=(245, 245, 247), text=(210, 210, 216),
                 muted=(142, 142, 147), accent=(10, 132, 255), chip=(35, 35, 38), chip_line=(64, 64, 70),
                 win=(22, 22, 24), side=(30, 30, 33), group=(35, 35, 37), sep=(58, 58, 62), label=(245, 245, 247),
                 sub=(160, 160, 166), orange=(255, 159, 10), green=(48, 209, 88), blue=(10, 132, 255), gray=(152, 152, 157)),
    "light": dict(bg=(245, 245, 247), bg2=(232, 232, 237), dot=(210, 210, 216), title=(29, 29, 31), text=(60, 60, 67),
                  muted=(110, 110, 115), accent=(0, 113, 227), chip=(255, 255, 255), chip_line=(210, 210, 215),
                  win=(245, 245, 247), side=(232, 232, 236), group=(255, 255, 255), sep=(224, 224, 228), label=(29, 29, 31),
                  sub=(110, 110, 115), orange=(224, 120, 0), green=(40, 167, 69), blue=(0, 122, 255), gray=(142, 142, 147)),
}


def mono(size, weight="Regular"):
    f = ImageFont.truetype(str(FONTS / "CascadiaCode.ttf"), size * S)
    f.set_variation_by_name(weight)
    return f


def sans(size, bold=False):
    return ImageFont.truetype(str(FONTS / ("seguisb.ttf" if bold else "segoeui.ttf")), size * S)


def symbol(d, cx, cy, r, color, kind):
    """The status symbols of the window: a filled circle with a white mark."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    w = max(2, r // 4)
    if kind == "warn":
        d.line([cx, cy - r * 0.45, cx, cy + r * 0.12], fill="white", width=w)
        d.ellipse([cx - w / 2, cy + r * 0.38 - w / 2, cx + w / 2, cy + r * 0.38 + w / 2], fill="white")
    elif kind == "check":
        d.line([(cx - r * 0.42, cy + r * 0.02), (cx - r * 0.1, cy + r * 0.34), (cx + r * 0.45, cy - r * 0.3)], fill="white", width=w, joint="curve")
    elif kind == "up":
        d.line([cx, cy + r * 0.45, cx, cy - r * 0.42], fill="white", width=w)
        d.line([(cx - r * 0.38, cy - r * 0.05), (cx, cy - r * 0.45), (cx + r * 0.38, cy - r * 0.05)], fill="white", width=w, joint="curve")


def window(d, im, box, c):
    x0, y0, x1, y1 = [v * S for v in box]
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x0, y0 + 18, x1, y1 + 18], 22 * S, fill=(0, 0, 0, 80))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(28)))
    d.rounded_rectangle([x0, y0, x1, y1], 16 * S, fill=c["win"])
    side = x0 + 120 * S
    d.rounded_rectangle([x0, y0, side + 16 * S, y1], 16 * S, fill=c["side"])
    d.rectangle([side, y0, side + 16 * S, y1], fill=c["win"])
    d.line([side, y0, side, y1], fill=c["sep"], width=S)
    d.rounded_rectangle([x0, y0, x1, y1], 16 * S, outline=c["sep"], width=S)  # last, over both halves
    for i, col in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = x0 + (18 + i * 16) * S
        d.ellipse([cx - 5 * S, y0 + 13 * S, cx + 5 * S, y0 + 23 * S], fill=col)
    small, tiny = sans(11, bold=True), sans(9)
    games = (("Oblivion R.", "7 mods", (52, 199, 120), "ES"), ("S.T.A.L.K.E.R. 2", "4 mods", (40, 170, 190), "S2"),
             ("Black Myth", "3 mods", (214, 100, 60), "BM"), ("Phantom Blade", "1 mod", (180, 200, 60), "PB"))
    picked = tuple(int(a + (b - a) * 0.22) for a, b in zip(c["side"], c["accent"]))  # the window's accent-soft
    for i, (name, n, hue, ini) in enumerate(games):
        ty = y0 + (44 + i * 34) * S
        if i == 0:
            d.rounded_rectangle([x0 + 6 * S, ty - 5 * S, side - 6 * S, ty + 27 * S], 7 * S, fill=picked)
        d.rounded_rectangle([x0 + 12 * S, ty, x0 + 34 * S, ty + 22 * S], 6 * S, fill=hue)
        d.text((x0 + 23 * S, ty + 11 * S), ini, font=sans(8, bold=True), fill="white", anchor="mm")
        d.text((x0 + 40 * S, ty - 1 * S), name, font=small, fill=c["label"])
        d.text((x0 + 40 * S, ty + 12 * S), n, font=tiny, fill=c["sub"])
    cx0 = side + 24 * S
    symbol(d, cx0 + 14 * S, y0 + 56 * S, 14 * S, c["orange"], "warn")
    d.text((cx0 + 36 * S, y0 + 40 * S), "2 mods need a look", font=sans(19, bold=True), fill=c["label"])
    d.text((cx0 + 37 * S, y0 + 66 * S), "The update changed files these mods replace.", font=sans(10), fill=c["sub"])
    rows = (("Needs a look", [("zzz_ClassicHUD_P", "changed 2 of 3 game files", "orange", "warn"),
                              ("zzz_QuieterGuards_P", "changed the file it replaces", "orange", "warn")]),
            ("Fine", [("zzz_ElvenArmor_P", "replaces 2 game files", "green", "check"),
                      ("zzz_Lanterns_P", "replaces 2 game files, adds 1", "green", "check")]))
    y, gx1 = y0 + 96 * S, x1 - 16 * S
    for title, items in rows:
        d.text((cx0 + 6 * S, y), title, font=sans(9, bold=True), fill=c["sub"])
        y += 15 * S
        top = y
        d.rounded_rectangle([cx0, top, gx1, top + len(items) * 34 * S], 9 * S, fill=c["group"])
        for i, (name, sub, col, kind) in enumerate(items):
            ry = top + i * 34 * S
            if i:
                d.line([cx0 + 34 * S, ry, gx1, ry], fill=c["sep"], width=S)
            symbol(d, cx0 + 17 * S, ry + 17 * S, 9 * S, c[col], kind)
            d.text((cx0 + 34 * S, ry + 5 * S), name, font=sans(11, bold=True), fill=c["label"])
            d.text((cx0 + 34 * S, ry + 19 * S), sub, font=sans(9), fill=c["sub"])
        y = top + len(items) * 34 * S + 12 * S


def logo(d, x, y, size):
    d.rounded_rectangle([x, y, x + size, y + size], size * 0.23, fill=(20, 120, 245))
    s = size / 96

    def p(px, py):
        return (x + 18 * s + px * 2.5 * s, y + 17 * s + py * 2.5 * s)

    for a, b in (((21, 8), (12, 3)), ((12, 3), (3, 8)), ((3, 8), (3, 16)), ((3, 16), (12, 21)), ((12, 21), (21, 16)),
                 ((21, 16), (21, 8)), ((3, 8), (12, 13)), ((12, 13), (21, 8)), ((12, 13), (12, 21))):
        d.line((p(*a), p(*b)), fill="white", width=max(2, int(size / 18)), joint="curve")
    cx, cy = p(12, 13)
    r = size * 0.055
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="white")


def banner(theme: str, w=1280, h=400, path=None):
    c = THEMES[theme]
    im = Image.new("RGBA", (w * S, h * S), c["bg"])
    d = ImageDraw.Draw(im)
    for y in range(h * S):  # soft vertical gradient
        t = y / (h * S)
        d.line([(0, y), (w * S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c["bg"], c["bg2"])))
    for gx in range(0, w * S, 28 * S):  # dot grid, faded toward the text side
        for gy in range(0, h * S, 28 * S):
            if gx > 560 * S:
                d.ellipse([gx, gy, gx + 2 * S, gy + 2 * S], fill=c["dot"])
    x, top = 72 * S, (h - 400) // 2 * S
    logo(d, x, top + 70 * S, 44 * S)
    d.text((x + 58 * S, top + 80 * S), "for Unreal Engine 5 mods", font=mono(16, "SemiBold"), fill=c["accent"])
    d.text((x - 4 * S, top + 116 * S), "pakwatch", font=mono(64, "Bold"), fill=c["title"])
    tag = sans(24)
    d.text((x, top + 206 * S), "See which of your mods", font=tag, fill=c["text"])
    d.text((x, top + 240 * S), "a game update touched.", font=tag, fill=c["text"])
    cx, cy, cf = x, top + 300 * S, sans(15, bold=True)
    for chip in ("Steam aware", "IoStore + .pak", "mod conflicts", "turn mods off"):
        tw = cf.getlength(chip)
        d.rounded_rectangle([cx, cy, cx + tw + 28 * S, cy + 34 * S], 17 * S, fill=c["chip"], outline=c["chip_line"], width=S)
        d.text((cx + 14 * S, cy + 17 * S), chip, font=cf, fill=c["text"], anchor="lm")
        cx += tw + 38 * S
    pad = (h - 400) // 2
    window(d, im, (w - 540, pad + 48, w - 56, h - pad - 48), c)
    out = im.convert("RGB").resize((w * 2, h * 2) if S == 2 else (w, h))
    Image.frombytes(out.mode, out.size, out.tobytes()).save(path or OUT / f"banner-{theme}.png", optimize=True)


if __name__ == "__main__":
    banner("dark")
    banner("light")
    print("written to", OUT)
