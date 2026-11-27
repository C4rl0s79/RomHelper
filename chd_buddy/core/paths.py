"""Porównania ścieżek „czy leży w katalogu" — w JEDNYM miejscu.

Windows: bez rozróżniania wielkości liter i separatorów (normcase), ścieżki
bezwzględne (abspath). Prefiks katalogu kończy się separatorem, więc
``C:\\a\\bc`` NIE leży w ``C:\\a\\b``. Nic tu nie dotyka dysku.
"""
from __future__ import annotations

import os


def dir_key(path) -> str:
    """Znormalizowana ścieżka (bez końcowego separatora) — klucz słowników."""
    return os.path.normcase(os.path.abspath(str(path))).rstrip("\\/")


def dir_prefix(path) -> str:
    """Prefiks katalogu do `norm_path.startswith(prefix)` (z separatorem)."""
    return dir_key(path) + os.sep


def dir_prefixes(paths) -> list[str]:
    """Prefiksy wielu katalogów (puste pomijane)."""
    return [dir_prefix(p) for p in (paths or ()) if p]


def norm(path) -> str:
    """Ścieżka do porównania z prefiksami z `dir_prefix`."""
    return os.path.normcase(os.path.abspath(str(path)))


def is_under(path, directory) -> bool:
    """`path` leży w `directory` (lub jest nim)."""
    p, d = dir_key(path), dir_key(directory)
    return p == d or p.startswith(d + os.sep)


def under_any(path, prefixes) -> bool:
    """`path` leży pod którymkolwiek z prefiksów (z `dir_prefixes`)."""
    p = norm(path)
    return any(p.startswith(x) for x in prefixes)


# BIBLIOTEKI ŹRÓDEŁ tylko do odczytu (np. <ToSort>/cues — paczki cuesheetów i
# luźne .cue, z których naprawa bierze brakujący cue do samotnego bin-a).
# Naprawa czyta z nich KOPIĘ, ale nigdy nie kasuje ani nie przenosi (0.6.93).
_PROTECTED: list[str] = []


def protect(dirs) -> None:
    """Ustawia chronione katalogi (zastępuje poprzednie)."""
    _PROTECTED[:] = dir_prefixes(dirs)


def is_protected(path) -> bool:
    """`path` leży w chronionej bibliotece źródeł — nie kasować, nie przenosić."""
    return bool(_PROTECTED) and under_any(path, _PROTECTED)


def protected_dirs_for(tosorts) -> list:
    """Chronione biblioteki dla katalogów ToSort: `<ToSort>/cues`."""
    from pathlib import Path
    return [Path(str(t)) / "cues" for t in (tosorts or ()) if t]
