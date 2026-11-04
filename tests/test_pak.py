import struct
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from pakwatch import cityhash, pak, scan
from tests.test_scan import SWORD, write


def fstring(s: str) -> bytes:
    b = s.encode() + b"\0"
    return struct.pack("<i", len(b)) + b


def footer(version: int, offset: int, size: int) -> bytes:
    if version < 4:
        return struct.pack("<Iiqq20s", pak.MAGIC, version, offset, size, b"\0" * 20)
    return b"\0" * 16 + b"\0" + struct.pack("<Iiqq20s", pak.MAGIC, version, offset, size, b"\0" * 20) + b"\0" * 160


def build_pak(files: list[str], version: int, mount: str = "../../../") -> bytes:
    """A .pak with no file data, just an index the way UnrealPak writes it."""
    data = b"\0" * 64  # stands in for the file data
    if version < pak.PATH_HASH_INDEX:
        index = fstring(mount) + struct.pack("<i", len(files))
        for f in files:  # name, then FPakEntry: offset, size, raw size, compression, hash, flags, block size
            index += fstring(f) + struct.pack("<qqqI20sBI", 0, 1, 1, 0, b"\0" * 20, 0, 0)
        return data + index + footer(version, len(data), len(index))
    folders: dict[str, list[str]] = {}
    for f in files:
        d, _, n = f.rpartition("/")
        folders.setdefault(d + "/" if d else "/", []).append(n)
    dir_index = struct.pack("<i", len(folders))
    for d, names in folders.items():
        dir_index += fstring(d) + struct.pack("<i", len(names)) + b"".join(fstring(n) + struct.pack("<i", 0) for n in names)
    dir_offset = len(data)
    index = (fstring(mount) + struct.pack("<iQ", len(files), 0) + struct.pack("<I", 0)
             + struct.pack("<I", 1) + struct.pack("<qq20s", dir_offset, len(dir_index), b"\0" * 20)
             + struct.pack("<i", 0) + struct.pack("<i", 0))  # encoded entries, unencoded entries
    body = data + dir_index
    return body + index + footer(version, len(body), len(index))


class CityHashTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(cityhash.cityhash64(b""), cityhash.K2)

    def test_real_package_ids(self):  # pairs read from a real mod's .utoc (path in its index, id in its table)
        for path, cid in (
            ("ProjectPBZ/Plugins/PBZVFXPack/Content/VFX/SanguineSkins/MI/MI_FX_BS1_Blade_001_B.uasset", "46e31b115c50ce0000000001"),
            ("ProjectPBZ/Plugins/Secret/PBZCombatAsset/Content/ActorData/Players/Hun/Weapon/Iron/BP_Weapon_Hun_IronBlade.uasset",
             "4335d12c334bfa1a00000001")):
            self.assertEqual(cityhash.chunk_id(cityhash.package_of(path)).hex(), cid)

    def test_package_names(self):
        self.assertEqual(cityhash.package_of("MyGame/Content/Weapons/BP_Sword.uasset"), "/Game/Weapons/BP_Sword")
        self.assertEqual(cityhash.package_of("MyGame/Plugins/Fx/Content/NS_Trail.uasset"), "/Fx/NS_Trail")
        self.assertEqual(cityhash.package_of("Engine/Content/EngineMaterials/M.uasset"), "/Engine/EngineMaterials/M")
        self.assertIsNone(cityhash.package_of("MyGame/Config/DefaultGame.ini"))
        self.assertIsNone(cityhash.package_of("MyGame/Content/Weapons/BP_Sword.uexp"))


class PakTests(unittest.TestCase):
    FILES = ["MyGame/Content/Weapons/BP_Sword.uasset", "MyGame/Content/Weapons/BP_Sword.uexp", "MyGame/Config/DefaultGame.ini"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, data: bytes) -> pak.PakToc:
        p = self.root / "mod_P.pak"
        p.write_bytes(data)
        return pak.read_pak(p)

    def test_versions(self):
        for version in (3, 8, 11, 12):
            with self.subTest(version=version):
                t = self.read(build_pak(self.FILES, version))
                self.assertEqual(sorted(t.files), sorted(self.FILES))
                self.assertEqual(len(t.chunks()), 2)  # the package (with its .uexp) and the .ini
                self.assertIn(cityhash.chunk_id("/Game/Weapons/BP_Sword"), t.chunks())

    def test_encrypted_index(self):
        data = bytearray(build_pak(self.FILES, 11))
        data[-221 + 16] = 1  # the flag in front of the magic
        t = self.read(bytes(data))
        self.assertTrue(t.encrypted)
        self.assertEqual(t.files, [])

    def test_not_a_pak(self):
        with self.assertRaises(pak.PakError):
            self.read(b"hello" * 100)

    def test_pak_mod_in_the_report(self):
        paks = self.root / "MyGame" / "Content" / "Paks"
        sword = cityhash.chunk_id("/Game/Weapons/BP_Sword")
        write(paks / "MyGame-Windows.utoc", {sword: b"a" * 20, SWORD: b"b" * 20}, time.time() - 100)
        (paks / "~mods").mkdir()
        (paks / "~mods" / "zzz_Sword_P.pak").write_bytes(build_pak(self.FILES, 11))
        write(paks / "~mods" / "zzz_OtherSword_P.utoc", {sword: b"m" * 20}, time.time() - 50)
        (paks / "~mods" / "zzz_Broken_P.pak").write_bytes(b"not a pak at all" * 40)
        with mock.patch.object(scan, "store_dir", return_value=self.root / "store"):
            r = scan.run(paks)
        by_name = {m.toc.path.stem: m for m in r.mods}
        self.assertEqual((len(by_name["zzz_Sword_P"].replaced), by_name["zzz_Sword_P"].added), (1, 1))
        self.assertEqual(sorted(t.path.stem for t in r.conflicts[sword]), ["zzz_OtherSword_P", "zzz_Sword_P"])
        self.assertEqual([n for n, _ in r.unreadable], ["zzz_Broken_P"])


if __name__ == "__main__":
    unittest.main()
