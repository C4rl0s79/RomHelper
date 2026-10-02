"""TorrentZip — ZIP o BITOWO POWTARZALNEJ postaci (jak TrrntZip / RomVault).

Ta sama zawartość (te same nazwy i dane) daje zawsze te same bajty pliku, więc
ten sam zip w dwóch DAT-ach to jeden plik fizyczny + hardlink (dedup), a
RomVault uznaje go za poprawny i nie przepakowuje.

Reguły formatu:
- pliki posortowane po nazwie bez rozróżniania wielkości liter (remis →
  porządek z rozróżnianiem), separator „/";
- deflate zlib poziom 9 (raw, okno 15, memLevel 8), flaga 0x0002 („max");
- stała data/czas DOS 1996-12-24 23:32:00, brak pól extra, atrybuty 0,
  „version made by" 0, „needed" 20 (45 dla zip64);
- komentarz końcowy `TORRENTZIPPED-XXXXXXXX` = CRC32 katalogu centralnego.
"""
from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path
from typing import BinaryIO, Callable, Iterable, Optional, Tuple

import ctypes
import sys

TZ_TIME = 0xBC00              # 23:32:00
TZ_DATE = 0x2198              # 1996-12-24
_FLAG_MAX = 0x0002
_FLAG_UTF8 = 0x0800
_ZIP64_LIMIT = 0xFFFFFFFF
_CHUNK = 4 * 1024 * 1024
COMMENT_PREFIX = b"TORRENTZIPPED-"

# źródło danych członka: bajty albo funkcja otwierająca strumień do odczytu
Source = "bytes | Callable[[], BinaryIO]"
ProgCB = Callable[[int, int, str], None]


# --- KLASYCZNY zlib (bitowa zgodność z RomVault/TrrntZip) --------------------
# Python 3.14 na Windows ma zlib-ng — kompresuje INACZEJ (0/10 zgodnych
# strumieni). Klasyczny zlib 1.2.11/1.3.1/1.3.2 = 10/10 identycznych z
# TorrentZipami RomVaulta. Dołączona `chd_zlib1.dll` (zlib 1.3.2 mingw, tylko
# kernel32/msvcrt).

class _ZStream(ctypes.Structure):
    _fields_ = [("next_in", ctypes.c_void_p), ("avail_in", ctypes.c_uint),
                ("total_in", ctypes.c_ulong), ("next_out", ctypes.c_void_p),
                ("avail_out", ctypes.c_uint), ("total_out", ctypes.c_ulong),
                ("msg", ctypes.c_char_p), ("state", ctypes.c_void_p),
                ("zalloc", ctypes.c_void_p), ("zfree", ctypes.c_void_p),
                ("opaque", ctypes.c_void_p), ("data_type", ctypes.c_int),
                ("adler", ctypes.c_ulong), ("reserved", ctypes.c_ulong)]


_ZLIB = None          # ctypes.CDLL albo False (brak)


def _dll_candidates():
    # unikalna nazwa modułu: inna `zlib1.dll` już załadowana w procesie (Qt
    # itp.) nie może zostać podstawiona zamiast naszej
    names = ("chd_zlib1.dll",)
    dirs = []
    if getattr(sys, "_MEIPASS", None):
        dirs.append(Path(sys._MEIPASS))
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent)
    dirs.append(Path(__file__).resolve().parent.parent / "bin")
    for d in dirs:
        for n in names:
            yield d / n


def classic_zlib():
    """Klasyczny zlib (ctypes) albo None, gdy niedostępny."""
    global _ZLIB
    if _ZLIB is None:
        _ZLIB = False
        for c in _dll_candidates():
            if not c.is_file():
                continue
            try:
                lib = ctypes.CDLL(str(c))
                lib.zlibVersion.restype = ctypes.c_char_p
                if b"ng" in lib.zlibVersion():
                    continue
                _ZLIB = lib
                break
            except OSError:
                continue
    return _ZLIB or None


def classic_zlib_version() -> str:
    lib = classic_zlib()
    return lib.zlibVersion().decode() if lib else ""


class _ClassicDeflater:
    """Odpowiednik `zlib.compressobj(9, DEFLATED, -15, 8)` na klasycznym zlib."""

    _OUT = 1 << 20

    def __init__(self, lib):
        self._lib = lib
        self._s = _ZStream()
        r = lib.deflateInit2_(ctypes.byref(self._s), 9, 8, -15, 8, 0,
                              lib.zlibVersion(), ctypes.sizeof(self._s))
        if r != 0:
            raise OSError(f"deflateInit2 = {r}")
        self._out = ctypes.create_string_buffer(self._OUT)

    def _run(self, data: bytes, flush: int) -> bytes:
        s = self._s
        inb = ctypes.create_string_buffer(data, len(data)) if data else None
        s.next_in = ctypes.cast(inb, ctypes.c_void_p) if inb else None
        s.avail_in = len(data)
        res = bytearray()
        while True:
            s.next_out = ctypes.cast(self._out, ctypes.c_void_p)
            s.avail_out = self._OUT
            r = self._lib.deflate(ctypes.byref(s), flush)
            if r not in (0, 1, -5):          # Z_OK, Z_STREAM_END, Z_BUF_ERROR
                raise OSError(f"deflate = {r}")
            res += self._out.raw[:self._OUT - s.avail_out]
            if flush == 4:
                if r == 1:
                    break
            elif s.avail_in == 0 and s.avail_out != 0:
                break
        return bytes(res)

    def compress(self, data: bytes) -> bytes:
        return self._run(data, 0) if data else b""

    def flush(self) -> bytes:
        try:
            return self._run(b"", 4)
        finally:
            self._lib.deflateEnd(ctypes.byref(self._s))


def _deflater():
    lib = classic_zlib()
    if lib is not None:
        return _ClassicDeflater(lib)
    # awaryjnie: poprawny TorrentZip, ale bajty mogą różnić się od RomVaulta
    return zlib.compressobj(9, zlib.DEFLATED, -15, 8, zlib.Z_DEFAULT_STRATEGY)


def tz_sort_key(name: str) -> Tuple[str, str]:
    """Kolejność TrrntZip: małe litery, potem dokładna nazwa."""
    return (name.lower(), name)


def _name_bytes(name: str) -> Tuple[bytes, int]:
    try:
        return name.encode("ascii"), 0
    except UnicodeEncodeError:
        return name.encode("utf-8"), _FLAG_UTF8


def write_torrentzip(out_path, entries: Iterable[Tuple[str, object]], *,
                     on_progress: Optional[ProgCB] = None,
                     label: str = "") -> int:
    """Zapisuje TorrentZip do `out_path` (plik tymczasowy — wywołujący robi
    atomową podmianę). `entries`: (nazwa, bajty | funkcja→strumień). Zwraca
    rozmiar pliku. Dane są kompresowane STRUMIENIOWO (członki po setki MB)."""
    items = sorted(((str(e[0]).replace("\\", "/"), e[1],
                     e[2] if len(e) > 2 else 0) for e in entries),
                   key=lambda x: tz_sort_key(x[0]))
    central = bytearray()
    total_items = len(items)
    with open(out_path, "wb") as f:
        for idx, (name, src, known) in enumerate(items, 1):
            nb, uflag = _name_bytes(name)
            flags = _FLAG_MAX | uflag
            offset = f.tell()
            # nagłówek lokalny z zerami — uzupełniany po kompresji (seek)
            f.write(b"\0" * (30 + len(nb)))
            comp = _deflater()
            crc = 0
            usize = 0
            csize = 0
            lab = f"{label or Path(str(out_path)).name}: {name} ({idx}/{total_items})"
            if isinstance(src, (bytes, bytearray, memoryview)):
                data = bytes(src)
                crc = zlib.crc32(data)
                usize = len(data)
                out = comp.compress(data) + comp.flush()
                f.write(out)
                csize = len(out)
                if on_progress:
                    on_progress(usize, usize, lab)
            else:
                with src() as fin:
                    while True:
                        buf = fin.read(_CHUNK)
                        if not buf:
                            break
                        crc = zlib.crc32(buf, crc)
                        usize += len(buf)
                        out = comp.compress(buf)
                        if out:
                            f.write(out)
                            csize += len(out)
                        if on_progress:
                            on_progress(usize, known or 0, lab)
                out = comp.flush()
                f.write(out)
                csize += len(out)
            crc &= 0xFFFFFFFF
            end = f.tell()
            zip64 = (usize >= _ZIP64_LIMIT or csize >= _ZIP64_LIMIT
                     or offset >= _ZIP64_LIMIT)
            if zip64:
                raise ValueError(f"TorrentZip: członek >4 GB nieobsługiwany ({name})")
            f.seek(offset)
            f.write(struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags, 8,
                                TZ_TIME, TZ_DATE, crc, csize, usize, len(nb), 0))
            f.write(nb)
            f.seek(end)
            central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 0, 20,
                                   flags, 8, TZ_TIME, TZ_DATE, crc, csize,
                                   usize, len(nb), 0, 0, 0, 0, 0, offset)
            central += nb
        cd_offset = f.tell()
        if cd_offset >= _ZIP64_LIMIT or total_items > 0xFFFF:
            raise ValueError("TorrentZip: archiwum >4 GB / >65535 plików")
        f.write(central)
        comment = COMMENT_PREFIX + f"{zlib.crc32(bytes(central)) & 0xFFFFFFFF:08X}".encode("ascii")
        f.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, total_items,
                            total_items, len(central), cd_offset, len(comment)))
        f.write(comment)
        return f.tell()


def torrentzip_status(path) -> int:
    """1 = poprawny TorrentZip (komentarz + CRC katalogu centralnego zgodne),
    0 = inny zip, -1 = nie da się odczytać. Czyta tylko końcówkę pliku."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            back = min(size, 22 + 0xFFFF)
            f.seek(size - back)
            tail = f.read(back)
            i = tail.rfind(b"PK\x05\x06")
            if i < 0:
                return -1
            (_sig, _d, _dc, _n1, _n2, cd_size, cd_off,
             clen) = struct.unpack("<IHHHHIIH", tail[i:i + 22])
            comment = tail[i + 22:i + 22 + clen]
            if not comment.startswith(COMMENT_PREFIX) or len(comment) != 22:
                return 0
            f.seek(cd_off)
            cd = f.read(cd_size)
            want = f"{zlib.crc32(cd) & 0xFFFFFFFF:08X}".encode("ascii")
            return 1 if comment[len(COMMENT_PREFIX):] == want else 0
    except (OSError, struct.error):
        return -1


def repack_to_torrentzip(src_zip, out_path, *, on_progress: Optional[ProgCB] = None,
                         verify_sha1: Optional[dict] = None,
                         label: str = "") -> None:
    """Przepakowuje istniejący zip (dowolna metoda, także zstd/RVZSTD) do
    TorrentZip pod `out_path`. Treść członków bez zmian; `verify_sha1`
    {nazwa: sha1} — opcjonalna kontrola po zapisie."""
    import zipfile
    with zipfile.ZipFile(src_zip) as zin:
        infos = [i for i in zin.infolist() if not i.is_dir()]
        entries = [(i.filename, (lambda n=i.filename: zin.open(n)), i.file_size)
                   for i in infos]
        write_torrentzip(out_path, entries, on_progress=on_progress,
                         label=label or Path(str(src_zip)).name)
    with zipfile.ZipFile(out_path) as zchk:
        bad = zchk.testzip()
        if bad is not None:
            raise ValueError(f"TorrentZip: błąd CRC członka {bad}")
        if verify_sha1:
            import hashlib
            for n, want in verify_sha1.items():
                h = hashlib.sha1()
                with zchk.open(n) as fh:
                    for b in iter(lambda: fh.read(_CHUNK), b""):
                        h.update(b)
                if h.hexdigest() != want.lower():
                    raise ValueError(f"TorrentZip: SHA-1 {n} nie zgadza się")
