"""CityHash64 (v1.1, as in Unreal's Core/Hash/CityHash.cpp), and Unreal's package chunk ids built on it.

IoStore names a package's data by FPackageId = CityHash64 of the lower-case package name as UTF-16. With it a
legacy .pak mod's file paths can be matched against the game's IoStore chunks."""
from __future__ import annotations

import struct

M = (1 << 64) - 1
K0, K1, K2 = 0xC3A5C85C97CB3127, 0xB492B66FBE98F273, 0x9AE16A3B2F90404F
KMUL = 0x9DDFEA08EB382D69


def _f64(s: bytes, i: int) -> int:
    return struct.unpack_from("<Q", s, i)[0]


def _f32(s: bytes, i: int) -> int:
    return struct.unpack_from("<I", s, i)[0]


def _rot(v: int, n: int) -> int:
    return v if n == 0 else ((v >> n) | (v << (64 - n))) & M


def _mix(v: int) -> int:
    return v ^ (v >> 47)


def _bswap(v: int) -> int:
    return int.from_bytes(v.to_bytes(8, "little"), "big")


def _len16(u: int, v: int, mul: int = KMUL) -> int:
    a = ((u ^ v) * mul) & M
    a ^= a >> 47
    b = ((v ^ a) * mul) & M
    b ^= b >> 47
    return (b * mul) & M


def _0to16(s: bytes) -> int:
    n = len(s)
    if n >= 8:
        mul = K2 + n * 2
        a = (_f64(s, 0) + K2) & M
        b = _f64(s, n - 8)
        c = (_rot(b, 37) * mul + a) & M
        d = ((_rot(a, 25) + b) * mul) & M
        return _len16(c, d, mul)
    if n >= 4:
        mul = K2 + n * 2
        return _len16((n + (_f32(s, 0) << 3)) & M, _f32(s, n - 4), mul)
    if n:
        y = s[0] + (s[n >> 1] << 8)
        z = n + (s[n - 1] << 2)
        return (_mix(((y * K2) ^ (z * K0)) & M) * K2) & M
    return K2


def _17to32(s: bytes) -> int:
    n = len(s)
    mul = K2 + n * 2
    a = (_f64(s, 0) * K1) & M
    b = _f64(s, 8)
    c = (_f64(s, n - 8) * mul) & M
    d = (_f64(s, n - 16) * K2) & M
    return _len16((_rot((a + b) & M, 43) + _rot(c, 30) + d) & M, (a + _rot((b + K2) & M, 18) + c) & M, mul)


def _33to64(s: bytes) -> int:
    n = len(s)
    mul = K2 + n * 2
    a = (_f64(s, 0) * K2) & M
    b = _f64(s, 8)
    c = _f64(s, n - 24)
    d = _f64(s, n - 32)
    e = (_f64(s, 16) * K2) & M
    f = (_f64(s, 24) * 9) & M
    g = _f64(s, n - 8)
    h = (_f64(s, n - 16) * mul) & M
    u = (_rot((a + g) & M, 43) + (_rot(b, 30) + c) * 9) & M
    v = (((a + g) & M ^ d) + f + 1) & M
    w = (_bswap(((u + v) * mul) & M) + h) & M
    x = (_rot((e + f) & M, 42) + c) & M
    y = ((_bswap(((v + w) * mul) & M) + g) * mul) & M
    z = (e + f + c) & M
    a = (_bswap(((x + z) * mul + y) & M) + b) & M
    b = (_mix(((z + a) * mul + d + h) & M) * mul) & M
    return (b + x) & M


def _weak(s: bytes, i: int, a: int, b: int) -> tuple[int, int]:
    w, x, y, z = _f64(s, i), _f64(s, i + 8), _f64(s, i + 16), _f64(s, i + 24)
    a = (a + w) & M
    b = _rot((b + a + z) & M, 21)
    c = a
    a = (a + x + y) & M
    b = (b + _rot(a, 44)) & M
    return (a + z) & M, (b + c) & M


def cityhash64(s: bytes) -> int:
    n = len(s)
    if n <= 16:
        return _0to16(s)
    if n <= 32:
        return _17to32(s)
    if n <= 64:
        return _33to64(s)
    x = _f64(s, n - 40)
    y = (_f64(s, n - 16) + _f64(s, n - 56)) & M
    z = _len16((_f64(s, n - 48) + n) & M, _f64(s, n - 24))
    v = _weak(s, n - 64, n, z)
    w = _weak(s, n - 32, (y + K1) & M, x)
    x = (x * K1 + _f64(s, 0)) & M
    pos, left = 0, (n - 1) & ~63
    while left:
        x = (_rot((x + y + v[0] + _f64(s, pos + 8)) & M, 37) * K1) & M
        y = (_rot((y + v[1] + _f64(s, pos + 48)) & M, 42) * K1) & M
        x ^= w[1]
        y = (y + v[0] + _f64(s, pos + 40)) & M
        z = (_rot((z + w[0]) & M, 33) * K1) & M
        v = _weak(s, pos, (v[1] * K1) & M, (x + w[0]) & M)
        w = _weak(s, pos + 32, (z + w[1]) & M, (y + _f64(s, pos + 16)) & M)
        z, x = x, z
        pos += 64
        left -= 64
    return _len16((_len16(v[0], w[0]) + _mix(y) * K1 + z) & M, (_len16(v[1], w[1]) + x) & M)


def package_id(package: str) -> int:
    """FPackageId::FromName: CityHash64 of the lower-case name as UTF-16, e.g. "/Game/Weapons/BP_Sword"."""
    return cityhash64(package.lower().encode("utf-16-le"))


def chunk_id(package: str, kind: int = 1) -> bytes:
    """FIoChunkId for a package: 8-byte id, 2-byte index (big-endian, 0), a pad byte, the chunk type (1: package)."""
    return struct.pack("<Q", package_id(package)) + b"\0\0\0" + bytes([kind])


def package_of(path: str) -> str | None:
    """Pak path -> package name. Proj/Content/X/Y.uasset -> /Game/X/Y; .../Plugins/.../P/Content/X -> /P/X;
    Engine/Content/X -> /Engine/X. None for files that aren't packages (.ini, .uexp, ...)."""
    p = path.replace("\\", "/").lstrip("./")
    stem, dot, ext = p.rpartition(".")
    if not dot or ext.lower() not in ("uasset", "umap"):
        return None
    parts = stem.split("/")
    if "Content" not in parts:
        return None
    i = len(parts) - 1 - parts[::-1].index("Content")  # the last Content: plugins nest one inside another
    rest = "/".join(parts[i + 1:])
    owner = parts[i - 1] if i > 0 else ""
    if i >= 2 and parts[i - 2] == "Plugins" or "Plugins" in parts[:i]:
        return f"/{owner}/{rest}"
    return f"/Engine/{rest}" if owner == "Engine" else f"/Game/{rest}"
