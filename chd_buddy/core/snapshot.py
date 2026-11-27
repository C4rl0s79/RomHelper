"""Plik STANU KOLEKCJI — start bez liczenia (0.6.99, model RomVaulta).

RomVault startuje z jednego pliku cache i ufa mu, dopóki użytkownik sam nie
odpali „Update DATs"/skanu. Tu to samo: po wczytaniu DAT-ów / skanie /
podglądzie / naprawie zapisujemy wszystko, czego drzewo potrzebuje na starcie
— wpisy DAT-ów BEZ gier (nazwa, ścieżki, reguły katalogu, liczba gier,
sygnatura pliku do cache), reguła skip, liczniki ToSort, kolejność katalogów,
DAT-y nieudane. Liczby gier są w indeksie liczb (`datcache.load_counts`),
stan gier — leniwie per DAT (`datcache.LazyStates`), gry DAT-ów — z lokalnego
`dat_parse_cache` (`DatEntry.load`). Start nie dotyka NAS.
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from .settings import app_base_dir

SNAPSHOT_FILENAME = "collection_state.pkl"
SNAPSHOT_VERSION = 2          # 2 (0.7.07): formaty „auto" liczone od nowa

# pola wpisu DAT-u (poza grami), które ustawia discover + apply_rule_targets
_FIELDS = ("name", "subdir_per_game", "store_format", "meta")
_EXTRA = ("arcade_format", "_fmt_applied")


def snapshot_path() -> Path:
    return app_base_dir() / SNAPSHOT_FILENAME


def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p))) if p else ""


def _entry_rec(e) -> dict:
    rec = {"dat_path": str(e.dat_path), "target_dir": str(e.target_dir),
           "n_games": e.game_count, "n_roms": e.rom_count,
           "cache_sig": tuple(getattr(e, "cache_sig", ()) or ())}
    for f in _FIELDS:
        rec[f] = getattr(e, f)
    for f in _EXTRA:
        if hasattr(e, f):
            rec[f] = getattr(e, f)
    return rec


def _entry_from(rec: dict):
    from .datstore import DatEntry
    e = DatEntry(dat_path=Path(rec["dat_path"]), name=rec["name"],
                 target_dir=Path(rec["target_dir"]),
                 subdir_per_game=rec.get("subdir_per_game", True),
                 store_format=rec.get("store_format", "keep"),
                 meta=rec.get("meta") or {},
                 n_games=rec.get("n_games", -1), n_roms=rec.get("n_roms", -1),
                 cache_sig=tuple(rec.get("cache_sig") or ()))
    for f in _EXTRA:
        if f in rec:
            setattr(e, f, rec[f])
    return e


def save_snapshot(entries, dat_root, rom_root, *, skip: Optional[dict] = None,
                  tosort: Optional[list] = None, order=None, failed=None,
                  path: Optional[Path] = None) -> bool:
    """Zapis (atomowy) pliku stanu. False = nie zapisano (błąd nie przerywa)."""
    from datetime import datetime

    from .datcache import _drop_tmp, _tmp_for
    dst = Path(path) if path else snapshot_path()
    blob = {"version": SNAPSHOT_VERSION,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "dat_root": _norm(dat_root), "rom_root": _norm(rom_root),
            "entries": [_entry_rec(e) for e in entries],
            "skip": dict(skip or {}), "tosort": list(tosort or []),
            "order": order, "failed": [str(p) for p in (failed or ())]}
    tmp = _tmp_for(dst)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            pickle.dump(blob, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, dst)
        return True
    except (OSError, pickle.PickleError):
        _drop_tmp(tmp)
        return False


def load_snapshot(dat_root, rom_root, path: Optional[Path] = None):
    """Plik stanu dla TYCH ustawień DatRoot/rom_root albo None (brak, stara
    wersja, inne katalogi). Zwraca SimpleNamespace(entries, skip, tosort,
    order, failed, saved_at)."""
    fp = Path(path) if path else snapshot_path()
    try:
        with open(fp, "rb") as f:
            blob = pickle.load(f)
    except (OSError, pickle.PickleError, EOFError, AttributeError):
        return None
    if not isinstance(blob, dict) or blob.get("version") != SNAPSHOT_VERSION:
        return None
    if (blob.get("dat_root") != _norm(dat_root)
            or blob.get("rom_root") != _norm(rom_root)):
        return None
    try:
        entries = [_entry_from(r) for r in blob.get("entries") or ()]
    except (KeyError, TypeError):
        return None
    if not entries:
        return None
    return SimpleNamespace(entries=entries, skip=blob.get("skip") or {},
                           tosort=blob.get("tosort") or [],
                           order=blob.get("order"),
                           failed=blob.get("failed") or [],
                           saved_at=blob.get("saved_at"))


def update_snapshot(path: Optional[Path] = None, **changes) -> None:
    """Zmiana pól pliku stanu bez przebudowy (np. skip po kliknięciu pola
    DAT-u: `skip={klucz: bool}` jest DOKŁADANE). Brak pliku = nic."""
    from .datcache import _drop_tmp, _tmp_for
    dst = Path(path) if path else snapshot_path()
    try:
        with open(dst, "rb") as f:
            blob = pickle.load(f)
    except (OSError, pickle.PickleError, EOFError, AttributeError):
        return
    if not isinstance(blob, dict) or blob.get("version") != SNAPSHOT_VERSION:
        return
    for k, v in changes.items():
        if k == "skip" and isinstance(v, dict):
            blob.setdefault("skip", {}).update(v)
        else:
            blob[k] = v
    tmp = _tmp_for(dst)
    try:
        with open(tmp, "wb") as f:
            pickle.dump(blob, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, dst)
    except (OSError, pickle.PickleError):
        _drop_tmp(tmp)
