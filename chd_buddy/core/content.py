"""TOŻSAMOŚĆ TREŚCI z indeksu — jedno miejsce (0.7.09).

Zasada usera: czym jest plik, rozstrzygają SUMY (SHA-1, w razie braku
CRC32+rozmiar), nie nazwa. Pytanie „czy plik/archiwum `p` zawiera te ROM-y /
tę samą treść co `q`" było zapisane osobno w kilku miejscach (matcher,
rebuilder: zajęte miejsce, kopia tej samej gry) — każde z własną odmianą
porównania. Tu jest jedno.
"""
from __future__ import annotations


def _crc(c) -> str:
    return (c or "").lower().zfill(8) if c else ""


def content_sets(index, path) -> tuple:
    """(SHA-1, (CRC32, rozmiar)) treści `path` wg INDEKSU: sam plik oraz —
    dla archiwum — jego niepuste członki. Puste zbiory = treść nieznana."""
    sha: set = set()
    crc: set = set()
    try:
        row = index.lookup(path)
    except Exception:
        row = None
    if row is not None and not row["missing"]:
        # pusty plik (0 B) nie ma tożsamości — każdy ma te same sumy (0.7.10)
        if row["sha1"] and (row["size"] or 0):
            sha.add(row["sha1"].lower())
        if row["crc32"] and row["size"]:
            crc.add((_crc(row["crc32"]), row["size"]))
        path = row["path"]
    try:
        members = index.members_of(path)
    except Exception:
        members = []
    for m in members:
        if not (m["size"] or 0):
            continue
        if m["sha1"]:
            sha.add(m["sha1"].lower())
        if m["crc32"]:
            crc.add((_crc(m["crc32"]), m["size"]))
    return sha, crc


def has_item(sets: tuple, sha1, crc, size) -> bool:
    """Treść jest w `sets`: po SHA-1, a gdy go nie ma po tej stronie (np.
    członek po szybkim skanie) — po CRC32+rozmiar."""
    sha, crcs = sets
    if sha1 and sha1.lower() in sha:
        return True
    return bool(crc and size) and (_crc(crc), size) in crcs


def holds_roms(index, path, roms) -> bool:
    """`path` zawiera (po sumach) WSZYSTKIE niepuste ROM-y z `roms`. Brak
    niepustych ROM-ów albo nieznana treść pliku → False."""
    need = [r for r in roms if (getattr(r, "size", 0) or 0)
            and (getattr(r, "sha1", "") or getattr(r, "crc", ""))]
    if not need:
        return False
    sets = content_sets(index, path)
    if not (sets[0] or sets[1]):
        return False
    return all(has_item(sets, r.sha1, r.crc, r.size) for r in need)
