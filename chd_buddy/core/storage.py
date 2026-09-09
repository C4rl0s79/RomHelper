"""Rozpoznanie nośnika katalogu: sieć (NAS/SMB) vs dysk lokalny.

Decyduje o liczbie wątków hashujących w skanie — na NAS/SMB i SSD/NVMe kilka
odczytów naraz ukrywa latencję (duży zysk), na pojedynczym HDD szkodzi (skakanie
głowicy). Auto-wykrywanie (Windows: typ dysku / ścieżka UNC) + ręczne nadpisanie
per katalog z GUI (przełącznik „na NAS / lokalny").
"""
from __future__ import annotations

import os

# Rodzaje nośnika i sugerowana liczba wątków skanu.
KINDS = ("nas", "ssd", "hdd")


def _auto_kind(path: str) -> str:
    """Zgaduje nośnik BEZ nadpisań: 'nas' dla ścieżek sieciowych (UNC albo dysk
    zmapowany jako sieciowy), inaczej 'ssd' (bezpieczny domyślny — zakłada dysk
    lokalny obsługujący równoległe odczyty). Na nie-Windows: 'ssd'."""
    p = str(path or "")
    if p.startswith("\\\\") or p.startswith("//"):
        return "nas"                       # UNC = zasób sieciowy
    if os.name != "nt":
        return "ssd"
    try:
        import ctypes
        drive = os.path.splitdrive(os.path.abspath(p))[0]
        if drive:
            root = drive + "\\"
            # GetDriveTypeW: 4 = DRIVE_REMOTE (sieć)
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 4:
                return "nas"
    except Exception:
        pass
    return "ssd"


def _override_for(path: str, overrides: dict | None) -> str | None:
    """Ręczne nadpisanie nośnika dla `path` (najdłuższy pasujący prefiks)."""
    if not overrides:
        return None
    target = os.path.normcase(os.path.abspath(str(path)))
    best_len, best_val = -1, None
    for pref, kind in overrides.items():
        pk = os.path.normcase(os.path.abspath(str(pref)))
        if (target == pk or target.startswith(pk + os.sep)) and len(pk) > best_len:
            best_len, best_val = len(pk), str(kind)
    return best_val


def storage_kind(path, overrides: dict | None = None) -> str:
    """Nośnik katalogu: ręczne nadpisanie (jeśli jest) albo auto-wykrycie."""
    ov = _override_for(str(path), overrides)
    if ov in KINDS:
        return ov
    return _auto_kind(str(path))


def same_volume(a, b) -> bool:
    """Czy `a` i `b` leżą na TYM SAMYM woluminie (systemie plików) — wtedy
    przeniesienie to `os.rename` (natychmiastowe, bez kopiowania bajtów). Różny
    wolumin = kopiowanie (wolne). Najpierw `st_dev` (numer woluminu), fallback:
    litera dysku / UNC share."""
    try:
        sa = os.stat(a).st_dev
        sb = os.stat(b).st_dev
        if sa and sb:
            return sa == sb
    except OSError:
        pass
    da = os.path.splitdrive(os.path.abspath(str(a)))[0].lower()
    db = os.path.splitdrive(os.path.abspath(str(b)))[0].lower()
    return bool(da) and da == db


def workers_for_kind(kind: str, nas: int, ssd: int, hdd: int) -> int:
    """Liczba wątków hashujących wg nośnika (HDD zawsze 1 — równoległość szkodzi)."""
    if kind == "nas":
        return max(1, int(nas))
    if kind == "hdd":
        return 1
    return max(1, int(ssd))
