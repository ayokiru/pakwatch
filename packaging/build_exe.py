"""Builds dist/pakwatch.exe (one file, console) with PyInstaller, plus its icon from the logo.

usage: python packaging/build_exe.py"""
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def icon(path: Path) -> None:
    """The logo (blue rounded square with the pak cube), drawn at 256 px and saved with the usual icon sizes."""
    n = 256
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, n - 9, n - 9), 56, fill=(20, 120, 245))
    s = n / 96

    def p(x, y):
        return (18 * s + x * 2.5 * s, 17 * s + y * 2.5 * s)

    for a, b in (((21, 8), (12, 3)), ((12, 3), (3, 8)), ((3, 8), (3, 16)), ((3, 16), (12, 21)), ((12, 21), (21, 16)),
                 ((21, 16), (21, 8)), ((3, 8), (12, 13)), ((12, 13), (21, 8)), ((12, 13), (12, 21))):
        d.line((p(*a), p(*b)), fill="white", width=14, joint="curve")
    cx, cy = p(12, 13)
    d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill="white")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main() -> None:
    ico = BUILD / "pakwatch.ico"
    icon(ico)
    web = f"{ROOT / 'pakwatch' / 'web'}{os.pathsep}pakwatch/web"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console", "--name", "pakwatch",
                    "--icon", str(ico), "--add-data", web, "--distpath", str(ROOT / "dist"), "--workpath", str(BUILD / "work"),
                    "--specpath", str(BUILD), str(ROOT / "packaging" / "launcher.py")], check=True, cwd=ROOT)
    exe = ROOT / "dist" / "pakwatch.exe"
    print(f"{exe} ({exe.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
