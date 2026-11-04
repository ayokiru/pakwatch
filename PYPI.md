<p align="center"><img src="https://raw.githubusercontent.com/ayokiru/pakwatch/main/docs/logo.svg" width="88" alt=""></p>
<h1 align="center">pakwatch</h1>
<p align="center">See which of your mods a game update touched, before you find out in the game.</p>
<p align="center">
  <a href="https://github.com/ayokiru/pakwatch/actions/workflows/test.yml"><img src="https://github.com/ayokiru/pakwatch/actions/workflows/test.yml/badge.svg" alt="Tests"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-8e8e93" alt="MIT license">
</p>

![pakwatch in the browser, example data](https://raw.githubusercontent.com/ayokiru/pakwatch/main/docs/window-light.png)
<p align="center"><sub>Example data: the games are real, the mods and the update are made up for the picture.</sub></p>

Unreal Engine 5 games keep their files in IoStore containers, and pak mods replace some of those files. After a game update, a mod that replaces a file the update changed can crash the game or quietly undo a fix, and you only notice once you play. pakwatch remembers your game's files. After an update it shows which mods replace files that changed, so you know which ones to check for a new version.

## What it tells you

<table>
  <tr><td width="34%"><img src="https://raw.githubusercontent.com/ayokiru/pakwatch/main/docs/status-look.svg" width="20" alt=""> <b>Needs a look</b></td><td>The update changed or removed a game file this mod replaces. Look for a newer version of the mod.</td></tr>
  <tr><td width="34%"><img src="https://raw.githubusercontent.com/ayokiru/pakwatch/main/docs/status-updated.svg" width="20" alt=""> <b>Updated by its author</b></td><td>The mod is newer than the update, so its author has probably caught up.</td></tr>
  <tr><td width="34%"><img src="https://raw.githubusercontent.com/ayokiru/pakwatch/main/docs/status-fine.svg" width="20" alt=""> <b>Fine</b></td><td>None of the files it replaces changed.</td></tr>
  <tr><td width="34%"><img src="https://raw.githubusercontent.com/ayokiru/pakwatch/main/docs/status-adds.svg" width="20" alt=""> <b>Only adds files</b></td><td>It replaces nothing, so an update can't clash with it.</td></tr>
  <tr><td width="34%"><img src="https://raw.githubusercontent.com/ayokiru/pakwatch/main/docs/status-shared.svg" width="20" alt=""> <b>Replaced by more than one mod</b></td><td>Two mods replace the same file. The game loads one version, and the other mod loses that part.</td></tr>
</table>

## Get started

Download `pakwatch.exe` from the [latest release](https://github.com/ayokiru/pakwatch/releases/latest) and run it, or install it with Python 3.11 or newer:

```
pip install pakwatch
pakwatch
```

pakwatch opens in your browser and lists the Unreal Engine games in your Steam libraries. Pick one, or type the folder of a game that isn't on Steam.

The first check remembers the game as it is now, so run it while your mods work. Open pakwatch again after the next game update. The report then also says how many game files the update changed and, for Steam games, which build it went from and to.

From the report you can turn a mod off until its author catches up. pakwatch moves the mod's files out of the game, and Turn On puts them back where they were. Copy Report puts the whole report on the clipboard as Markdown, ready for a comment to the mod's author or a bug report, without any of your local paths.

## On the command line

Give it the game's folder and it prints the same report:

```
> pakwatch "C:\Program Files (x86)\Steam\steamapps\common\MyGame"
304,986 game files. The game changed since 2026-11-03T21:40:12Z; mods compared with that version.

! zzz_Swords_P: patch touched, replaces 9 game files, adds 8
    changed: MyGame/Content/Weapons/BP_Sword.uasset

  zzz_Shields_P: ok, replaces 2 game files, adds 0
```

The exit code is 0 when everything is fine, 1 when the update touched a mod or two mods collide, and 2 when the folder can't be read, so scripts and mod managers can act on it. Add `--markdown` to get the shareable version of the report instead. `pakwatch --no-browser` starts the window without opening it and prints its address.

## How it works

- pakwatch reads only the tables of contents (`.utoc`) of the game's containers. It never opens the data in `.ucas`, so it needs no AES key, and a whole game takes about a second.
- Every file in a container has a content hash. pakwatch keeps the hashes of all game files, a few MB per game in `%LOCALAPPDATA%\pakwatch`, and compares them after an update.
- A mod is any `*_P` container, or anything in a subfolder of `Paks` such as `~mods`.
- Mods packed as a plain `.pak` work too. Their index lists file paths without hashes, so pakwatch turns each path into the package id the game uses (CityHash64 of the package name) and matches it against the game's files.
- The report compares with the game as it was before the last update, so it keeps showing what that update touched until the next one.

## Privacy and safety

pakwatch only reads files, except when you press Turn Off or Turn On. Those move one mod's files between the game's `Paks` folder and `%LOCALAPPDATA%\pakwatch`, and never delete or overwrite anything. pakwatch never connects to the internet. The window is a page served on 127.0.0.1 with a one-time key, so other sites open in your browser can't use it, and it shuts down shortly after you close the tab.

## Limits

- It works with IoStore games, which is most Unreal Engine 5 games. The game's own `.pak` files aren't read, because their file index is usually encrypted. A mod with an encrypted index is listed under "Couldn't read".
- A changed file doesn't always break a mod, and an unchanged one doesn't prove it works. Treat the list as the places to check first.
- When a game encrypts its file index, file names come from the mod's own index, which is usually readable.

## License

MIT
