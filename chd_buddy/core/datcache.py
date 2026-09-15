"""Przyrostowy cache sparsowanych DAT-ów.

Parsowanie 391 DAT-ów (1,36 mln ROM-ów) z XML jest wolne — a DAT-y zmieniają
się rzadko. Cache trzyma per plik: (mtime, rozmiar) + nazwa z nagłówka +
lista gier. Przy kolejnym wczytaniu niezmienione DAT-y ładują się z cache;
tylko nowe/zmienione są parsowane ponownie. Cache jest zapisywany po każdym
odkryciu, jeśli coś się zmieniło.

Format pliku: pickle {abspath: {"sig": (mtime_ns, size), "name": str,
"games": [DatGame]}}. Wersjonowany — niezgodna wersja = cache ignorowany.
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Optional

from .datfile import DatGame, parse_dat, parse_dat_header
from .settings import app_base_dir

CACHE_FILENAME = "dat_parse_cache.pkl"
CACHE_VERSION = 3      # v3: DatGame.cloneof/romof + DatRom.merge (MAME)

REPORT_CACHE_FILENAME = "report_state_cache.pkl"   # stary format: jeden plik
REPORT_STATES_DIRNAME = "report_states"            # nowy: plik per DAT
REPORT_CACHE_VERSION = 4      # v4: + archive_names_ok (zła nazwa w archiwum)


def cache_path() -> Path:
    return app_base_dir() / CACHE_FILENAME


def report_cache_path() -> Path:
    """Katalog zapamiętanych raportów (jeden plik na DAT)."""
    return app_base_dir() / REPORT_STATES_DIRNAME


def _report_file(dirpath: Path, dat_key: str) -> Path:
    import hashlib
    h = hashlib.sha1(os.path.normcase(dat_key).encode("utf-8")).hexdigest()[:20]
    return dirpath / f"{h}.pkl"


def _compact(rep) -> dict:
    games: dict[str, dict] = {}
    for s in rep.statuses:
        games.setdefault(s.game, {})[s.rom.name.lower()] = (
            s.state.value, s.source_path, s.member, int(s.via_chd),
            int(getattr(s, "via_archive", False)),
            int(getattr(s, "archive_names_ok", True)))
    return games


def _write_report_file(dirpath: Path, key: str, games: dict, saved_at: str) -> None:
    dst = _report_file(dirpath, key)
    tmp = dst.with_suffix(".pkl.tmp")
    try:
        with open(tmp, "wb") as f:
            pickle.dump({"version": REPORT_CACHE_VERSION, "saved_at": saved_at,
                         "dat": key, "games": games},
                        f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, dst)
    except (OSError, pickle.PickleError):
        tmp.unlink(missing_ok=True)


def save_report_states(reports, path: Optional[Path] = None) -> None:
    """Zapisuje ZWARTY stan raportu — OSOBNY plik dla KAŻDEGO DAT-u:
    {gra: {rom_lower: (kod_stanu, source_path, member, via_chd, …)}}. Pozwala
    po ponownym otwarciu programu pokazać ostatni wynik skanu WRAZ z planem
    naprawy (skąd plik).

    Zapisywane są WYŁĄCZNIE DAT-y z tego raportu. Skan obejmuje tylko włączone
    DAT-y, więc odznaczony DAT (żeby skan był szybszy) po prostu nie jest
    ruszany i po ponownym zaznaczeniu ma swój ostatni stan. Dawniej jeden
    wspólny plik był nadpisywany samymi włączonymi DAT-ami — stan wyłączonych
    znikał — i przy każdym skanie przepisywało się kilkadziesiąt MB."""
    d = Path(path) if path else report_cache_path()
    from datetime import datetime
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    for rep in reports:
        key = str(Path(os.path.abspath(rep.entry.dat_path)))
        _write_report_file(d, key, _compact(rep), now)


def _migrate_legacy(d: Path) -> None:
    """Jednorazowo rozbija stary wspólny plik na pliki per DAT (plik zostaje)."""
    legacy = d.parent / REPORT_CACHE_FILENAME
    if not legacy.is_file() or (d.is_dir() and any(d.glob("*.pkl"))):
        return
    try:
        with open(legacy, "rb") as f:
            blob = pickle.load(f)
        if blob.get("version") != REPORT_CACHE_VERSION:
            return
    except (OSError, pickle.PickleError, EOFError, AttributeError):
        return
    d.mkdir(parents=True, exist_ok=True)
    saved_at = blob.get("saved_at") or ""
    for key, games in (blob.get("reports") or {}).items():
        _write_report_file(d, key, games, saved_at)


def load_report_states(path: Optional[Path] = None):
    """Zwraca (saved_at, {dat_abspath: {gra: {rom_lower: status}}}) albo
    (None, {}). status = lekki obiekt z polami state/source_path/member/
    via_chd (do kolorów i planu naprawy). `saved_at` = najnowszy zapis.
    Pliki DAT-ów, których już nie ma na dysku, są pomijane."""
    d = Path(path) if path else report_cache_path()
    if path is None:
        _migrate_legacy(d)
    if not d.is_dir():
        return None, {}
    from types import SimpleNamespace

    from .matcher import RomState
    out: dict[str, dict] = {}
    newest = None
    for fp in d.glob("*.pkl"):
        try:
            with open(fp, "rb") as f:
                blob = pickle.load(f)
        except (OSError, pickle.PickleError, EOFError, AttributeError):
            continue
        if not isinstance(blob, dict) or blob.get("version") != REPORT_CACHE_VERSION:
            continue
        key = blob.get("dat") or ""
        if not key or not os.path.isfile(key):
            continue
        out[key] = {
            g: {rn: SimpleNamespace(
                    state=RomState(v[0]), source_path=v[1], member=v[2],
                    via_chd=bool(v[3]),
                    via_archive=bool(v[4]) if len(v) > 4 else False,
                    archive_names_ok=bool(v[5]) if len(v) > 5 else True)
                for rn, v in roms.items()}
            for g, roms in (blob.get("games") or {}).items()}
        at = blob.get("saved_at")
        if at and (newest is None or at > newest):
            newest = at
    if not out:
        return None, {}
    return newest, out


def _sig(path: Path) -> tuple[int, int]:
    st = path.stat()
    return (st.st_mtime_ns, st.st_size)


class DatParseCache:
    """Wczytuje/zapisuje sparsowane DAT-y; parsuje tylko zmienione."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else cache_path()
        self._data: dict[str, dict] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            with open(self.path, "rb") as f:
                blob = pickle.load(f)
            if isinstance(blob, dict) and blob.get("version") == CACHE_VERSION:
                self._data = blob.get("entries", {})
        except (OSError, pickle.PickleError, EOFError, AttributeError):
            self._data = {}       # uszkodzony/stary cache — zignoruj

    def get(self, dat: Path) -> Optional[tuple[str, list[DatGame]]]:
        """Zwraca (name, games) z cache, jeśli plik niezmieniony."""
        key = str(Path(os.path.abspath(dat)))
        rec = self._data.get(key)
        if rec is None:
            return None
        try:
            if tuple(rec["sig"]) != _sig(dat):
                return None
        except OSError:
            return None
        return rec["name"], rec["games"]

    def put(self, dat: Path, name: str, games: list[DatGame]) -> None:
        key = str(Path(os.path.abspath(dat)))
        try:
            sig = _sig(dat)
        except OSError:
            return
        self._data[key] = {"sig": sig, "name": name, "games": games}
        self._dirty = True

    def parse(self, dat: Path) -> tuple[str, list[DatGame]]:
        """Nazwa + gry DAT-a — z cache albo świeżo sparsowane (i dołożone)."""
        hit = self.get(dat)
        if hit is not None:
            return hit
        name = (parse_dat_header(dat).get("name") or dat.stem)
        games = list(parse_dat(dat))
        self.put(dat, name, games)
        return name, games

    def prune(self, present: set[str]) -> None:
        """Usuwa z cache wpisy DAT-ów, których już nie ma (present = zbiór
        aktualnych abspath)."""
        stale = [k for k in self._data if k not in present]
        for k in stale:
            del self._data[k]
            self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".pkl.tmp")
        try:
            with open(tmp, "wb") as f:
                pickle.dump({"version": CACHE_VERSION, "entries": self._data},
                            f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, self.path)
            self._dirty = False
        except (OSError, pickle.PickleError):
            tmp.unlink(missing_ok=True)
