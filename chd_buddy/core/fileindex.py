"""Trwały indeks plików (SQLite) + skaner przyrostowy.

Cel: nie liczyć sum kontrolnych w kółko. Raz zeskanowany plik jest pamiętany
w bazie (ścieżka, rozmiar, mtime, CRC32/MD5/SHA-1); dopóki rozmiar i mtime się
nie zmienią, przy kolejnych skanach sumy NIE są przeliczane. Dzięki temu
katalogi docelowe (także na NAS) można skanować tanio, a pliki raz rozpoznane
"istnieją" dla wszystkich DAT-ów aż do fizycznego przeniesienia.

Zasady:
- Skanujemy WSZYSTKIE wskazane korzenie (źródłowe i docelowe) do jednej bazy.
- Symlinki/junctions są rejestrowane jako linki (is_link=1) i nigdy nie są
  haszowane ani rozwijane — fizyczna tożsamość należy do celu linku.
- Plik nieobecny przy skanie korzenia dostaje missing=1 (nie jest usuwany
  z bazy — NAS może być chwilowo odpięty); pojawi się znów => missing=0.
- --full wymusza ponowne policzenie sum mimo zgodnego (rozmiar, mtime).
- Dla .chd można podać próbnik (chd_prober), który zwraca SHA-1 ZAWARTOŚCI
  z nagłówka CHD (chdman info) — to nim CHD trafia w DAT-y bez ekstrakcji.

Ścieżki przechowywane są absolutnie (os.path.abspath, bez rozwiązywania
symlinków). Windows nie rozróżnia wielkości liter, ale nasz własny skan
produkuje spójne ścieżki, więc UNIQUE po ścieżce wystarcza.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import stat as stat_mod
import threading
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from .settings import app_base_dir
from . import netguard
from .storage import same_volume

INDEX_DB_FILENAME = "chd_buddy_index.sqlite3"

# Próbnik zawartości CHD: path -> hex SHA-1 zawartości ("" gdy nieznane).
ChdProber = Callable[[Path], object]   # str (data_sha1) albo (data_sha1, cd_tracks, cd_typed)
# Callback postępu: (liczba widzianych plików, aktualna ścieżka).
FileCB = Callable[[int, Path], None]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL DEFAULT 0,
    mtime_ns INTEGER NOT NULL DEFAULT 0,
    crc32 TEXT NOT NULL DEFAULT '',
    md5 TEXT NOT NULL DEFAULT '',
    sha1 TEXT NOT NULL DEFAULT '',
    data_sha1 TEXT NOT NULL DEFAULT '',
    is_link INTEGER NOT NULL DEFAULT 0,
    missing INTEGER NOT NULL DEFAULT 0,
    scanned_at TEXT NOT NULL DEFAULT '',
    -- mtime_ns pliku w chwili NIEUDANEJ głębokiej identyfikacji CHD:
    -- porażka też jest wynikiem — nie mielimy tego samego pliku co skan.
    deep_fail INTEGER NOT NULL DEFAULT 0,
    -- CHD: czy KONTENER zgadza się z medium gry w DAT (createcd vs createdvd).
    -- -1 = niesprawdzony, 0 = zgodny, 1 = NIEZGODNY (np. gra DVD spakowana jako
    -- CD) => „do naprawy" (skan sam to wykrywa, nie tylko po treści).
    bad_container INTEGER NOT NULL DEFAULT -1,
    -- ZIP: czy metoda kompresji jest NIEZGODNA z emulatorami (inne niż store/
    -- deflate — np. ZSTD/LZMA/bzip2). -1 = niesprawdzony, 0 = OK, 1 = ZŁA metoda
    -- => „do naprawy" (przepakowanie na deflate). Skan zapisuje to z centralnego
    -- katalogu ZIP-a (tanio), żeby naprawa NIE otwierała wszystkich zipów.
    bad_zip_method INTEGER NOT NULL DEFAULT -1,
    tz INTEGER NOT NULL DEFAULT -1,
    -- CHD gry CD: czy UKŁAD ścieżek (liczba/rodzaj torów) zgadza się z DAT.
    -- -1 = niesprawdzony, 1 = zgodny. Odbudowa CHD pomija zgodne BEZ czytania
    -- nagłówka z NAS (dawniej każdy przebieg sprawdzał setki PSX/Saturn/DC).
    layout_ok INTEGER NOT NULL DEFAULT -1,
    -- CHD: z NAGŁÓWKA czytanego przy skanie (chdman info — i tak czytany dla
    -- data_sha1): liczba ścieżek CD w metadanych i czy kontener jest „CD"
    -- (createcd). -1 = nieznane. Planowanie naprawy porównuje je z DAT-em BEZ
    -- czytania nagłówków z NAS.
    cd_tracks INTEGER NOT NULL DEFAULT -1,
    cd_typed INTEGER NOT NULL DEFAULT -1,
    -- HARDLINK znany programowi: normcase ścieżki pliku, z którym ten wpis
    -- dzieli treść fizycznie (program go utworzył albo wykrył). Hardlink nie
    -- jest reparse pointem, więc skan widzi go jak zwykły plik — bez tej wiedzy
    -- planowanie musiało pytać NAS (same_file) o każdą kopię. '' = nieznane.
    link_of TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_files_sha1 ON files(sha1);
CREATE INDEX IF NOT EXISTS idx_files_crc32 ON files(crc32);
CREATE INDEX IF NOT EXISTS idx_files_md5 ON files(md5);
CREATE INDEX IF NOT EXISTS idx_files_data_sha1 ON files(data_sha1);
CREATE INDEX IF NOT EXISTS idx_files_size_mtime ON files(size, mtime_ns);
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY,
    archive TEXT NOT NULL,
    name TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    crc32 TEXT NOT NULL DEFAULT '',
    md5 TEXT NOT NULL DEFAULT '',
    sha1 TEXT NOT NULL DEFAULT '',
    UNIQUE(archive, name)
);
CREATE INDEX IF NOT EXISTS idx_members_crc ON members(crc32, size);
CREATE INDEX IF NOT EXISTS idx_members_sha1 ON members(sha1);
CREATE INDEX IF NOT EXISTS idx_members_archive ON members(archive);
"""

# Archiwa, których zawartość indeksujemy (CRC32+rozmiar z metadanych —
# bez dekompresji; SHA-1 weryfikowany przy wypakowaniu).
# .7z wymaga opcjonalnego py7zr (pip install .[archives]).
ARCHIVE_EXTS = {"zip", "7z"}

_HASH_CHUNK = 4 * 1024 * 1024  # 4 MiB — duże bloki opłacają się na NAS/SMB


def default_db_path() -> Path:
    """Domyślna lokalizacja bazy — przenośnie, obok exe/projektu."""
    return app_base_dir() / INDEX_DB_FILENAME


def count_files(root: Path, cancel=None, skip_dirs: Optional[set] = None) -> int:
    """Szybko liczy pliki pod `root` (sam scandir, bez stat/hashowania) — daje
    MIANOWNIK do paska „plik X z Y". Pomija artefakty tymczasowe i NIE wchodzi
    w dowiązane katalogi (jak `_walk`).

    `skip_dirs` — normcase-owe ścieżki poddrzew liczonych OSOBNO (nie schodzimy
    w nie), by mianownik zgadzał się z faktycznym zakresem skanu (ten sam wyjątek
    co w `scan`), inaczej pasek nie dobija do 100%."""
    n = 0
    stack = [Path(root)]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if _is_temp_artifact(e.name, is_dir):
                    continue
                if is_dir:
                    try:
                        if is_reparse_stat(e.stat(follow_symlinks=False)):
                            continue          # link do katalogu — nie wchodzimy
                    except OSError:
                        continue
                    if skip_dirs and os.path.normcase(e.path) in skip_dirs:
                        continue              # liczone osobno (Faza 1)
                    stack.append(Path(e.path))
                else:
                    n += 1
    return n


class HashAborted(Exception):
    """Hashowanie przerwane przez użytkownika (cancel) w trakcie czytania."""


def hash_file(path: Path, on_progress=None, cancel=None) -> tuple[str, str, str]:
    """Liczy (crc32, md5, sha1) w jednym przebiegu po pliku.

    on_progress(done_bytes, total_bytes) — wołane co porcję, żeby GUI pokazało
    postęp BAJTOWY w obrębie jednego wielkiego pliku (CHD/ISO/RVZ po kilka GB,
    gdzie samo liczenie sum trwa minuty).

    cancel — threading.Event: sprawdzany co blok; ustawiony → HashAborted (żeby
    „Przerwij" reagował także W ŚRODKU wielkiego pliku, nie dopiero po nim)."""
    crc = 0
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    try:
        total = os.path.getsize(path)
    except OSError:
        total = 0
    done = 0
    with open(path, "rb") as fh:
        while True:
            if cancel is not None and cancel.is_set():
                raise HashAborted()
            chunk = fh.read(_HASH_CHUNK)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
            md5.update(chunk)
            sha1.update(chunk)
            if on_progress is not None:
                done += len(chunk)
                on_progress(done, total)
    return f"{crc & 0xFFFFFFFF:08x}", md5.hexdigest(), sha1.hexdigest()


def is_reparse_stat(st: os.stat_result) -> bool:
    """Czy wpis to reparse point (symlink/junction) — po lstat."""
    if stat_mod.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    reparse = getattr(stat_mod, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & reparse)


# Artefakty robocze kombajnu — NIGDY nie indeksowane (żywe pliki tymczasowe
# naprawy/ekstrakcji/dedupu nie mogą stać się kandydatami dopasowania).
_TEMP_DIR_PREFIXES = ("chdbuddy_", "chddeep_", "chd_buddy_", ".rh_upload_")
_TEMP_FILE_MARKERS = (".rtcheck.", ".chdbuddy_extract_tmp",
                      ".chdbuddy_dedup_tmp", ".chd_tmp", ".json.tmp",
                      # przerwana wysyłka / podmiana symlinku na hardlink —
                      # resztki NIE mogą trafić do indeksu jako zwykłe pliki
                      ".chdbuddy_move_tmp", ".rh_hardlink_tmp",
                      ".chdbuddy_rebuild_tmp")


def _is_temp_artifact(name: str, is_dir: bool) -> bool:
    low = name.lower()
    if is_dir:
        return low.startswith(_TEMP_DIR_PREFIXES)
    return (low.startswith("chdbuddy_tmp_")
            or any(m in low for m in _TEMP_FILE_MARKERS))


def _list_dir(d: Path) -> list:
    """Jeden katalog: [(ścieżka, lstat, czy_katalog, czy_link)] bez plików
    tymczasowych kombajnu. Na Windows `DirEntry.stat(follow_symlinks=False)`
    bierze dane z listingu (bez dodatkowej rundy SMB). OSError z scandir leci
    wyżej (obsługa zaniku sieci w obchodzie)."""
    out = []
    with os.scandir(d) as it:
        entries = list(it)
    for e in entries:
        try:
            st = e.stat(follow_symlinks=False)
            is_dir = e.is_dir(follow_symlinks=False)
        except OSError:
            continue
        if _is_temp_artifact(e.name, is_dir):
            continue
        out.append((Path(e.path), st, is_dir, is_reparse_stat(st)))
    return out


def _walk(root: Path, skip_dirs: Optional[set] = None, cancel=None,
          workers: int = 1) -> Iterator[tuple[Path, os.stat_result, bool]]:
    """Rekurencyjny scandir; yielduje (ścieżka, lstat, czy_link).

    W linkowane katalogi NIE wchodzi (yielduje je jako linki) — inaczej
    zdeduplikowana kolekcja byłaby liczona wielokrotnie. Katalogi i pliki
    tymczasowe kombajnu są pomijane w całości.

    `skip_dirs` — zbiór ścieżek (normcase, absolutne) katalogów, w które NIE
    schodzimy (np. już przeskanowane w tej samej rundzie z innego korzenia).
    Sam pokrywający korzeń zostaje przeskanowany, tylko te podkatalogi pomijamy
    — bez utraty pokrycia reszty drzewa (ważne: pominięte pliki NIE są liczone
    jako widziane, więc nie stają się „duchami").

    `workers` > 1 — katalogi listowane RÓWNOLEGLE (NAS: każdy scandir to
    runda sieciowa ~33 ms przez Tailscale; tysiące katalogów gier bin/cue
    szeregowo = minuty samego czekania). Kolejność plików wtedy dowolna.
    """
    def _dispatch(listing, push):
        for path, st, is_dir, link in listing:
            if is_dir:
                if link:
                    yield path, st, True
                elif skip_dirs and os.path.normcase(str(path)) in skip_dirs:
                    continue                   # już przeskanowany osobno
                else:
                    push(path)
            else:
                yield path, st, link

    def _net_retry(d, err) -> Optional[bool]:
        """NAS zniknął (uśpienie laptopa, restart routera)? — czekaj i
        przeczytaj katalog PONOWNIE; pominięcie oznaczyłoby całe drzewo jako
        „brakujące". True = ponów, False = koniec obchodu (przerwane czekanie
        — skan zauważy przerwanie i niczego nie oznaczy jako brak), None =
        zwykły błąd katalogu (pomiń)."""
        if netguard.is_net_error(err) or not netguard.alive(d):
            return bool(netguard.wait_until_back([d], cancel=cancel))
        return None

    if workers <= 1:
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                listing = _list_dir(d)
            except OSError as err:
                r = _net_retry(d, err)
                if r:
                    stack.append(d)
                elif r is False:
                    return
                continue
            yield from _dispatch(listing, stack.append)
        return

    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    ex = ThreadPoolExecutor(max_workers=workers)
    pending: dict = {}

    def push(d):
        pending[ex.submit(_list_dir, d)] = d

    try:
        push(root)
        while pending:
            if cancel is not None and cancel.is_set():
                return
            done, _ = wait(list(pending), timeout=0.5,
                           return_when=FIRST_COMPLETED)
            for fut in done:
                d = pending.pop(fut)
                try:
                    listing = fut.result()
                except OSError as err:
                    r = _net_retry(d, err)
                    if r:
                        push(d)
                    elif r is False:
                        return
                    continue
                yield from _dispatch(listing, push)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


@dataclass
class ScanStats:
    seen: int = 0          # wszystkie napotkane wpisy (pliki + linki)
    hashed: int = 0        # policzone od nowa
    unchanged: int = 0     # zgodny (rozmiar, mtime) => sumy z bazy
    links: int = 0         # zarejestrowane symlinki/junctions
    filtered: int = 0      # pominięte filtrem rozszerzeń
    missing: int = 0       # oznaczone jako nieobecne pod korzeniem
    errors: int = 0        # błędy odczytu
    bytes_hashed: int = 0
    adopted: int = 0       # przeniesione pliki przejęte z bazy (bez czytania)
    oversize_moved: int = 0   # obce (za duże) przeniesione do ToSort (rename)
    cancelled: bool = False   # przerwany przez użytkownika (postęp zapisany)

    def summary(self) -> str:
        if self.cancelled:
            return (f"PRZERWANY — plików {self.seen}, policzono {self.hashed} "
                    f"({self.bytes_hashed / 2**30:.2f} GiB), zapisane")
        return (f"plików {self.seen}, policzono {self.hashed} "
                f"({self.bytes_hashed / 2**30:.2f} GiB), bez zmian {self.unchanged}, "
                f"przejęte po przenosinach {self.adopted}, "
                f"obce→ToSort {self.oversize_moved}, "
                f"linki {self.links}, brakujące {self.missing}, błędy {self.errors}")


@dataclass
class DupGroup:
    sha1: str
    size: int
    paths: list[str] = field(default_factory=list)


class FileIndex:
    """Baza tożsamości plików + skan przyrostowy."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.db_path))
        self._db.row_factory = sqlite3.Row
        # cache dopasowania w PAMIĘCI (słowniki po sumach) — dziesiątki tysięcy
        # zapytań SELECT przy matchingu całej kolekcji to minuty; wczytanie
        # indeksu raz i dopasowanie w RAM to sekundy. None => nieaktywny.
        self._mcache = None
        # KATALOGI OPUSZCZONE w tym przebiegu (plik skasowany/przeniesiony stąd):
        # normcase → ścieżka. Jedyni kandydaci do „pusty katalog → usuń" —
        # zamiast os.walk całego drzewa na NAS (Wii: 1266 podkatalogów = minuty
        # ciszy przez internet).
        self._vacated: dict = {}
        self._db.executescript(_SCHEMA)
        # migracja starych baz (CREATE IF NOT EXISTS nie dodaje kolumn)
        try:
            self._db.execute(
                "ALTER TABLE files ADD COLUMN deep_fail INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass                       # kolumna już jest
        try:
            self._db.execute(
                "ALTER TABLE files ADD COLUMN bad_container "
                "INTEGER NOT NULL DEFAULT -1")
        except sqlite3.OperationalError:
            pass                       # kolumna już jest
        try:
            self._db.execute(
                "ALTER TABLE files ADD COLUMN bad_zip_method "
                "INTEGER NOT NULL DEFAULT -1")
        except sqlite3.OperationalError:
            pass                       # kolumna już jest
        try:
            # 0.6.95: zip jest TorrentZipem (1) / nie (0) / nie sprawdzono (-1)
            self._db.execute(
                "ALTER TABLE files ADD COLUMN tz INTEGER NOT NULL DEFAULT -1")
        except sqlite3.OperationalError:
            pass                       # kolumna już jest
        try:
            self._db.execute(
                "ALTER TABLE files ADD COLUMN layout_ok "
                "INTEGER NOT NULL DEFAULT -1")
        except sqlite3.OperationalError:
            pass                       # kolumna już jest
        for _col in ("cd_tracks", "cd_typed"):
            try:
                self._db.execute(f"ALTER TABLE files ADD COLUMN {_col} "
                                 "INTEGER NOT NULL DEFAULT -1")
            except sqlite3.OperationalError:
                pass                   # kolumna już jest
        try:
            self._db.execute("ALTER TABLE files ADD COLUMN link_of "
                             "TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass                       # kolumna już jest
        # SHA-1 z NAGŁÓWKA CHD (chdman info „SHA1") = suma dysku w DAT-ach
        # MAME/dir2dat (`<disk sha1>`); '' = jeszcze nie odczytany
        try:
            self._db.execute("ALTER TABLE files ADD COLUMN chd_sha1 "
                             "TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass                       # kolumna już jest
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_files_chd_sha1 "
                         "ON files(chd_sha1)")
        self._db.commit()

    # --- cykl życia ---------------------------------------------------------

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "FileIndex":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # --- skanowanie ---------------------------------------------------------

    def _move_to_tosort(self, path: Path, tosort: str, log) -> bool:
        """Przenosi obcy (za duży) plik do ToSort przez `os.rename` (ten sam
        wolumin → natychmiast). Kolizja nazwy → sufiks. Zwraca True, gdy udane."""
        try:
            dst_dir = Path(tosort)
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / path.name
            i = 1
            while dst.exists():
                dst = dst_dir / f"{path.stem} (dup{i}){path.suffix}"
                i += 1
            os.rename(str(path), str(dst))
            if log:
                log(f"→ ToSort (za duży dla platformy): {path.name}")
            return True
        except OSError as e:
            if log:
                log(f"Nie udało się przenieść {path} do ToSort: {e}")
            return False

    def _persist_hashed(self, cur, key, st, path, suffix, crc, md5, sha1, now,
                        stats, log, chd_prober) -> int:
        """Zapisuje policzony plik: profil CHD (data_sha1), wiersz w `files`,
        członków archiwum. Wspólne dla skanu serialnego i równoległego. Zwraca
        liczbę operacji do licznika commitu."""
        cur.execute(
            "INSERT INTO files(path, size, mtime_ns, crc32, md5, sha1, "
            "                  data_sha1, is_link, missing, scanned_at, "
            "                  cd_tracks, cd_typed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET size=excluded.size, "
            "  mtime_ns=excluded.mtime_ns, crc32=excluded.crc32, "
            "  md5=excluded.md5, sha1=excluded.sha1, "
            "  data_sha1=excluded.data_sha1, is_link=0, missing=0, "
            "  scanned_at=excluded.scanned_at, deep_fail=0, chd_sha1='', "
            "  bad_container=-1, layout_ok=-1, tz=-1, "  # plik się zmienił → od nowa
            "  cd_tracks=excluded.cd_tracks, cd_typed=excluded.cd_typed, "
            "  link_of=''",
            (key, st.st_size, st.st_mtime_ns, crc, md5, sha1, "", now, -1, -1),
        )
        stats.hashed += 1
        stats.bytes_hashed += st.st_size
        added = 1
        if suffix == "chd":
            added += self._know_chd(cur, key, path, chd_prober, log)
        if suffix in ARCHIVE_EXTS:
            cur.execute("DELETE FROM members WHERE archive=?", (key,))
            # NOWE/ZMIENIONE archiwum zawsze skanujemy PEŁNIE (SHA-1 zawartości)
            # — nieznanego pliku nie wolno „poznać" po samym CRC z nagłówka.
            added += self._index_members(cur, key, path, log, full=True)
        return added

    def scan(
        self,
        root: Path,
        *,
        full: bool = False,
        exts: Optional[set[str]] = None,
        max_size: Optional[int] = None,
        oversize_to: Optional[str] = None,
        chd_prober: Optional[ChdProber] = None,
        on_file: Optional[FileCB] = None,
        detail: Optional[Callable[[int, int, str], None]] = None,
        slot_progress: Optional[Callable[[int, int, int, str], None]] = None,
        log: Optional[Callable[[str], None]] = None,
        cancel=None,
        workers: int = 1,
        skip_dirs: Optional[Iterable[Path | str]] = None,
    ) -> ScanStats:
        """Skanuje drzewo `root` przyrostowo do bazy.

        exts — zbiór rozszerzeń bez kropki (lowercase); None = wszystkie pliki.
        UWAGA: plik zaindeksowany wcześniej, a teraz odfiltrowany rozszerzeniem,
        zostanie oznaczony jako missing (filtr zawęża "widziane" wpisy).

        max_size — górny limit rozmiaru (bajty) dla NOWYCH plików surowych. Plik
        większy od największego ROM-u WŁĄCZONYCH DAT-ów nie może być żadnym z nich
        (dopasowanie surowego pliku wymaga równości bajtów → równości rozmiaru),
        więc nie ma po co go czytać — oszczędza I/O na dyskach TB (np. skan kart
        SNES nie hashuje płyt leżących w ToSort). NIE dotyczy archiwów (mogą
        zawierać wiele małych ROM-ów) ani plików JUŻ znanych (te zostają w indeksie,
        nie są oznaczane jako brak). Gdy włączona jest platforma płytowa, limit
        rośnie do jej rozmiaru — czyli w praktyce nie odcina nic błędnie.

        cancel — threading.Event: przerwanie w dowolnym momencie. Wszystko, co
        zdążyliśmy policzyć, JEST ZAPISANE (commit partiami), więc kolejny skan
        kontynuuje, a nie liczy od zera. Przerwany skan NIE oznacza plików jako
        brakujących (nie widzieliśmy całego drzewa).

        workers — liczba wątków HASHUJĄCYCH równolegle (czytanie bajtów). >1
        opłaca się na NAS/SMB i SSD/NVMe (kilka odczytów naraz ukrywa latencję);
        na pojedynczym HDD ZASZKODZI (skakanie głowicy) — wtedy 1. Zapis do
        SQLite zawsze w JEDNYM wątku (baza jednowątkowa). W trybie równoległym
        nie ma bajtowego podpostępu pojedynczego pliku (kilka liczy się naraz).
        """
        root = Path(os.path.abspath(root))
        if not root.is_dir():
            raise NotADirectoryError(f"'{root}' nie jest katalogiem")
        # katalogi już przeskanowane osobno w tej rundzie (np. priorytetowa
        # platforma leżąca POD tym korzeniem): NIE schodzimy w nie ponownie i NIE
        # oznaczamy ich plików jako brakujące (obsłużone przy własnym skanie).
        _skip_norm = {os.path.normcase(os.path.abspath(str(d)))
                      for d in (skip_dirs or [])}
        stats = ScanStats()
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._db.cursor()
        seen: list[str] = []
        pending = 0

        # PULA HASHUJĄCA (opcjonalna): workers>1 → czytamy kilka plików naraz.
        # Każde zadanie bierze SLOT (0..workers-1) na czas czytania i raportuje
        # postęp bajtowy TEGO pliku na własnym pasku (slot_progress) — dzięki
        # temu widać kilka wielkich RVZ/CHD liczonych równolegle.
        workers = max(1, int(workers or 1))
        # listowanie katalogów równolegle wg nośnika: NAS (8 wątków hash) → 16
        # naraz (czysta latencja sieci), SSD → 8, HDD (1) → szeregowo
        list_workers = 1 if workers <= 1 else min(32, workers * 2)
        ex = None
        inflight: list = []            # (future, key, st, path, suffix) FIFO
        max_inflight = workers * 3
        slot_pool = list(range(workers))
        slot_lock = threading.Lock()

        def _hash_job(p: Path):
            with slot_lock:
                sl = slot_pool.pop() if slot_pool else 0
            try:
                cb = None
                if slot_progress is not None:
                    cb = (lambda dn, tt, _s=sl, _nm=p.name:
                          slot_progress(_s, dn, tt, _nm))
                return netguard.call(
                    lambda: hash_file(p, on_progress=cb, cancel=cancel), p,
                    what=f"odczyt {p.name}", cancel=cancel)
            finally:
                with slot_lock:
                    slot_pool.append(sl)
                if slot_progress is not None:
                    slot_progress(sl, 0, -1, "")     # zwolnij pasek slotu

        if workers > 1:
            from concurrent.futures import ThreadPoolExecutor
            ex = ThreadPoolExecutor(max_workers=workers)

        def _drain(keep: int) -> int:
            """Zapisuje wyniki najstarszych zadań, aż w locie zostanie ≤ keep.
            Zwraca liczbę dopisanych operacji (do licznika commitu)."""
            delta = 0
            while len(inflight) > keep:
                fut, k, s, p, suf = inflight.pop(0)
                try:
                    crc, md5, sha1 = fut.result()
                except HashAborted:
                    continue                 # przerwane — pętla i tak zakończy
                except OSError as e:
                    stats.errors += 1
                    if log:
                        log(f"BŁĄD odczytu: {p} ({e})")
                    continue
                except Exception as e:       # jeden zły plik ≠ śmierć całego skanu
                    # np. MemoryError na ogromnym pliku, nieoczekiwany błąd w
                    # hash_file — zalicz błąd, POMIŃ ten plik i skanuj dalej,
                    # zamiast wysypać cały „Znajdź naprawy" i porzucić pulę wątków.
                    stats.errors += 1
                    if log:
                        log(f"BŁĄD hashowania: {p} ({e!r})")
                    continue
                delta += self._persist_hashed(cur, k, s, p, suf, crc, md5,
                                              sha1, now, stats, log, chd_prober)
            return delta

        try:
            cancelled = False
            for path, st, link in _walk(root, _skip_norm or None, cancel,
                                        list_workers):
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break                      # to, co policzone, zostaje w bazie
                key = str(path)
                stats.seen += 1
                if on_file:
                    on_file(stats.seen, path)

                if link:
                    stats.links += 1
                    seen.append(key)
                    # CEL symlinku do indeksu (link_of) — RAZ, gdy link nowy albo
                    # zmieniony (mtime). Dopasowanie porównuje z indeksem zamiast
                    # pytać NAS o każdy link (islink+readlink+exists = 3 rundy SMB
                    # na grę → „20 s bez postępu" w Znajdź naprawy, 29.09).
                    old = cur.execute("SELECT mtime_ns, link_of, is_link FROM files "
                                      "WHERE path=?", (key,)).fetchone()
                    tgt = (old["link_of"] if old is not None and old["is_link"]
                           and old["mtime_ns"] == st.st_mtime_ns and old["link_of"]
                           else "")
                    if not tgt:
                        try:
                            t = os.readlink(str(path))
                            if not os.path.isabs(t):
                                t = os.path.join(os.path.dirname(str(path)), t)
                            tgt = os.path.normcase(os.path.abspath(
                                t.replace("\\\\?\\", "")))
                        except OSError:
                            tgt = ""
                    cur.execute(
                        "INSERT INTO files(path, size, mtime_ns, is_link, missing, "
                        "                  scanned_at, link_of) "
                        "VALUES (?, 0, ?, 1, 0, ?, ?) "
                        "ON CONFLICT(path) DO UPDATE SET is_link=1, missing=0, "
                        "  mtime_ns=excluded.mtime_ns, scanned_at=excluded.scanned_at, "
                        "  link_of=excluded.link_of",
                        (key, st.st_mtime_ns, now, tgt),
                    )
                    pending += 1
                else:
                    suffix = path.suffix.lower().lstrip(".")
                    if exts is not None and suffix not in exts:
                        stats.filtered += 1
                        continue
                    row = cur.execute(
                        "SELECT size, mtime_ns, sha1, data_sha1, missing, cd_tracks, "
                        "layout_ok, bad_container FROM files WHERE path=?",
                        (key,),
                    ).fetchone()
                    # SIZE CAP: nowy plik surowy większy niż największy ROM włączonych
                    # DAT-ów → nie może być żadnym z nich; nie czytamy go. Znany plik
                    # zostaje znany (dopisz do seen, by nie oznaczyć „brak"). Archiwa
                    # pomijamy z capa (mogą mieścić wiele małych ROM-ów).
                    if (max_size is not None and st.st_size > max_size
                            and suffix not in ARCHIVE_EXTS):
                        # Obcy dla platformy (za duży). Gdy ToSort na TYM SAMYM
                        # woluminie → przenieś OD RAZU (rename = darmowy, bez
                        # czytania). Inny wolumin = kopiowanie (wolne) → nie ruszamy
                        # podczas skanu (zostaje jak dotąd, tylko nie hashujemy).
                        # TYLKO pliki NIEZNANE indeksowi (row is None): plik już
                        # zaindeksowany (dopasowany wcześniej, np. do platformy teraz
                        # WYŁĄCZONEJ) NIE może zostać po cichu przeniesiony ze skanu —
                        # to zaskoczyłoby usera i zerwało ścieżki do niego.
                        if (oversize_to and suffix != "m3u" and row is None
                                and same_volume(path.parent, oversize_to)
                                and self._move_to_tosort(path, oversize_to, log)):
                            stats.oversize_moved += 1     # stara ścieżka zniknie
                        else:
                            if row is not None:
                                seen.append(key)
                            stats.filtered += 1
                        continue
                    seen.append(key)
                    fresh = (row is not None and not full
                             and row["size"] == st.st_size
                             and row["mtime_ns"] == st.st_mtime_ns
                             and row["sha1"] != "")
                    if fresh:
                        stats.unchanged += 1
                        if row["missing"]:
                            cur.execute("UPDATE files SET missing=0 WHERE path=?", (key,))
                            pending += 1
                        # wiedza o CHD (profil/układ/kontener): bliźniak z
                        # indeksu, chdman tylko gdy wciąż nieznana (raz — potem
                        # planowanie naprawy bierze ją z indeksu, bez NAS)
                        if path.suffix.lower() == ".chd":
                            k = self._know_chd(cur, key, path, chd_prober, log)
                            if k:
                                stats.adopted += 1
                                pending += k
                        # backfill/UPGRADE członków archiwum: brak członków ALBO
                        # członkowie bez SHA-1 (stary skan szybki = tylko CRC) →
                        # doskanuj PEŁNIE (SHA-1 zawartości). „Zawsze wiemy co
                        # dokładnie mamy" — nie ufamy samemu CRC przy operacjach.
                        if path.suffix.lower().lstrip(".") in ARCHIVE_EXTS:
                            n = cur.execute("SELECT COUNT(*) FROM members WHERE archive=?",
                                            (key,)).fetchone()[0]
                            no_sha = cur.execute(
                                "SELECT COUNT(*) FROM members WHERE archive=? AND "
                                "(sha1='' OR sha1 IS NULL)", (key,)).fetchone()[0]
                            if n == 0 or no_sha:
                                # NAJPIERW z bliźniaka w indeksie (hardlink/kopia —
                                # ta sama suma CAŁEGO pliku = ta sama zawartość):
                                # bez otwierania zipa na NAS. Hardlinki z naprawy
                                # 0.6.81 (przed poprawką) miały sumy bez członków →
                                # skan otwierał i hashował KAŻDY link (~0,3 s/plik).
                                if self._borrow_members(cur, key, row["sha1"],
                                                        st.st_size):
                                    stats.adopted += 1
                                    pending += 1
                                else:
                                    cur.execute("DELETE FROM members WHERE archive=?",
                                                (key,))
                                    pending += self._index_members(cur, key, path, log,
                                                                   full=True)
                        # NIE otwieramy tu ZIP-a, by wykryć metodę kompresji: na NAS
                        # to SZEREGOWE otwarcie centralnego katalogu KAŻDEGO zipa =
                        # jedna runda SMB na plik (sieć/CPU ~0%, sama latencja) →
                        # skan przyrostowy „stoi" przy dużej kolekcji (regresja 0.6.16).
                        # `bad_zip_method` ustawia `_index_members` przy indeksowaniu
                        # członków (nowe/zmienione zipy i upgrade bez SHA-1 — wyżej),
                        # więc flaga i tak powstaje, gdy zip jest OTWIERANY z innego
                        # powodu. Zipy tworzone przez program są deflate; niezgodne
                        # (zstd/lzma) z zewnątrz przychodzą jako NOWE → złapane.
                    else:
                        # PLIK PRZENIESIONY (np. ręcznie w Eksploratorze)?
                        # Wiedza podąża za treścią: ta sama nazwa + rozmiar +
                        # mtime_ns, a stara ścieżka już nie istnieje => przejmij
                        # sumy/data_sha1/deep_fail/członków BEZ czytania danych.
                        if row is None and not full:
                            if self._adopt_moved(cur, key, path, st, now):
                                stats.adopted += 1
                                pending += 1
                                continue
                            # HARDLINK znanego pliku pod NOWĄ ścieżką (np. po
                            # zmianie katalogów DAT-ów): ten sam plik fizyczny
                            # (identyfikator pliku) → sumy bez czytania danych
                            if self._adopt_hardlink(cur, key, path, st, now):
                                stats.adopted += 1
                                pending += 1
                                continue
                        if ex is not None:
                            # RÓWNOLEGLE: zleć hash do puli (czyta bajty — na NAS/SSD
                            # kilka naraz ukrywa latencję), zapis do SQLite ODROCZONY
                            # i wyłącznie w tym wątku (SQLite jednowątkowe). Postęp
                            # bajtowy każdego pliku leci na własny pasek (slot).
                            inflight.append(
                                (ex.submit(_hash_job, path), key, st, path, suffix))
                            if len(inflight) >= max_inflight:
                                pending += _drain(keep=workers)
                        else:
                            try:
                                _dcb = ((lambda dn, tt: detail(dn, tt, path.name))
                                        if detail is not None else None)
                                crc, md5, sha1 = netguard.call(
                                    lambda: hash_file(path, on_progress=_dcb,
                                                      cancel=cancel),
                                    path, what=f"odczyt {path.name}",
                                    cancel=cancel)
                            except HashAborted:
                                cancelled = True
                                break
                            except OSError as e:
                                stats.errors += 1
                                if log:
                                    log(f"BŁĄD odczytu: {path} ({e})")
                                continue
                            pending += self._persist_hashed(
                                cur, key, st, path, suffix, crc, md5, sha1, now,
                                stats, log, chd_prober)

                if pending >= 200:  # commituj partiami — długi skan NAS nie przepada
                    self._db.commit()
                    pending = 0

            # obchód skończony przez przerwane czekanie na NAS, albo wolumin
            # zniknął na sam koniec — NIE oznaczaj brakujących (niepełny obraz)
            if cancel is not None and cancel.is_set():
                cancelled = True
            elif not netguard.alive(root):
                if not netguard.wait_until_back([root], cancel=cancel):
                    cancelled = True
            if cancelled:
                # przerwano: porzuć zadania w locie (przeliczą się przy kolejnym
                # skanie), zapisz to, co już policzone
                if ex is not None:
                    ex.shutdown(wait=False, cancel_futures=True)
                # NIE oznaczamy brakujących — nie obeszliśmy całego drzewa
                self._db.commit()
                stats.cancelled = True
                if log:
                    log(f"PRZERWANO skan {root} — zapisano {stats.hashed} "
                        f"policzonych plików (kolejny skan dokończy resztę).")
                return stats
            # dokończ zaległe zadania puli (zapis w tym wątku), potem zamknij pulę
            if ex is not None:
                pending += _drain(keep=0)
                ex.shutdown(wait=True)
            stats.missing = self._mark_missing(root, seen, _skip_norm)
            self._db.commit()
            # TorrentZip: jednorazowo dla zipów bez oznaczenia (stare wpisy)
            self.fill_tz(root, workers=max(1, workers), detail=detail,
                         log=log, cancel=cancel)
            return stats
        finally:
            # ZAWSZE domknij pulę wątków, nawet gdy pętla wysypała się
            # nieoczekiwanie — inaczej wątki-workery wiszą do końca procesu.
            if ex is not None:
                ex.shutdown(wait=False, cancel_futures=True)

    def set_tz(self, path: Path | str, value: int) -> None:
        key = str(Path(os.path.abspath(path)))
        self._db.execute("UPDATE files SET tz=? WHERE path=?", (int(value), key))
        self._db.commit()

    def fill_tz(self, root, *, workers: int = 8, detail=None, log=None,
                cancel=None) -> int:
        """Oznacza zipy pod `root` bez znanego `tz` (-1): TorrentZip czy nie.
        Czyta tylko KOŃCÓWKĘ pliku, RÓWNOLEGLE (NAS), raz na TREŚĆ: hardlinki
        i kopie tej samej treści (sha1+rozmiar) dostają wynik bez odczytu.
        Przerywalne; niedokończone zostają -1 (następny skan dokończy)."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .paths import dir_prefix
        from .torrentzip import torrentzip_status
        pref = dir_prefix(root)
        rows = self._db.execute(
            "SELECT path, sha1, size FROM files WHERE tz=-1 AND missing=0 "
            "AND is_link=0 AND lower(path) LIKE '%.zip'").fetchall()
        groups: dict = {}
        for r in rows:
            if not os.path.normcase(r["path"]).startswith(pref):
                continue
            groups.setdefault(((r["sha1"] or "").lower(), r["size"]),
                              []).append(r["path"])
        if not groups:
            return 0
        if log:
            log(f"TorrentZip: sprawdzam {len(groups)} zipów bez oznaczenia "
                f"({root}) — jednorazowo, odczyt końcówki pliku.")
        done = 0
        total = len(groups)
        with ThreadPoolExecutor(max_workers=max(1, min(32, workers * 2))) as ex:
            futs = {ex.submit(torrentzip_status, paths[0]): (k, paths)
                    for k, paths in groups.items()}
            for f in as_completed(futs):
                if cancel is not None and cancel.is_set():
                    ex.shutdown(wait=False, cancel_futures=True)
                    break
                (sha1, size), paths = futs[f]
                v = f.result()
                if v >= 0:
                    if sha1:
                        self._db.execute(
                            "UPDATE files SET tz=? WHERE sha1=? AND size=? AND tz=-1",
                            (v, sha1, size))
                    else:
                        self._db.executemany("UPDATE files SET tz=? WHERE path=?",
                                             [(v, p) for p in paths])
                done += 1
                if done % 200 == 0 or done == total:
                    self._db.commit()
                    if detail:
                        detail(done, total, f"TorrentZip: {os.path.basename(paths[0])}")
        self._db.commit()
        if detail:
            detail(-1, 0, "")
        return done

    def prune_ghosts(self, log=None, skip_roots=None) -> int:
        """Oznacza missing=1 wpisy, których PLIK już nie istnieje.

        Skan robi to per katalog (`_mark_missing`) dla KAŻDEGO odwiedzonego
        korzenia — więc wpisy pod ŚWIEŻO przeskanowanymi katalogami są już
        poprawne. Ta funkcja łapie tylko korzenie, które ZNIKNĘŁY całkiem
        (np. skasowane stare `roms`).

        `skip_roots` — katalogi przeskanowane w tym przebiegu: ich wpisy
        POMIJAMY (już obsłużone). KLUCZOWE na NAS: bez tego `lexists` po całym
        indeksie (100k+ wpisów) to 100k+ zapytań SMB w ciszy — skan „stoi".
        """
        from .paths import dir_prefixes
        skips = dir_prefixes(skip_roots)

        def _under_skip(p: str) -> bool:
            pn = os.path.normcase(p)
            return any(pn.startswith(s) for s in skips)

        n = 0
        cur = self._db.cursor()
        rows = cur.execute("SELECT path FROM files WHERE missing=0").fetchall()
        to_check = [r["path"] for r in rows if not _under_skip(r["path"])]
        # SPRAWDZANIE PO KATALOGACH (nie per plik!): duchy spoza skanowanych
        # korzeni pojawiają się, gdy zniknął CAŁY katalog/korzeń (np. skasowane
        # stare `roms`). Zamiast `lexists` na KAŻDYM pliku (na NAS 100k+ zapytań
        # SMB w ciszy — skan „stoi") sprawdzamy KAŻDY KATALOG raz (cache): plik
        # pod ISTNIEJĄCYM katalogiem zostaje (zweryfikuje go skan tego katalogu),
        # pod ZNIKNIONYM → duch. Redukuje zapytania z liczby PLIKÓW do liczby
        # KATALOGÓW. Pojedynczy skasowany plik w istniejącym, nieskanowanym
        # katalogu złapie skan tego katalogu (per-katalog `_mark_missing`).
        if log and to_check:
            log(f"Indeks: sprawdzam duchy spoza skanowanych katalogów "
                f"({len(to_check)} wpisów, po katalogach)…")
        dir_alive: dict[str, bool] = {}
        checked = 0
        for path in to_check:
            d = os.path.dirname(path)
            alive = dir_alive.get(d)
            if alive is None:
                alive = os.path.lexists(d)
                dir_alive[d] = alive
                checked += 1
                if log and checked % 1000 == 0:
                    log(f"  … sprawdzono {checked} katalogów (duchów: {n})")
            if not alive:
                self._db.execute(
                    "UPDATE files SET missing=1 WHERE path=?", (path,))
                n += 1
        # sieroty: członkowie archiwów, których wiersz-archiwum już NIE MA
        # w bazie. UWAGA: członków archiwów missing=1 ZOSTAWIAMY — to pamięć
        # dla adopcji (przeniesione archiwum przejmuje ich bez ponownego
        # czytania); z dopasowań i tak wypadają (JOIN po missing=0).
        m = self._db.execute(
            "DELETE FROM members WHERE archive NOT IN "
            "(SELECT path FROM files)").rowcount
        if n or m:
            self._db.commit()
            if log:
                log(f"Indeks: oznaczono {n} duchów"
                    + (f", usunięto {m} osieroconych członków archiwów"
                       if m else "") + ".")
        return n

    # Kolumny opisujące TREŚĆ pliku (nie ścieżkę): identyczne bajty = identyczne
    # wartości. Kopiowanie wpisu z bliźniaka (hardlink, przeniesienie) MUSI brać
    # je WSZYSTKIE — dawniej każda ścieżka miała własną listę bez sondy CHD
    # (cd_tracks/layout_ok/bad_container) → skan pytał chdman po NAS o każdy
    # świeży hardlink CHD, pojedynczo (1344 PS1/PS2, 29.09).
    _CONTENT_COLS = ("crc32", "md5", "sha1", "data_sha1", "deep_fail",
                     "bad_container", "bad_zip_method", "layout_ok",
                     "cd_tracks", "cd_typed", "chd_sha1", "tz")
    _PROBE_COLS = ("data_sha1", "deep_fail", "bad_container", "layout_ok",
                   "cd_tracks", "cd_typed", "chd_sha1")

    @classmethod
    def _copy_content(cls, cur, key: str, src, size: int, mtime_ns: int,
                      now: str, link_of: str = "") -> None:
        """Wpis `key` = treść wiersza `src` (wszystkie kolumny treści)."""
        cols = cls._CONTENT_COLS
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        upd = ", ".join(f"{c}=excluded.{c}" for c in cols)
        cur.execute(
            f"INSERT INTO files(path, size, mtime_ns, {names}, is_link, missing, "
            f"                  scanned_at, link_of) "
            f"VALUES (?, ?, ?, {marks}, 0, 0, ?, ?) "
            f"ON CONFLICT(path) DO UPDATE SET size=excluded.size, "
            f"  mtime_ns=excluded.mtime_ns, {upd}, is_link=0, missing=0, "
            f"  scanned_at=excluded.scanned_at, link_of=excluded.link_of",
            (key, size, mtime_ns, *[src[c] for c in cols], now, link_of))

    # wartość „nieznane” kolumn sondy (świeży wpis, zanim cokolwiek sprawdzono)
    _PROBE_UNKNOWN = {"data_sha1": "", "deep_fail": 0, "bad_container": -1,
                      "layout_ok": -1, "cd_tracks": -1, "cd_typed": -1,
                      "chd_sha1": ""}

    @classmethod
    def _borrow_probe(cls, cur, key: str, sha1: str, size: int) -> bool:
        """Wiedza z sondy CHD (profil, układ, kontener, porażka identyfikacji)
        z BLIŹNIAKÓW o tej samej sumie całego pliku — bez chdman na NAS.
        Uzupełnia TYLKO kolumny nieznane u `key`, z dowolnego bliźniaka, który
        je zna. True = coś uzupełniono."""
        if not sha1:
            return False
        row = cur.execute("SELECT * FROM files WHERE path=?", (key,)).fetchone()
        if row is None:
            return False
        unk = cls._PROBE_UNKNOWN
        lacking = [c for c in cls._PROBE_COLS
                   if row[c] is None or row[c] == unk[c]]
        if not lacking:
            return False
        twins = cur.execute(
            "SELECT * FROM files WHERE sha1=? AND size=? AND path<>? "
            "ORDER BY missing", (sha1, size, key)).fetchall()
        upd: dict = {}
        for c in lacking:
            for t in twins:
                if t[c] is not None and t[c] != unk[c]:
                    upd[c] = t[c]
                    break
        if not upd:
            return False
        cur.execute(f"UPDATE files SET {', '.join(f'{c}=?' for c in upd)} "
                    f"WHERE path=?", (*upd.values(), key))
        return True

    @staticmethod
    def _chd_unknown(r) -> bool:
        """CHD wymaga sondy: brak profilu treści ALBO nieznany układ ścieżek
        przy niepotwierdzonym kontenerze."""
        return (not r["data_sha1"]
                or (r["cd_tracks"] < 0 and r["layout_ok"] != 1
                    and r["bad_container"] < 0))

    def _know_chd(self, cur, key: str, path: Path, prober, log) -> int:
        """JEDYNA droga skanu do wiedzy o CHD (plik nowy i znany): najpierw
        bliźniak z indeksu (hardlink/kopia), chdman na NAS tylko dla tego, co
        wciąż nieznane. Zwraca liczbę zapisów (0 = nic nie trzeba było)."""
        row = cur.execute("SELECT * FROM files WHERE path=?", (key,)).fetchone()
        if row is None or not self._chd_unknown(row):
            return 0
        ops = 0
        if self._borrow_probe(cur, key, row["sha1"], row["size"]):
            ops += 1
            row = cur.execute("SELECT * FROM files WHERE path=?",
                              (key,)).fetchone()
            if not self._chd_unknown(row):
                return ops
        if prober is None:
            return ops
        ds, trk, cdt = self._probe_chd(prober, path, log)
        if ds and not row["data_sha1"]:
            cur.execute("UPDATE files SET data_sha1=? WHERE path=?", (ds, key))
            ops += 1
        if trk >= 0 or cdt >= 0:
            cur.execute("UPDATE files SET cd_tracks=?, cd_typed=? WHERE path=?",
                        (trk, cdt, key))
            ops += 1
        return ops

    def fill_from_twins(self, log=None) -> int:
        """JEDEN przebieg po indeksie (bez NAS): każdy CHD z niepełną wiedzą
        o treści dostaje ją od bliźniaków (hardlink/kopia, ta sama suma). Woła
        się przed KAŻDĄ fazą, która sonduje CHD (skan, sonda CHD) — żadna nie
        może pytać chdman o coś, co indeks już wie (29.09: 2942 hardlinków
        REDUMP w fazie sondy po poprawce samego skanu)."""
        rows = self._db.execute(
            "SELECT path, sha1, size FROM files WHERE missing=0 AND is_link=0 "
            "AND sha1<>'' AND lower(path) LIKE '%.chd' AND (data_sha1='' "
            "OR bad_container=-1 OR layout_ok=-1 OR cd_tracks=-1 "
            "OR cd_typed=-1 OR chd_sha1='')").fetchall()
        cur = self._db.cursor()
        n = 0
        for r in rows:
            if self._borrow_probe(cur, r["path"], r["sha1"], r["size"]):
                n += 1
        self._db.commit()
        if n and log:
            log(f"Wiedza o CHD przejęta od bliźniaków (bez chdman): {n}")
        return n

    @staticmethod
    def _adopt_moved(cur, key: str, path: Path, st, now: str) -> bool:
        """Przejmuje wpis PRZENIESIONEGO pliku bez ponownego liczenia sum.

        Dopasowanie: identyczna NAZWA pliku + rozmiar + mtime_ns (mtime w
        nanosekundach przeżywa move/rename na tym samym i między woluminami
        NTFS), a stara ścieżka już nie wskazuje pliku. Przenosi też członków
        archiwum i pamięć o nieudanej identyfikacji CHD (deep_fail).
        Dzięki temu ręczne przenosiny setek GB nie kosztują godzin haszowania.
        """
        cands = cur.execute(
            "SELECT * FROM files WHERE size=? AND mtime_ns=? AND is_link=0 "
            "AND sha1<>'' AND path<>?",
            (st.st_size, st.st_mtime_ns, key)).fetchall()
        name = path.name.lower()
        matches = []
        for c in cands:
            if Path(c["path"]).name.lower() != name:
                continue
            if os.path.lexists(c["path"]):
                continue                     # stary plik wciąż istnieje — to kopia
            matches.append(c)
        if len(matches) != 1:
            return False                     # niejednoznaczne => policz normalnie
        old = matches[0]
        FileIndex._copy_content(cur, key, old, st.st_size, st.st_mtime_ns, now)
        cur.execute("UPDATE members SET archive=? WHERE archive=?",
                    (key, old["path"]))
        cur.execute("DELETE FROM files WHERE path=?", (old["path"],))
        return True

    @staticmethod
    def _borrow_members(cur, key: str, sha1: str, size: int) -> int:
        """Członkowie archiwum `key` skopiowani z INNEGO wpisu o tej samej sumie
        SHA-1 i rozmiarze CAŁEGO pliku (identyczne bajty = identyczna
        zawartość), który ma pełnych członków (z SHA-1). Zwraca liczbę
        skopiowanych (0 = brak bliźniaka — trzeba otworzyć archiwum)."""
        if not sha1:
            return 0
        # także wpisy BRAKUJĄCE (missing=1): plik zniknął, ale jego członkowie
        # to wciąż prawda o tej treści (ta sama suma całego archiwum). Dawniej
        # hardlink, którego cel usunięto/przeniesiono, tracił jedyne źródło
        # członków → skan otwierał go na NAS (1373 zipy Mega Drive, ~0,3 s/plik).
        twins = cur.execute(
            "SELECT path FROM files WHERE sha1=? AND size=? AND path<>? "
            "ORDER BY missing", (sha1, size, key)).fetchall()
        for t in twins:
            src = t[0]
            n, no_sha = cur.execute(
                "SELECT COUNT(*), SUM(CASE WHEN sha1='' OR sha1 IS NULL "
                "THEN 1 ELSE 0 END) FROM members WHERE archive=?",
                (src,)).fetchone()
            if not n or no_sha:
                continue
            cur.execute("DELETE FROM members WHERE archive=?", (key,))
            cur.execute(
                "INSERT OR IGNORE INTO members(archive, name, size, crc32, md5, sha1) "
                "SELECT ?, name, size, crc32, md5, sha1 FROM members WHERE archive=?",
                (key, src))
            return n
        return 0

    @staticmethod
    def _adopt_hardlink(cur, key: str, path: Path, st, now: str) -> bool:
        """Nowa ścieżka będąca HARDLINKIEM pliku już zaindeksowanego: ten sam
        rozmiar i mtime (hardlink dzieli je z celem) ORAZ ten sam identyfikator
        pliku (st_ino+st_dev — sprawdzane os.stat, jedna runda SMB na
        kandydata zamiast czytania całego pliku). Przejmuje sumy, data_sha1 i
        członków; zapisuje link_of."""
        cands = cur.execute(
            "SELECT * FROM files WHERE size=? AND mtime_ns=? AND is_link=0 "
            "AND missing=0 AND sha1<>'' AND path<>? LIMIT 8",
            (st.st_size, st.st_mtime_ns, key)).fetchall()
        if not cands:
            return False
        try:
            me = os.stat(path)
        except OSError:
            return False
        if not me.st_ino:
            return False
        for c in cands:
            try:
                other = os.stat(c["path"])
            except OSError:
                continue
            if other.st_ino != me.st_ino or other.st_dev != me.st_dev:
                continue
            FileIndex._copy_content(cur, key, c, st.st_size, st.st_mtime_ns,
                                    now, os.path.normcase(c["path"]))
            cur.execute("DELETE FROM members WHERE archive=?", (key,))
            cur.execute(
                "INSERT OR IGNORE INTO members(archive, name, size, crc32, md5, sha1) "
                "SELECT ?, name, size, crc32, md5, sha1 FROM members WHERE archive=?",
                (key, c["path"]))
            return True
        return False

    @staticmethod
    def _index_members(cur, key: str, path: Path, log, full: bool = False,
                       on_progress=None) -> int:
        """Indeksuje zawartość archiwum.

        Szybko (full=False): tylko metadane — CRC32+rozmiar z centralnego
        katalogu ZIP-a / nagłówka 7z (bez dekompresji).
        Pełne (full=True): DODATKOWO wypakowuje każdy plik i liczy MD5+SHA-1
        (weryfikacja zawartości + trwały odcisk do dopasowania po SHA-1).
        Gdy policzony CRC nie zgadza się z centralnym katalogiem — ostrzeżenie
        (archiwum uszkodzone), ale wpis i tak trafia z realnymi sumami.

        7z wymaga py7zr — bez niego archiwum zostaje zwykłym plikiem.
        """
        # (name -> (size, crc, md5, sha1)); md5/sha1 puste przy skanie szybkim
        meta: dict[str, tuple[int, str, str, str]] = {}
        bad_method = 0        # ZIP: 1 gdy któryś człon używa metody != store/deflate
        try:
            if path.suffix.lower() == ".7z":
                try:
                    import py7zr
                except ImportError:
                    if log:
                        log(f"7z pominięte (brak py7zr — pip install py7zr): {path.name}")
                    return 0
                with py7zr.SevenZipFile(path) as zf:
                    for i in zf.list():
                        if i.is_directory:
                            continue
                        crc = f"{i.crc32 & 0xFFFFFFFF:08x}" if i.crc32 else ""
                        meta[i.filename] = (i.uncompressed or 0, crc, "", "")
                if full:
                    FileIndex._hash_7z_members(path, meta, log)
            else:
                import zipfile
                with zipfile.ZipFile(path) as zf:
                    for i in zf.infolist():
                        if i.is_dir():
                            continue
                        # metoda kompresji z centralnego katalogu (bez dekompresji)
                        # store=0, deflate=8 → OK; reszta (zstd=93/lzma=14/…) ZŁA
                        if i.compress_type not in (0, 8):
                            bad_method = 1
                        meta[i.filename] = (i.file_size,
                                            f"{i.CRC & 0xFFFFFFFF:08x}", "", "")
                    if full:
                        FileIndex._hash_zip_members(zf, meta, log, path,
                                                    on_progress)
        except Exception as e:  # uszkodzone archiwum nie może ubić skanu
            if log:
                log(f"ARCHIWUM nieczytelne: {path} ({e})")
            return 0
        rows = [(key, name, size, crc, md5, sha1)
                for name, (size, crc, md5, sha1) in meta.items()]
        cur.executemany(
            "INSERT INTO members(archive, name, size, crc32, md5, sha1) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(archive, name) DO UPDATE SET size=excluded.size, "
            "  crc32=excluded.crc32, md5=excluded.md5, sha1=excluded.sha1", rows)
        # ZAPISZ metodę tylko dla .zip (dla .7z pojęcie nie ma sensu → 0);
        # przy okazji: czy to TorrentZip (końcówka pliku — plik i tak czytany)
        if path.suffix.lower() == ".zip":
            from .torrentzip import torrentzip_status
            cur.execute("UPDATE files SET bad_zip_method=?, tz=? WHERE path=?",
                        (bad_method, torrentzip_status(path), key))
        return len(rows)

    @staticmethod
    def _zip_method_flag(path) -> int:
        """1 gdy ZIP używa metody != store/deflate (niezgodne z emulatorami),
        0 gdy OK, -1 gdy nieczytelne. TANIO — tylko centralny katalog (bez
        dekompresji, jeden odczyt)."""
        import zipfile
        try:
            with zipfile.ZipFile(path) as zf:
                for i in zf.infolist():
                    if not i.is_dir() and i.compress_type not in (0, 8):
                        return 1
            return 0
        except Exception:
            return -1

    @staticmethod
    def _hash_zip_members(zf, meta: dict, log, path: Path,
                          on_progress=None) -> None:
        """Wypakowuje strumieniowo każdy plik ZIP-a i liczy CRC/MD5/SHA-1.
        on_progress(done, total, etykieta) — pasek szczegółowy (opcjonalny)."""
        names = list(meta)
        for i, name in enumerate(names, 1):
            crc = 0
            md5 = hashlib.md5()
            sha1 = hashlib.sha1()
            size = 0
            label = f"indeksuję {path.name}: {name} ({i}/{len(names)})"
            try:
                with zf.open(name) as fh:
                    while True:
                        b = fh.read(_HASH_CHUNK)
                        if not b:
                            break
                        crc = zlib.crc32(b, crc)
                        md5.update(b)
                        sha1.update(b)
                        size += len(b)
                        if on_progress is not None:
                            on_progress(size, meta[name][0], label)
            except Exception as e:
                if log:
                    log(f"ARCHIWUM: nie wypakowano {path.name}::{name} ({e})")
                continue
            crc_hex = f"{crc & 0xFFFFFFFF:08x}"
            if log and meta[name][1] and meta[name][1] != crc_hex:
                log(f"UWAGA CRC: {path.name}::{name} centralny {meta[name][1]} "
                    f"!= policzony {crc_hex} (uszkodzone?)")
            meta[name] = (size, crc_hex, md5.hexdigest(), sha1.hexdigest())

    @staticmethod
    def _hash_7z_members(path: Path, meta: dict, log) -> None:
        """Wypakowuje 7z (solid) i liczy CRC/MD5/SHA-1 członków."""
        import py7zr
        try:
            with py7zr.SevenZipFile(path) as zf:
                data = zf.readall()          # {name: BytesIO}
        except Exception as e:
            if log:
                log(f"ARCHIWUM 7z: nie wypakowano {path.name} ({e})")
            return
        for name, bio in data.items():
            if name not in meta:
                continue
            blob = bio.read()
            meta[name] = (len(blob), f"{zlib.crc32(blob) & 0xFFFFFFFF:08x}",
                          hashlib.md5(blob).hexdigest(),
                          hashlib.sha1(blob).hexdigest())

    @staticmethod
    def _probe_chd(prober: ChdProber, path: Path, log) -> tuple:
        """(data_sha1, cd_tracks, cd_typed) — próbnik może zwrócić sam SHA-1
        (str) albo krotkę z danymi nagłówka; brak = ("", -1, -1)."""
        try:
            res = prober(path)
        except Exception as e:  # próbnik nie może ubić skanu
            if log:
                log(f"CHD prober: {path}: {e}")
            return "", -1, -1
        if isinstance(res, tuple):
            ds, trk, cdt = (list(res) + [-1, -1])[:3]
            return ds or "", int(trk), int(cdt)
        return res or "", -1, -1

    def _mark_missing(self, root: Path, seen: Iterable[str],
                      skip_norm: Optional[set] = None) -> int:
        """Oznacza missing=1 wpisy pod `root`, których skan nie zobaczył.

        `skip_norm` — normcase-owe ścieżki poddrzew przeskanowanych OSOBNO w tej
        rundzie: ich wpisów NIE oznaczamy jako brakujące (skan gołego rodzica w
        nie nie schodził, więc ich plików nie ma w `seen` — bez tego wyjątku
        zostałyby błędnie zdegradowane do „brak"). Porównanie po normcase, by
        różnica wielkości liter na Windows nie ominęła wyjątku."""
        prefix = str(root).rstrip("\\/") + os.sep
        cur = self._db.cursor()
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS _seen(path TEXT PRIMARY KEY)")
        cur.execute("DELETE FROM _seen")
        cur.executemany("INSERT OR IGNORE INTO _seen(path) VALUES (?)",
                        ((s,) for s in seen))
        sql = ("UPDATE files SET missing=1 WHERE missing=0 "
               "AND substr(path, 1, ?) = ? "
               "AND path NOT IN (SELECT path FROM _seen)")
        params: list = [len(prefix), prefix]
        skips = [str(s).rstrip("\\/") + os.sep for s in (skip_norm or set())]
        if skips:
            try:
                self._db.create_function("ncase", 1, os.path.normcase,
                                         deterministic=True)
            except TypeError:                      # starszy Python bez kw-argu
                self._db.create_function("ncase", 1, os.path.normcase)
            for sp in skips:
                sql += " AND ncase(substr(path, 1, ?)) <> ?"
                params += [len(sp), sp]
        cur.execute(sql, params)
        return cur.rowcount

    # --- zapytania ------------------------------------------------------------

    def lookup(self, path: Path | str) -> Optional[sqlite3.Row]:
        key = str(Path(os.path.abspath(path)))
        return self._db.execute("SELECT * FROM files WHERE path=?", (key,)).fetchone()

    def members_of(self, archive: Path | str) -> list[sqlite3.Row]:
        """Członkowie (pliki wewnątrz) danego archiwum z indeksu (name, sha1…)."""
        key = str(Path(os.path.abspath(archive)))
        return list(self._db.execute(
            "SELECT * FROM members WHERE archive=?", (key,)).fetchall())

    def build_match_cache(self) -> None:
        """Wczytuje CAŁY indeks (obecne pliki + członków archiwów) do słowników
        w PAMIĘCI po sumach. Dopasowanie całej kolekcji robi dziesiątki tysięcy
        SELECT-ów (minuty); z cache to lookupy w RAM (sekundy). Ważny TYLKO na
        czas dopasowania — po zmianach w indeksie wywołaj `drop_match_cache`."""
        by_sha1: dict = {}
        by_crc: dict = {}
        by_md5: dict = {}
        by_data: dict = {}
        by_chd: dict = {}
        for r in self._db.execute("SELECT * FROM files WHERE missing=0"):
            if r["chd_sha1"]:
                by_chd.setdefault(r["chd_sha1"], []).append(r)
            if r["sha1"]:
                by_sha1.setdefault(r["sha1"], []).append(r)
            if r["crc32"] and r["size"] is not None:
                by_crc.setdefault((r["crc32"], r["size"]), []).append(r)
            if r["md5"]:
                by_md5.setdefault(r["md5"], []).append(r)
            if r["data_sha1"]:
                by_data.setdefault(r["data_sha1"], []).append(r)
        m_sha: dict = {}
        m_crc: dict = {}
        for r in self._db.execute(
                "SELECT m.* FROM members m JOIN files f ON f.path = m.archive "
                "WHERE f.missing=0"):
            if r["sha1"]:
                m_sha.setdefault(r["sha1"], []).append(r)
            if r["crc32"] and r["size"] is not None:
                m_crc.setdefault((r["crc32"], r["size"]), []).append(r)
        self._mcache = {"sha1": by_sha1, "crc": by_crc, "md5": by_md5,
                        "data": by_data, "msha": m_sha, "mcrc": m_crc,
                        "chd": by_chd}
        # miliony wierszy w RAM na czas dopasowania — nie każ pełnemu GC ich
        # przeglądać co kilkanaście sekund (pauza całego programu do ~2 s)
        from .gcpause import settle
        settle()

    def drop_match_cache(self) -> None:
        self._mcache = None

    def find_sha1(self, sha1: str, include_chd_content: bool = True) -> list[sqlite3.Row]:
        """Pliki o danym SHA-1 (opcjonalnie także trafienia w zawartość CHD)."""
        s = sha1.lower()
        if self._mcache is not None:
            res = list(self._mcache["sha1"].get(s, ()))
            if include_chd_content:
                res += self._mcache["data"].get(s, ())
            return res
        q = "SELECT * FROM files WHERE missing=0 AND (sha1=?"
        args: list[str] = [s]
        if include_chd_content:
            q += " OR data_sha1=?"
            args.append(s)
        q += ")"
        return self._db.execute(q, args).fetchall()

    def find_chd_sha1(self, sha1: str) -> list[sqlite3.Row]:
        """Pliki CHD o danym SHA-1 NAGŁÓWKA (suma `<disk>` w DAT-ach MAME)."""
        s = (sha1 or "").lower()
        if not s:
            return []
        if self._mcache is not None:
            return list(self._mcache["chd"].get(s, ()))
        return self._db.execute(
            "SELECT * FROM files WHERE missing=0 AND chd_sha1=?", (s,)).fetchall()

    def set_chd_sha1(self, path: Path | str, sha1: str) -> None:
        key = str(Path(os.path.abspath(path)))
        self._db.execute("UPDATE files SET chd_sha1=? WHERE path=?",
                         ((sha1 or "").lower(), key))
        self._db.commit()

    def find_md5(self, md5: str) -> list[sqlite3.Row]:
        """Pliki o danym MD5 (fallback gdy DAT nie ma/nie trafił SHA-1)."""
        m = md5.lower()
        if self._mcache is not None:
            return list(self._mcache["md5"].get(m, ()))
        return self._db.execute(
            "SELECT * FROM files WHERE missing=0 AND md5=?", (m,)).fetchall()

    def duplicate_groups(self, min_size: int = 1) -> list[DupGroup]:
        """Grupy identycznych plików fizycznych (ten sam SHA-1 i rozmiar)."""
        groups: list[DupGroup] = []
        rows = self._db.execute(
            "SELECT sha1, size FROM files "
            "WHERE missing=0 AND is_link=0 AND sha1 != '' AND size >= ? "
            "GROUP BY sha1, size HAVING COUNT(*) > 1 ORDER BY size DESC",
            (min_size,),
        ).fetchall()
        for r in rows:
            paths = [p["path"] for p in self._db.execute(
                "SELECT path FROM files WHERE sha1=? AND size=? AND missing=0 AND is_link=0 "
                "ORDER BY path",
                (r["sha1"], r["size"]),
            )]
            groups.append(DupGroup(sha1=r["sha1"], size=r["size"], paths=paths))
        return groups

    def find_crc(self, crc32: str, size: int) -> list[sqlite3.Row]:
        """Pliki o danym CRC32 i rozmiarze (fallback, gdy DAT nie ma SHA-1)."""
        c = crc32.lower().zfill(8)
        if self._mcache is not None:
            return list(self._mcache["crc"].get((c, size), ()))
        return self._db.execute(
            "SELECT * FROM files WHERE missing=0 AND crc32=? AND size=?",
            (c, size),
        ).fetchall()

    def find_member_crc(self, crc32: str, size: int) -> list[sqlite3.Row]:
        """Pliki WEWNĄTRZ archiwów o danym CRC32+rozmiarze (archiwum obecne)."""
        c = crc32.lower().zfill(8)
        if self._mcache is not None:
            return list(self._mcache["mcrc"].get((c, size), ()))
        return self._db.execute(
            "SELECT m.* FROM members m JOIN files f ON f.path = m.archive "
            "WHERE f.missing=0 AND m.crc32=? AND m.size=?",
            (c, size),
        ).fetchall()

    def find_member_sha1(self, sha1: str) -> list[sqlite3.Row]:
        s = sha1.lower()
        if self._mcache is not None:
            return list(self._mcache["msha"].get(s, ()))
        return self._db.execute(
            "SELECT m.* FROM members m JOIN files f ON f.path = m.archive "
            "WHERE f.missing=0 AND m.sha1=?",
            (s,),
        ).fetchall()

    def member_name_in(self, archive: str, sha1: str, crc: str,
                        size: int) -> Optional[str]:
        """Nazwa pliku WEWNĄTRZ danego archiwum, dopasowana po SUMIE (SHA-1,
        potem CRC32+rozmiar). Do przepakowania: bierzemy dane po sumie, a nie
        po nazwie (nazwa w źródle może być błędna)."""
        if sha1:
            r = self._db.execute(
                "SELECT name FROM members WHERE archive=? AND sha1=?",
                (archive, sha1.lower())).fetchone()
            if r:
                return r["name"]
        if crc and size:
            r = self._db.execute(
                "SELECT name FROM members WHERE archive=? AND crc32=? AND size=?",
                (archive, crc.lower().zfill(8), size)).fetchone()
            if r:
                return r["name"]
        return None

    def reindex_archive(self, path: Path | str, full: bool = True,
                        on_progress=None) -> None:
        """Przeindeksowuje świeżo utworzone/zmienione archiwum: wpis pliku
        (własne sumy) + członkowie (z SHA-1 gdy full).
        on_progress(done, total, etykieta) — pasek szczegółowy (opcjonalny):
        oba odczyty z NAS (sumy pliku, sumy członków) nie są „ciszą"."""
        p = Path(os.path.abspath(path))
        key = str(p)
        _hp = None
        if on_progress is not None:
            _hl = f"indeksuję {p.name}"

            def _hp(d, t, _cb=on_progress, _l=_hl):
                _cb(d, t, _l)
        crc, md5, sha1 = hash_file(p, on_progress=_hp)
        st = os.lstat(p)
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._db.cursor()
        cur.execute(
            "INSERT INTO files(path, size, mtime_ns, crc32, md5, sha1, "
            "                  is_link, missing, scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?) "
            "ON CONFLICT(path) DO UPDATE SET size=excluded.size, "
            "  mtime_ns=excluded.mtime_ns, crc32=excluded.crc32, "
            "  md5=excluded.md5, sha1=excluded.sha1, is_link=0, missing=0, "
            "  scanned_at=excluded.scanned_at",
            (key, st.st_size, st.st_mtime_ns, crc, md5, sha1, now))
        cur.execute("DELETE FROM members WHERE archive=?", (key,))
        self._index_members(cur, key, p, None, full=full,
                            on_progress=on_progress)
        self._db.commit()

    def record_file(self, path: Path | str, crc32: str, md5: str, sha1: str) -> None:
        """Rejestruje świeżo utworzony plik (np. wypakowany z archiwum)."""
        p = Path(os.path.abspath(path))
        st = os.lstat(p)
        now = datetime.now().isoformat(timespec="seconds")
        self._db.execute(
            "INSERT INTO files(path, size, mtime_ns, crc32, md5, sha1, "
            "                  is_link, missing, scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?) "
            "ON CONFLICT(path) DO UPDATE SET size=excluded.size, "
            "  mtime_ns=excluded.mtime_ns, crc32=excluded.crc32, "
            "  md5=excluded.md5, sha1=excluded.sha1, is_link=0, missing=0, "
            "  scanned_at=excluded.scanned_at, layout_ok=-1, cd_tracks=-1, "
            "  cd_typed=-1, chd_sha1='', link_of='', tz=-1",
            (str(p), st.st_size, st.st_mtime_ns, crc32.lower(), md5.lower(),
             sha1.lower(), now))
        # kopia znanej treści (np. CHD kopiowane dla innej platformy): wynik
        # sondy z bliźniaka — inaczej skan sondowałby ją chdman po NAS
        self._borrow_probe(self._db, str(p), sha1.lower(), st.st_size)
        self._db.commit()

    def all_under(self, root: Path | str, physical_only: bool = True) -> list[sqlite3.Row]:
        """Wszystkie zaindeksowane wpisy pod katalogiem `root`."""
        prefix = str(Path(os.path.abspath(root))).rstrip("\\/") + os.sep
        q = "SELECT * FROM files WHERE missing=0 AND substr(path, 1, ?) = ?"
        if physical_only:
            q += " AND is_link=0"
        return self._db.execute(q, (len(prefix), prefix)).fetchall()

    def count_under(self, root: Path | str, skip=()) -> int:
        """Liczba znanych (nie-brakujących) wpisów pod `root` — SZACUNEK
        mianownika paska skanu z poprzedniego skanu, jednym zapytaniem SQL.
        Zastępuje osobny obchód NAS („liczenie plików") przed skanem, który
        dublował pracę samego skanu. `skip` — poddrzewa skanowane osobno."""
        def _n(r) -> int:
            prefix = str(Path(os.path.abspath(r))).rstrip("/" + os.sep) + os.sep
            return self._db.execute(
                "SELECT COUNT(*) FROM files WHERE missing=0 "
                "AND substr(path, 1, ?) = ?", (len(prefix), prefix)).fetchone()[0]
        total = _n(root)
        rn = os.path.normcase(os.path.abspath(str(root))).rstrip("/" + os.sep) + os.sep
        for sk in skip or ():
            skn = os.path.normcase(os.path.abspath(str(sk)))
            if skn.startswith(rn):
                total -= _n(sk)
        return max(total, 0)

    def identified_chds_under(self, root: Path | str) -> list[sqlite3.Row]:
        """Fizyczne .chd pod `root` z USTALONYM odciskiem treści (data_sha1) —
        filtr w SQL, bez przeglądania całego drzewa w Pythonie (ToSort ma
        dziesiątki tysięcy wpisów, a takich CHD — garstkę)."""
        # prefiks jak w all_under (ścieżki w bazie NIE są normcase — SQL
        # porównuje z rozróżnieniem wielkości liter)
        prefix = str(Path(os.path.abspath(root))).rstrip("/" + os.sep) + os.sep
        return self._db.execute(
            "SELECT * FROM files WHERE missing=0 AND is_link=0 "
            "AND substr(path, 1, ?) = ? AND data_sha1 != '' "
            "AND lower(substr(path, -4)) = '.chd'",
            (len(prefix), prefix)).fetchall()

    def rename(self, old: Path | str, new: Path | str) -> None:
        """Aktualizuje ścieżkę wpisu po przeniesieniu/zmianie nazwy pliku.

        WAŻNE: przenosi też CZŁONKÓW archiwum (members.archive), inaczej po
        przeniesieniu ZIP-a z ToSort do kolekcji indeks nie miałby dla nowej
        ścieżki żadnych członków → NASTĘPNY skan wypakowywałby i hashował całą
        zawartość od nowa (drogi „wolny skan po fix", choć plik ruszył sam
        program). mtime pliku po `os.replace`/`copystat` jest zachowany, więc
        wpis pliku pozostaje AKTUALNY (skan uzna go za świeży)."""
        old_key = str(Path(os.path.abspath(old)))
        new_key = str(Path(os.path.abspath(new)))
        self._note_vacated(old_key)
        self._hand_over_members(new_key)          # nadpisywany wpis
        self._db.execute("DELETE FROM files WHERE path=?", (new_key,))
        self._db.execute("UPDATE files SET path=? WHERE path=?", (new_key, old_key))
        # osieroceni członkowie pod nową ścieżką (gdyby coś było) → precz, potem
        # przenieś członków starego archiwum na nową ścieżkę
        self._db.execute("DELETE FROM members WHERE archive=?", (new_key,))
        self._db.execute("UPDATE members SET archive=? WHERE archive=?",
                         (new_key, old_key))
        self._db.commit()

    def set_deep_fail(self, path: Path | str) -> None:
        """Zapamiętuje NIEUDANĄ głęboką identyfikację CHD (przy bieżącym
        mtime). Dopóki plik się nie zmieni (i nie wymusisz pełnego skanu),
        nie próbujemy ekstrakcji ponownie — porażka też jest wynikiem."""
        key = str(Path(os.path.abspath(path)))
        try:
            m = os.lstat(key).st_mtime_ns
        except OSError:
            return
        self._db.execute("UPDATE files SET deep_fail=? WHERE path=?", (m, key))
        self._db.commit()

    def set_data_sha1(self, path: Path | str, sha1: str) -> None:
        """Zapisuje SHA-1 ZAWARTOŚCI pliku CHD (z nagłówka albo głębokiej
        identyfikacji) — trwale, więc kosztowna ekstrakcja liczy się raz."""
        key = str(Path(os.path.abspath(path)))
        self._db.execute("UPDATE files SET data_sha1=? WHERE path=?",
                         (sha1.lower(), key))
        self._db.commit()

    def set_bad_container(self, path: Path | str, bad: int) -> None:
        """Zapisuje wynik sprawdzenia KONTENERA CHD vs medium DAT:
        -1 niesprawdzony, 0 zgodny, 1 NIEZGODNY (np. gra DVD zrobiona jako CD)."""
        key = str(Path(os.path.abspath(path)))
        self._db.execute("UPDATE files SET bad_container=? WHERE path=?",
                         (int(bad), key))
        self._db.commit()

    def chd_header(self, path: Path | str) -> tuple:
        """(cd_tracks, cd_typed) CHD z indeksu (z nagłówka czytanego przy
        skanie); (-1, -1) = nieznane. Bez dostępu do dysku."""
        row = self.lookup(path)
        if row is None or row["missing"] or "cd_tracks" not in row.keys():
            return -1, -1
        return int(row["cd_tracks"]), int(row["cd_typed"])

    def set_chd_header(self, path: Path | str, tracks: int, cd_typed: int) -> None:
        key = str(Path(os.path.abspath(path)))
        self._db.execute("UPDATE files SET cd_tracks=?, cd_typed=? WHERE path=?",
                         (int(tracks), int(cd_typed), key))
        self._db.commit()

    def set_layout_ok(self, path: Path | str, ok: int) -> None:
        """Zapisuje wynik sprawdzenia UKŁADU ścieżek CHD gry CD vs DAT:
        -1 niesprawdzony, 1 zgodny (odbudowa go pominie bez czytania z NAS)."""
        key = str(Path(os.path.abspath(path)))
        self._db.execute("UPDATE files SET layout_ok=? WHERE path=?",
                         (int(ok), key))
        self._db.commit()

    def set_bad_zip_method(self, path: Path | str, bad: int) -> None:
        """Zapisuje wynik sprawdzenia METODY kompresji ZIP:
        -1 niesprawdzony, 0 OK (store/deflate), 1 ZŁA (zstd/lzma/… — do repacku)."""
        key = str(Path(os.path.abspath(path)))
        self._db.execute("UPDATE files SET bad_zip_method=? WHERE path=?",
                         (int(bad), key))
        self._db.commit()

    def _hand_over_members(self, key: str) -> None:
        """Przed usunięciem wpisu archiwum: jego członkowie przechodzą na
        BLIŹNIAKÓW (ta sama suma i rozmiar — hardlinki/kopie), którzy ich nie
        mają. Inaczej skasowanie jednej nazwy hardlinku kasowało jedyną w
        indeksie wiedzę o zawartości, a pozostałe nazwy trzeba było otwierać."""
        r = self._db.execute("SELECT sha1, size FROM files WHERE path=?",
                             (key,)).fetchone()
        if r is None or not r["sha1"]:
            return
        if not self._db.execute("SELECT 1 FROM members WHERE archive=? LIMIT 1",
                                (key,)).fetchone():
            return
        for (twin,) in self._db.execute(
                "SELECT path FROM files WHERE sha1=? AND size=? AND path<>? "
                "AND NOT EXISTS (SELECT 1 FROM members m WHERE m.archive=files.path)",
                (r["sha1"], r["size"], key)).fetchall():
            self._db.execute(
                "INSERT OR IGNORE INTO members(archive, name, size, crc32, md5, sha1) "
                "SELECT ?, name, size, crc32, md5, sha1 FROM members WHERE archive=?",
                (twin, key))

    def remove_path(self, path: Path | str) -> None:
        """Usuwa wpis pliku z indeksu (po skasowaniu pliku z dysku)."""
        key = str(Path(os.path.abspath(path)))
        self._note_vacated(key)
        self._hand_over_members(key)
        self._db.execute("DELETE FROM files WHERE path=?", (key,))
        self._db.execute("DELETE FROM members WHERE archive=?", (key,))
        self._db.commit()

    def _note_vacated(self, path_key: str) -> None:
        d = os.path.dirname(path_key)
        if d:
            self._vacated[os.path.normcase(d)] = d

    def take_vacated_under(self, root: Path | str) -> list:
        """Katalogi opuszczone pod `root` (bez samego `root`), NAJGŁĘBSZE
        pierwsze; zwrócone są zapominane (kolejne sprzątanie ich nie ponawia)."""
        r = os.path.normcase(os.path.abspath(str(root))).rstrip("\\/")
        pref = r + os.sep
        out = [k for k in self._vacated if k.startswith(pref)]
        paths = [self._vacated.pop(k) for k in out]
        return sorted(paths, key=len, reverse=True)

    def copy_members(self, src: Path | str, dest: Path | str) -> None:
        """Kopia archiwum: członkowie `dest` = członkowie `src` (ta sama treść
        bajt w bajt) — bez czytania pliku z dysku. Czyści ewentualny STARY
        skład spod `dest` (nadpisany plik)."""
        s_key = str(Path(os.path.abspath(src)))
        d_key = str(Path(os.path.abspath(dest)))
        cur = self._db.cursor()
        cur.execute("DELETE FROM members WHERE archive=?", (d_key,))
        cur.execute(
            "INSERT OR IGNORE INTO members(archive, name, size, crc32, md5, sha1) "
            "SELECT ?, name, size, crc32, md5, sha1 FROM members WHERE archive=?",
            (d_key, s_key))
        self._db.commit()

    def set_link_of(self, path: Path | str, target: Path | str) -> None:
        """Zapamiętaj: `path` to HARDLINK treści `target` (ten sam plik
        fizyczny). Planowanie pomija go bez pytania NAS."""
        key = str(Path(os.path.abspath(path)))
        self._db.execute("UPDATE files SET link_of=? WHERE path=?",
                         (os.path.normcase(os.path.abspath(str(target))), key))
        self._db.commit()

    def same_content(self, path: Path | str) -> list:
        """Inne FIZYCZNE wpisy (nie symlinki, obecne) o tej samej sumie i
        rozmiarze co `path` — kandydaci na jego hardlinki/kopie. Bez NAS."""
        key = str(Path(os.path.abspath(path)))
        r = self._db.execute("SELECT sha1, size FROM files WHERE path=?",
                             (key,)).fetchone()
        if r is None or not r["sha1"]:
            return []
        return [row[0] for row in self._db.execute(
            "SELECT path FROM files WHERE sha1=? AND size=? AND path<>? "
            "AND missing=0 AND is_link=0", (r["sha1"], r["size"], key))]

    def record_hardlink(self, path: Path | str, target: Path | str,
                        commit: bool = True) -> None:
        """Świeżo utworzony HARDLINK `path` → treść `target`: wpis z danymi
        celu (rozmiar, mtime, sumy — hardlink dzieli je z celem), BEZ pytania
        NAS. Cel nieznany indeksowi → nic (skan dopisze)."""
        key = str(Path(os.path.abspath(path)))
        tkey = str(Path(os.path.abspath(target)))
        t = self._db.execute("SELECT * FROM files WHERE path=?", (tkey,)).fetchone()
        if t is None or not t["sha1"]:
            return
        now = datetime.now().isoformat(timespec="seconds")
        self._copy_content(self._db, key, t, t["size"], t["mtime_ns"], now,
                           os.path.normcase(tkey))
        # członkowie archiwum celu = członkowie linku (ta sama treść)
        mem = self._db.execute(
            "SELECT name, size, crc32, md5, sha1 FROM members WHERE archive=?",
            (tkey,)).fetchall()
        if mem:
            self._db.execute("DELETE FROM members WHERE archive=?", (key,))
            self._db.executemany(
                "INSERT INTO members(archive, name, size, crc32, md5, sha1) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(key, m["name"], m["size"], m["crc32"], m["md5"], m["sha1"])
                 for m in mem])
        if commit:
            self._db.commit()

    def mark_link(self, path: Path | str) -> None:
        """Po zastąpieniu pliku symlinkiem: wpis staje się linkiem."""
        key = str(Path(os.path.abspath(path)))
        self._db.execute("UPDATE files SET is_link=1 WHERE path=?", (key,))
        self._db.commit()

    def stats(self) -> dict:
        row = self._db.execute(
            "SELECT COUNT(*) AS total, "
            "  SUM(CASE WHEN is_link=1 THEN 1 ELSE 0 END) AS links, "
            "  SUM(CASE WHEN missing=1 THEN 1 ELSE 0 END) AS missing, "
            "  SUM(CASE WHEN is_link=0 AND missing=0 THEN size ELSE 0 END) AS bytes "
            "FROM files"
        ).fetchone()
        return {"total": row["total"] or 0, "links": row["links"] or 0,
                "missing": row["missing"] or 0, "bytes": row["bytes"] or 0}
