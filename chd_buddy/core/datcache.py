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

CACHE_FILENAME = "dat_parse_cache.pkl"     # stary MONOLIT (migrowany → katalog)
CACHE_DIRNAME = "dat_parse_cache"          # v3+: OSOBNY plik per DAT (obok exe)
CACHE_VERSION = 3      # v3: DatGame.cloneof/romof + DatRom.merge (MAME)

REPORT_CACHE_FILENAME = "report_state_cache.pkl"   # stary format: jeden plik
REPORT_STATES_DIRNAME = "report_states"            # nowy: plik per DAT
REPORT_CACHE_VERSION = 4      # v4: + archive_names_ok (zła nazwa w archiwum)


def cache_path() -> Path:
    return app_base_dir() / CACHE_FILENAME


def cache_dir() -> Path:
    """Katalog cache sparsowanych DAT-ów (jeden plik na DAT) — obok exe."""
    return app_base_dir() / CACHE_DIRNAME


def _cache_file(dirpath: Path, dat_key: str) -> Path:
    import hashlib
    h = hashlib.sha1(os.path.normcase(dat_key).encode("utf-8")).hexdigest()[:20]
    return dirpath / f"{h}.pkl"


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


STALE_MARKER = ".nieaktualny"     # naprawa zmieniła indeks, a stan nie przeliczony


def mark_report_states_stale(path: Optional[Path] = None) -> None:
    """Naprawa zaczyna zmieniać pliki/indeks → zapamiętany stan przestaje być
    prawdą. Znacznik zdejmuje dopiero zapis stanu przeliczonego z indeksu
    (`save_report_states`). Gdy program zamknięto w trakcie naprawy, start
    widzi znacznik i przelicza stan z indeksu (bez skanu plików)."""
    d = Path(path) if path else report_cache_path()
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / STALE_MARKER).write_text("1", encoding="utf-8")
    except OSError:
        pass


def report_states_stale(path: Optional[Path] = None) -> bool:
    d = Path(path) if path else report_cache_path()
    return (d / STALE_MARKER).is_file()


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
    # stan policzony z AKTUALNEGO indeksu → znacznik „nieaktualny" zdjęty
    try:
        (d / STALE_MARKER).unlink(missing_ok=True)
    except OSError:
        pass


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


def _expand(games: dict) -> dict:
    """Zapisany (zwarty) stan DAT-u → {gra: {rom_lower: status}} dla okna."""
    from types import SimpleNamespace

    from .matcher import RomState
    return {g: {rn: SimpleNamespace(
                    state=RomState(v[0]), source_path=v[1], member=v[2],
                    via_chd=bool(v[3]),
                    via_archive=bool(v[4]) if len(v) > 4 else False,
                    archive_names_ok=bool(v[5]) if len(v) > 5 else True)
                for rn, v in roms.items()}
            for g, roms in games.items()}


def states_from_reports(reports) -> dict:
    """Stan okna {dat_abspath: {gra: {rom_lower: status}}} prosto z raportów
    w pamięci — TEN SAM format co `load_report_states`, bez czytania dysku.
    Osobne obiekty (nie statusy raportu), więc dalsze zmiany na żywo liczą
    różnicę względem tego stanu."""
    return {str(Path(os.path.abspath(rep.entry.dat_path))): _expand(_compact(rep))
            for rep in reports}


def load_report_states(path: Optional[Path] = None, known_keys=None):
    """Zwraca (saved_at, {dat_abspath: {gra: {rom_lower: status}}}) albo
    (None, {}). status = lekki obiekt z polami state/source_path/member/
    via_chd (do kolorów i planu naprawy). `saved_at` = najnowszy zapis.

    `known_keys` — zbiór abspath AKTUALNIE odkrytych DAT-ów (z pamięci): stany
    DAT-ów spoza niego są pomijane. NIE sprawdzamy istnienia plików DAT na
    dysku — DAT-y leżą na NAS, a `isfile` per plik (600+) to ~45 s seryjnych
    rund SMB na wątku GUI (zamrażało start, przerwanie i koniec skanu).
    Bez `known_keys` zwracamy wszystko (nieaktualne klucze są nieszkodliwe —
    nikt ich nie odpyta, bo lookup idzie po kluczach bieżących DAT-ów)."""
    d = Path(path) if path else report_cache_path()
    if path is None:
        _migrate_legacy(d)
    if not d.is_dir():
        return None, {}
    known = ({os.path.normcase(k) for k in known_keys}
             if known_keys is not None else None)
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
        if not key or (known is not None and os.path.normcase(key) not in known):
            continue
        out[key] = _expand(blob.get("games") or {})
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
    """Cache sparsowanych DAT-ów — OSOBNY plik na DAT (obok exe).

    Dawniej jeden monolit ``dat_parse_cache.pkl`` (~315 MB): zmiana JEDNEGO
    DAT-a przepisywała całość, a start odpicklowywał wszystko naraz. Teraz
    każdy DAT ma własny ``<hash(abspath)>.pkl`` = {sig, dat, name, games}:
    zmiana dotyka tylko swojego pliku, a wczytanie bierze wyłącznie realnie
    potrzebne DAT-y. Zapis jest natychmiastowy (``put``), więc ``save`` to
    no-op (zgodność API). Stary monolit jest jednorazowo rozbijany na pliki
    per DAT i usuwany (odzysk ~315 MB; cache i tak się regeneruje).

    `path` (opcjonalne, głównie testy) wskazuje KATALOG cache; None = obok exe.
    """

    def __init__(self, path: Optional[Path] = None, log=None):
        self.dir = Path(path) if path else cache_dir()
        self._migrate_monolith(log)

    def _migrate_monolith(self, log=None) -> None:
        legacy = self.dir.parent / CACHE_FILENAME
        if not legacy.is_file():
            return
        # już zmigrowane (katalog ma pliki) → tylko posprzątaj monolit
        if self.dir.is_dir() and any(self.dir.glob("*.pkl")):
            legacy.unlink(missing_ok=True)
            return
        if log:
            log("Migruję cache DAT-ów na format per-plik (jednorazowo po "
                "aktualizacji, chwilę to potrwa)…")
        try:
            with open(legacy, "rb") as f:
                blob = pickle.load(f)
        except (OSError, pickle.PickleError, EOFError, AttributeError):
            return
        if not isinstance(blob, dict) or blob.get("version") != CACHE_VERSION:
            legacy.unlink(missing_ok=True)     # stara wersja — i tak do wyrzucenia
            return
        n = 0
        for key, rec in (blob.get("entries") or {}).items():
            try:
                self._write(key, rec["sig"], rec["name"], rec["games"])
                n += 1
            except (KeyError, TypeError):
                continue
        legacy.unlink(missing_ok=True)
        if log:
            log(f"Migracja cache DAT-ów zakończona ({n} plików) — kolejne starty "
                f"będą szybkie.")

    def _write(self, key: str, sig, name: str, games: list[DatGame]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        dst = _cache_file(self.dir, key)
        tmp = dst.with_suffix(".pkl.tmp")
        try:
            with open(tmp, "wb") as f:
                pickle.dump({"version": CACHE_VERSION, "sig": tuple(sig),
                             "dat": key, "name": name, "games": games},
                            f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, dst)
        except (OSError, pickle.PickleError):
            tmp.unlink(missing_ok=True)

    def get(self, dat: Path, sig=None) -> Optional[tuple[str, list[DatGame]]]:
        """Zwraca (name, games) z cache, jeśli plik DAT-a niezmieniony.
        `sig` (mtime_ns, size) można podać z zewnątrz (discover robi jeden
        RÓWNOLEGŁY przebieg stat na NAS), żeby uniknąć stat per rekord."""
        key = str(Path(os.path.abspath(dat)))
        fp = _cache_file(self.dir, key)
        if not fp.is_file():
            return None
        if sig is None:
            try:
                sig = _sig(dat)
            except OSError:
                return None
        try:
            with open(fp, "rb") as f:
                blob = pickle.load(f)
        except (OSError, pickle.PickleError, EOFError, AttributeError):
            return None
        if not isinstance(blob, dict) or blob.get("version") != CACHE_VERSION:
            return None
        if tuple(blob.get("sig", ())) != tuple(sig):
            return None
        return blob["name"], blob["games"]

    def put(self, dat: Path, name: str, games: list[DatGame], sig=None) -> None:
        key = str(Path(os.path.abspath(dat)))
        if sig is None:
            try:
                sig = _sig(dat)
            except OSError:
                return
        self._write(key, sig, name, games)

    def parse(self, dat: Path, sig=None) -> tuple[str, list[DatGame]]:
        """Nazwa + gry DAT-a — z cache albo świeżo sparsowane (i zapisane)."""
        hit = self.get(dat, sig=sig)
        if hit is not None:
            return hit
        name = (parse_dat_header(dat).get("name") or dat.stem)
        games = list(parse_dat(dat))
        self.put(dat, name, games, sig=sig)
        return name, games

    def prune(self, present: set[str]) -> None:
        """Usuwa pliki cache DAT-ów, których już nie ma (present = zbiór
        aktualnych abspath). Rusza WYŁĄCZNIE pliki o kształcie per-DAT
        (`<20 hex>.pkl`) — inne pliki w tym katalogu (np. `dat_sha1_cache.pkl`)
        zostają nietknięte."""
        import re
        if not self.dir.is_dir():
            return
        shaped = re.compile(r"^[0-9a-f]{20}\.pkl$")
        keep = {_cache_file(self.dir, str(Path(os.path.abspath(k)))).name
                for k in present}
        for fp in self.dir.glob("*.pkl"):
            if shaped.match(fp.name) and fp.name not in keep:
                fp.unlink(missing_ok=True)

    def save(self) -> None:
        return       # zapis per-DAT jest natychmiastowy (put) — nic do zrobienia
