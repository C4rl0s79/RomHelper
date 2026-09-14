"""Konwersja plików gry do docelowego formatu przechowywania.

Formaty i narzędzia:
  ZIP  — kartridże; stdlib zipfile (deflate).
  7z   — opcjonalnie; py7zr.
  CHD  — płyty; chdman (createcd dla bin/cue/gdi, createdvd dla iso).
  RVZ  — GameCube/Wii; DolphinTool.exe convert (mają OSOBNE DAT-y na RVZ).
  extract — rozpakuj archiwum/CHD do plików luzem (w podkatalogu per gra).

Każda konwersja jest WERYFIKOWANA przed usunięciem źródła:
  ZIP/7z  — po spakowaniu odczytujemy z powrotem i porównujemy SHA-1 członków;
  CHD     — round-trip (extract) + porównanie SHA-1 z oryginałem;
  RVZ     — DolphinTool verify (SHA-1 zdekompresowanego obrazu == źródło).
Źródło jest kasowane dopiero po udanej weryfikacji (atomowa podmiana tmp).
"""
from __future__ import annotations

import os
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from .fileindex import hash_file

LogCB = Callable[[str], None]

CART_EXTS = {"nes", "sfc", "smc", "gb", "gbc", "gba", "n64", "z64", "v64",
             "md", "gen", "sms", "gg", "nds", "3ds", "cia", "pce", "a26",
             "a78", "lnx", "ws", "wsc", "col", "int", "vec", "rom", "bin"}
DISC_EXTS = {"iso", "cue", "gdi", "bin", "img", "chd"}


@dataclass
class ConvertResult:
    ok: bool
    dst: Optional[Path] = None
    message: str = ""


# --- wykrywanie narzędzi ------------------------------------------------------

def detect_dolphintool(emu_root: Path) -> Optional[Path]:
    """Znajduje DolphinTool.exe (konwersja RVZ) w katalogu emulatorów."""
    for cand in (emu_root / "Dolphin" / "DolphinTool.exe",):
        if cand.is_file():
            return cand
    hits = sorted(emu_root.rglob("DolphinTool.exe"))
    return hits[0] if hits else None


# --- ZIP ----------------------------------------------------------------------

def _zip_compression(method: str):
    """(stała kompresji ZIP, czy metoda dostępna). „zstd" wymaga Pythona 3.14+
    (zipfile.ZIP_ZSTANDARD); gdy niedostępny → fallback DEFLATE."""
    if str(method).lower() == "zstd":
        zst = getattr(zipfile, "ZIP_ZSTANDARD", None)
        if zst is not None:
            return zst, True
        return zipfile.ZIP_DEFLATED, False    # brak wsparcia → deflate
    return zipfile.ZIP_DEFLATED, True


def pack_zip(files: Sequence[Path], dst_zip: Path, *,
             arcnames: Optional[Sequence[str]] = None,
             level: int = 6, method: str = "deflate",
             log: LogCB = lambda m: None) -> ConvertResult:
    """Pakuje pliki do ZIP i WERYFIKUJE (SHA-1 członków po odczycie).
    `level` — poziom 0–9 (0=store, 6=domyślny, 9=maks). `method` — „deflate"
    (zgodne wszędzie) albo „zstd" (mniejszy, ale słabo wspierany)."""
    arcnames = list(arcnames) if arcnames else [f.name for f in files]
    tmp = dst_zip.with_name(dst_zip.name + ".chdbuddy_tmp.zip")
    expected: dict[str, str] = {}
    lvl = max(0, min(int(level), 9))
    comp, ok = _zip_compression(method)
    if not ok:
        log("  UWAGA: ZSTD niedostępny w tym Pythonie — pakuję DEFLATE.")
    try:
        with zipfile.ZipFile(tmp, "w", comp,
                             compresslevel=lvl) as z:
            for f, arc in zip(files, arcnames):
                _, _, sha1 = hash_file(f)
                expected[arc] = sha1
                z.write(f, arc)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return ConvertResult(False, message=f"pakowanie ZIP: {e}")
    # weryfikacja
    import hashlib
    try:
        with zipfile.ZipFile(tmp) as z:
            for arc, want in expected.items():
                got = hashlib.sha1(z.read(arc)).hexdigest()
                if got != want:
                    tmp.unlink(missing_ok=True)
                    return ConvertResult(False,
                        message=f"ZIP weryfikacja: {arc} sha1 nie zgadza się")
    except (OSError, zipfile.BadZipFile) as e:
        tmp.unlink(missing_ok=True)
        return ConvertResult(False, message=f"ZIP weryfikacja: {e}")
    os.replace(tmp, dst_zip)
    log(f"  ZIP OK: {dst_zip.name} ({len(files)} plików, zweryfikowane)")
    return ConvertResult(True, dst=dst_zip)


_ZIP_METHOD_NAMES = {0: "STORE", 8: "DEFLATE", 12: "BZIP2", 14: "LZMA",
                     93: "ZSTD", 99: "AES"}


def _zip_acceptable_methods(method: str):
    """Zbiór metod kompresji AKCEPTOWANYCH dla danego wyboru użytkownika, albo
    None gdy metoda niedostępna w tym Pythonie (zstd < 3.14).

    - "deflate": STORE(0)+DEFLATE(8) — czytelne w KAŻDYM narzędziu.
    - "zstd": tylko ZSTD(93) — user świadomie wybrał mniejszy, mniej zgodny."""
    if str(method).lower() == "zstd":
        zst = getattr(__import__("zipfile"), "ZIP_ZSTANDARD", None)
        return None if zst is None else {zst}
    return {0, 8}


def zip_incompatible_methods(zip_path: Path) -> set:
    """Zbiór metod kompresji w ZIP-ie poza STORE/DEFLATE (niezgodne z emu/
    scraperami). Pusty = czytelny wszędzie. Błąd odczytu → {-1}."""
    import zipfile
    try:
        with zipfile.ZipFile(zip_path) as z:
            return {i.compress_type for i in z.infolist()
                    if not i.is_dir()} - {0, 8}
    except (OSError, zipfile.BadZipFile):
        return {-1}


def zip_needs_repack(zip_path: Path, method: str) -> bool:
    """Czy ZIP UŻYWA innej metody niż wybrana (`method`) → wymaga przepakowania.
    Gdy wybrana metoda niedostępna w tym Pythonie → False (nie ruszamy)."""
    import zipfile
    acc = _zip_acceptable_methods(method)
    if acc is None:
        return False
    try:
        with zipfile.ZipFile(zip_path) as z:
            used = {i.compress_type for i in z.infolist() if not i.is_dir()}
    except (OSError, zipfile.BadZipFile):
        return False
    return bool(used - acc)


def repack_zip(zip_path: Path, *, method: str = "deflate", level: int = 6,
               log: LogCB = lambda m: None,
               dry_run: bool = False) -> ConvertResult:
    """Przepakowuje ZIP na WYBRANĄ metodę (deflate albo zstd), zachowując nazwy
    i ZAWARTOŚĆ członków (weryfikacja SHA-1 round-trip). No-op gdy już w tej
    metodzie. Podmiana atomowa (tmp → replace)."""
    import hashlib
    import zipfile
    acc = _zip_acceptable_methods(method)
    if acc is None:
        return ConvertResult(False,
            message="ZSTD niedostępny w tym Pythonie (potrzebny 3.14+)")
    if not zip_needs_repack(zip_path, method):
        return ConvertResult(True, dst=zip_path)      # już w tej metodzie
    comp, _ok = _zip_compression(method)              # docelowa stała kompresji
    target_name = "ZSTD" if str(method).lower() == "zstd" else "DEFLATE"
    if dry_run:
        log(f"  (podgląd) PRZEPAKUJ ZIP {zip_path.name} → {target_name}")
        return ConvertResult(True, dst=zip_path)
    lvl = max(0, min(int(level), 9))
    # UNIKALNY, WYŁĄCZNIE utworzony plik tymczasowy (mkstemp = O_EXCL) obok
    # archiwum — nie przewidywalna nazwa. Przewidywalna `.chdbuddy_repack.zip`
    # mogłaby zostać podstawiona przez inny proces jako symlink, a ZipFile("w")
    # podążyłby za nim i nadpisał/zterował cel. mkstemp tworzy świeży, zwykły
    # plik pod losową nazwą → nie ma za czym podążać.
    import tempfile as _tf
    _fd, _tmp = _tf.mkstemp(prefix=zip_path.stem + ".", suffix=".chdbuddy_repack.zip",
                            dir=str(zip_path.parent))
    os.close(_fd)
    tmp = Path(_tmp)
    try:
        with zipfile.ZipFile(zip_path) as zin:
            infos = [i for i in zin.infolist() if not i.is_dir()]
            want = {i.filename: hashlib.sha1(zin.read(i.filename)).hexdigest()
                    for i in infos}
            with zipfile.ZipFile(tmp, "w", comp, compresslevel=lvl) as zout:
                for i in infos:
                    zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
                    zi.compress_type = comp
                    zi.external_attr = i.external_attr
                    zout.writestr(zi, zin.read(i.filename))
        with zipfile.ZipFile(tmp) as zchk:
            for name, wsha in want.items():
                if hashlib.sha1(zchk.read(name)).hexdigest() != wsha:
                    tmp.unlink(missing_ok=True)
                    return ConvertResult(False,
                        message=f"repack ZIP: {name} sha1 nie zgadza się")
            if zip_needs_repack(tmp, method):
                tmp.unlink(missing_ok=True)
                return ConvertResult(False, message="repack ZIP: nadal niezgodny")
    except (OSError, zipfile.BadZipFile) as e:
        tmp.unlink(missing_ok=True)
        return ConvertResult(False, message=f"repack ZIP {zip_path.name}: {e}")
    os.replace(tmp, zip_path)
    log(f"  ZIP przepakowany → {target_name}: {zip_path.name}")
    return ConvertResult(True, dst=zip_path)


def repack_zip_to_deflate(zip_path: Path, *, level: int = 6,
                          log: LogCB = lambda m: None,
                          dry_run: bool = False) -> ConvertResult:
    """Wrapper: przepakuj na DEFLATE (zgodne wszędzie)."""
    return repack_zip(zip_path, method="deflate", level=level, log=log,
                      dry_run=dry_run)


def repack_incompatible_zips(roots, *, method: str = "deflate", index=None,
                             level: int = 6, log: LogCB = lambda m: None,
                             dry_run: bool = False, cancel=None) -> tuple:
    """Skanuje `roots` i przepakowuje KAŻDY ZIP, który NIE jest w wybranej
    metodzie (`method`), na tę metodę. Zwraca (przepakowane, błędy). Aktualizuje
    indeks (suma pliku-kontenera się zmienia)."""
    n = err = 0
    for root in roots:
        if not root or not Path(root).is_dir():
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if cancel is not None and cancel.is_set():
                    return n, err
                if not fn.lower().endswith(".zip"):
                    continue
                p = Path(dirpath) / fn
                if os.path.islink(p) or not zip_needs_repack(p, method):
                    continue                       # link albo już w tej metodzie
                r = repack_zip(p, method=method, level=level, log=log,
                               dry_run=dry_run)
                if r.ok:
                    n += 1
                    if index is not None and not dry_run:
                        try:
                            from .fileindex import hash_file
                            crc, md5, sha1 = hash_file(p)
                            index.record_file(p, crc, md5, sha1)
                        except Exception:
                            pass
                else:
                    err += 1
                    log(f"  BŁĄD repack: {p} — {r.message}")
    if n or err:
        log(f"Przepakowano ZIP-ów na DEFLATE: {n}" +
            (f", błędy {err}" if err else "") +
            (" (podgląd)" if dry_run else ""))
    return n, err


# --- CHD (przez chdman) -------------------------------------------------------

def disc_to_chd(main_file: Path, dst_chd: Path, chdman, settings, *,
                log: LogCB = lambda m: None, on_progress=None) -> ConvertResult:
    """Konwertuje obraz płyty (cue/gdi/iso) do CHD z round-trip.

    Używa istniejącej logiki fixer.create_from_source (create + round-trip
    verify). `on_progress(pct, msg)` — postęp kompresji/weryfikacji (pasek
    szczegółowy). Zwraca ścieżkę CHD po udanej weryfikacji."""
    from . import fixer, presets
    from .models import MediaType
    ext = main_file.suffix.lower().lstrip(".")
    media = MediaType.DVD if ext == "iso" else MediaType.CD
    comp = presets.compression_for(settings.compression_preset, media)
    kw = {"on_progress": on_progress} if on_progress is not None else {}
    out = fixer.create_from_source(
        chdman, main_file, media, dst_chd.parent, settings,
        compression=comp, log=lambda m: log(f"  {m}"), delete_source=False,
        **kw)
    if not out.ok:
        return ConvertResult(False, message=out.message)
    made = dst_chd.parent / (main_file.stem + ".chd")
    if made != dst_chd and made.is_file():
        os.replace(made, dst_chd)
    log(f"  CHD OK: {dst_chd.name} (round-trip zweryfikowany)")
    return ConvertResult(True, dst=dst_chd)


def disc_archive_to_chd(archive: Path, dst_chd: Path, chdman, settings, *,
                        scratch: Path, log: LogCB = lambda m: None,
                        on_progress=None) -> Optional[ConvertResult]:
    """Buduje CHD z ARCHIWUM płyty (zip/7z z cue/gdi + torami). Wypakowuje
    WSZYSTKICH członków z ich WEWNĘTRZNYMI nazwami (płasko po basename), żeby
    cue trafiał w tory, i robi createcd/createdvd na cue/gdi/iso. CHD wchłania
    layout — wewnętrzny cue NIE musi zgadzać się z DAT-em (liczy się ZAWARTOŚĆ,
    czyli game_profile). Zwraca ConvertResult albo None (brak cue/nieudane)."""
    import shutil as _sh
    import tempfile
    work = Path(tempfile.mkdtemp(prefix="chdbuddy_disc_", dir=str(scratch)))
    try:
        extracted: list = []
        try:
            if archive.suffix.lower() == ".7z":
                import py7zr
                with py7zr.SevenZipFile(archive) as zf:
                    zf.extractall(path=str(work))
                for p in work.rglob("*"):
                    if p.is_file() and p.parent != work:
                        tgt = work / p.name          # spłaszcz do korzenia
                        if not tgt.exists():
                            os.replace(p, tgt)
                extracted = [p for p in work.iterdir() if p.is_file()]
            else:
                with zipfile.ZipFile(archive) as zf:
                    for i in zf.infolist():
                        if i.is_dir():
                            continue
                        out = work / Path(i.filename).name    # płasko po nazwie
                        with zf.open(i) as fh, open(out, "wb") as o:
                            _sh.copyfileobj(fh, o, 4 * 1024 * 1024)
                        extracted.append(out)
        except (OSError, zipfile.BadZipFile, Exception) as e:
            log(f"  nie wypakowano {archive.name}: {e}")
            return None
        main = None
        for ext in ("cue", "gdi", "toc", "iso"):
            main = next((p for p in extracted
                         if p.suffix.lower().lstrip(".") == ext), None)
            if main:
                break
        if main is None:
            log(f"  brak cue/gdi/iso w {archive.name} — nie zrobię CHD")
            return None
        log(f"  CHD z archiwum: {archive.name} (opis z {main.name})")
        return disc_to_chd(main, dst_chd, chdman, settings, log=log,
                           on_progress=on_progress)
    finally:
        _sh.rmtree(work, ignore_errors=True)


# --- RVZ (przez DolphinTool) --------------------------------------------------

def iso_to_rvz(iso: Path, dst_rvz: Path, dolphintool: Path, *,
               level: int = 5, block_kb: int = 128,
               log: LogCB = lambda m: None) -> ConvertResult:
    """Konwertuje obraz GameCube/Wii (iso) do RVZ i weryfikuje (verify).
    `level` — zstd 1–22 (5=domyślny); `block_kb` — rozmiar bloku w KB."""
    tmp = dst_rvz.with_name(dst_rvz.name + ".chdbuddy_tmp.rvz")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    lvl = str(max(1, min(int(level), 22)))
    block = str(max(32, int(block_kb)) * 1024)
    try:
        r = subprocess.run(
            [str(dolphintool), "convert", "-i", str(iso), "-o", str(tmp),
             "-f", "rvz", "-c", "zstd", "-l", lvl, "-b", block],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", creationflags=flags)
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            return ConvertResult(False, message=f"DolphinTool convert: "
                                                f"{(r.stderr or '').strip()[:200]}")
        v = subprocess.run(
            [str(dolphintool), "verify", "-i", str(tmp), "-a", "sha1"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", creationflags=flags)
        if v.returncode != 0:
            tmp.unlink(missing_ok=True)
            return ConvertResult(False, message="RVZ verify nieudany")
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return ConvertResult(False, message=f"DolphinTool: {e}")
    os.replace(tmp, dst_rvz)
    log(f"  RVZ OK: {dst_rvz.name} (DolphinTool verify)")
    return ConvertResult(True, dst=dst_rvz)


# --- plan konwersji per gra ---------------------------------------------------

def current_format(files: Sequence[Path]) -> str:
    """Zgaduje aktualny format zestawu plików gry."""
    exts = {f.suffix.lower().lstrip(".") for f in files}
    if len(files) == 1:
        only = next(iter(exts))
        if only in ("zip", "7z", "chd", "rvz"):
            return only
    if exts == {"m3u"} or "chd" in exts:
        return "chd"
    return "loose"


_DISC_MAIN_PRIORITY = {"cue": 0, "gdi": 1, "iso": 2}
# rozszerzenia, z których chdman UMIE zrobić CHD (opis ścieżek albo obraz).
# GOŁY .bin/.raw bez cue/gdi NIE wystarcza — createcd bez opisu toru się wiesza.
_CHD_SOURCE_EXTS = {"cue", "gdi", "toc", "iso", "img"}
# rozszerzenia OPISU ścieżek (nie niosą danych — matcher może ich nie mieć, a
# my zsyntetyzujemy je z torów danych).
_DISC_DESC_EXTS = {"cue", "gdi", "toc"}


def _track_no(name: str) -> int:
    """Numer toru z nazwy pliku ('… (Track 3).bin' → 3; 'game3.bin' → 3)."""
    import re
    m = re.search(r"\(\s*Track\s*(\d+)\s*\)", name, re.I)
    if not m:
        m = re.search(r"(?:^|[^0-9])(\d+)\.[A-Za-z0-9]+$", name)
    return int(m.group(1)) if m else 0


def _synthesize_cue(tracks, cue_path: Path,
                    log: LogCB = lambda m: None) -> bool:
    """Buduje .cue z torów .bin, gdy oryginalnego opisu NIE MA nigdzie (luźne/
    rozproszone tory). Każdy tor = osobny ``FILE … BINARY`` z ``INDEX 01
    00:00:00`` — CAŁA zawartość toru jest zapisywana, więc round-trip zachowuje
    bajty każdego toru (game_profile się zgadza). Tor 1 = dane (MODE1/2352),
    pozostałe = AUDIO — typowy układ Redump. Synteza NIE musi być idealna:
    STRAŻNIK TREŚCI (deep_identify == game_profile) i tak zweryfikuje wynik i
    odrzuci złe złożenie. Dzięki cue createcd NIE dostaje gołego binu (nie
    zawiesza się). Zwraca False, gdy nie ma żadnego .bin."""
    bins = [Path(t) for t in tracks if Path(t).suffix.lower() == ".bin"]
    if not bins:
        return False
    bins.sort(key=lambda p: (_track_no(p.name) or 9999, p.name.lower()))
    lines = []
    for i, b in enumerate(bins, 1):
        lines.append(f'FILE "{b.name}" BINARY')
        mode = "MODE1/2352" if i == 1 else "AUDIO"
        lines.append(f"  TRACK {i:02d} {mode}")
        lines.append("    INDEX 01 00:00:00")
    cue_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"  cue zsyntetyzowany z {len(bins)} tor(ów): {cue_path.name}")
    return True


def _content_matches_game(chd_path: Path, game, chdman, work_dir: Path,
                          log: LogCB = lambda m: None) -> bool:
    """STRAŻNIK TREŚCI (wspólny dla wszystkich ścieżek budowy CHD): czy
    zbudowany CHD naprawdę zawiera TĘ grę — ekstrakcja + game_profile == DAT.
    Round-trip weryfikuje tylko KODOWANIE, nie TOŻSAMOŚĆ. Bez tego jeden
    współdzielony/zły tor albo cudze archiwum tworzyły CHD złej gry pod
    właściwą nazwą (regresja naomi/naomi2). Brak chdman lub błąd ekstrakcji =
    False (nie umieszczamy niepewnej treści)."""
    if chdman is None:
        return False
    try:
        from .datfile import DatIndex, game_profile
        from .deepcheck import deep_identify
        expect = (game_profile(game.data_roms) or "").lower()
        one = DatIndex()
        one.add_game(game)
        vr = deep_identify(chdman, Path(chd_path), one, work_dir,
                           log=lambda *_a, **_k: None)
        return bool(vr.ok) and (not expect
                                or (vr.sha1 or "").lower() == expect)
    except Exception as _e:                        # noqa: BLE001
        log(f"  UWAGA: weryfikacja treści nie powiodła się: {_e}")
        return False


def _game_physical_files(target_dir: Path, game, subdir: bool) -> list[Path]:
    """Fizyczne (nie-symlink) pliki gry w kanonicznej lokalizacji."""
    if subdir and len(game.roms) > 1:
        d = target_dir / game.name
        if not d.is_dir():
            return []
        files = [p for p in sorted(d.iterdir()) if p.is_file()]
    else:
        files = [target_dir / r.name for r in game.roms]
        files = [f for f in files if f.is_file()]
    # tylko fizyczne kopie (dzieci-symlinki obsługiwane osobno)
    return [f for f in files if not os.path.islink(f)]


@dataclass
class ConvertStats:
    converted: int = 0
    skipped: int = 0
    errors: int = 0
    tosort_purged: int = 0      # luźne ścieżki gier już-na-CHD skasowane z ToSort
    relinked: int = 0           # fizyczne kopie DZIECI zamienione na linki do rodzica

    def summary(self) -> str:
        extra = (f", ToSort posprzątane {self.tosort_purged}"
                 if self.tosort_purged else "")
        if self.relinked:
            extra += f", kopie dzieci→linki {self.relinked}"
        return (f"skonwertowano {self.converted}, pominięto {self.skipped}, "
                f"błędy {self.errors}{extra}")


def convert_reports(reports, rules_fn, tools: dict, index=None, *,
                    dry_run: bool = False, log: LogCB = lambda m: None,
                    cancel=None, on_progress=None, detail=None,
                    on_converted=None) -> ConvertStats:
    """Konwertuje pliki gier do formatu docelowego z reguł (resolve_format).

    tools: {"chdman": CHDMan|None, "settings": Settings, "dolphintool": Path|None}.
    Konwertuje TYLKO gry z fizycznymi, luźnymi plikami (nie-symlink, nie już
    w formacie docelowym). Weryfikacja w każdej konwersji; źródło kasowane
    dopiero po sukcesie.
    """
    from .dirrules import resolve_format
    st = ConvertStats()
    # ODROCZONE kasowanie źródeł: gry WIELOPŁYTOWE współdzielą ścieżki (np. audio
    # CDDA) — konwersja płyty 1 nie może skasować ścieżki, której potrzebuje
    # płyta 3. Zbieramy wszystkie skonsumowane źródła i kasujemy DOPIERO po
    # przerobieniu WSZYSTKICH gier (współdzielone zostają dostępne do końca).
    deferred: list = []
    deferred_dirs: list = []
    for ri, rep in enumerate(reports):
        if cancel is not None and cancel.is_set():
            log("PRZERWANO konwersję — pliki już przekonwertowane zostają.")
            break
        if on_progress:
            on_progress(ri, len(reports), f"konwersja: {rep.entry.name}")
        eff = rules_fn(rep.entry)
        if eff.get("skip"):
            continue
        fmt = resolve_format(eff.get("format", "keep"), rep.entry)
        if fmt in ("keep", "", "extract"):
            continue
        subdir = bool(eff.get("subdir_per_game", True))
        for game in rep.entry.games:
            if cancel is not None and cancel.is_set():
                break
            files = _game_physical_files(rep.entry.target_dir, game, subdir)
            if not files:
                continue
            cur = current_format(files)
            if cur == fmt:
                continue
            if cur != "loose":
                st.skipped += 1        # np. już chd/zip w innym docelowym — pomiń
                continue
            base = game.name
            if _convert_one(files, rep.entry.target_dir, base, fmt, subdir,
                            len(game.roms), tools, index, dry_run, log, st,
                            detail=detail, on_converted=on_converted,
                            deferred=deferred, deferred_dirs=deferred_dirs,
                            game=game):
                st.converted += 1
    # DOPIERO TERAZ kasujemy źródła (wszystkie płyty zestawów już skonwertowane)
    if deferred and not dry_run:
        log(f"Kasuję {len(deferred)} plików źródłowych po konwersji "
            f"(współdzielone ścieżki były dostępne do końca).")
        for f in deferred:
            try:
                os.unlink(f)
                if index is not None:
                    index.remove_path(f)
            except OSError:
                pass
        for d in deferred_dirs:
            try:
                d.rmdir()          # tylko puste — po zabraniu ścieżek
            except OSError:
                pass
    return st


# Ile WOLNEGO miejsca musi być, licząc jako wielokrotność rozmiaru źródła.
# CHD: powstaje nowy plik + round-trip wypakowuje PEŁNY obraz do weryfikacji,
# więc chwilowo trzymamy źródło + CHD + wypakowany obraz.
_FREE_FACTOR = {"chd": 2.2, "rvz": 1.6, "zip": 1.2, "7z": 1.2}

# Artefakty robocze: zostają po przerwanej konwersji/weryfikacji i zajmują dysk.
_TEMP_MARKERS = ("chdbuddy_", "chddeep_", ".rtcheck.")


def _is_temp_artifact(name: str) -> bool:
    low = name.lower()
    return any(m in low for m in _TEMP_MARKERS)


def purge_temp_artifacts(roots, *, dry_run: bool = False,
                         log: LogCB = lambda m: None,
                         cancel=None) -> tuple[int, int]:
    """Kasuje śmieci po PRZERWANYCH konwersjach/weryfikacjach (chdbuddy_*,
    chddeep_*, *.rtcheck.*). Skaner je ignoruje, więc same z siebie nigdy nie
    znikały i zajmowały dysk. Zwraca (ile_pozycji, ile_bajtów).

    `cancel` — Event: przeszukiwanie CAŁYCH korzeni to na NAS 100k+ zapytań;
    sprawdzamy cancel co katalog (Przerwij działa) i logujemy heartbeat, żeby
    faza „Start…" nie wyglądała na zawieszoną."""
    import shutil as _sh
    n = size = 0
    scanned = 0
    for root in roots:
        p = Path(root)
        if not p.is_dir():
            continue
        log(f"Sprzątanie śmieci po konwersjach: {p}…")
        for dirpath, dirnames, filenames in os.walk(p, topdown=False):
            if cancel is not None and cancel.is_set():
                return n, size
            scanned += 1
            if scanned % 5000 == 0:
                log(f"  …przeszukano {scanned} katalogów (śmieci: {n})")
            for fn in filenames:
                if not _is_temp_artifact(fn):
                    continue
                fp = Path(dirpath) / fn
                try:
                    sz = fp.stat().st_size
                except OSError:
                    sz = 0
                log(f"USUWAM śmieć: {fp} ({sz/1024**3:.2f} GB)")
                if not dry_run:
                    try:
                        fp.unlink()
                    except OSError as e:
                        log(f"  nie usunięto: {e}")
                        continue
                n += 1
                size += sz
            for dn in dirnames:
                if not _is_temp_artifact(dn):
                    continue
                dp = Path(dirpath) / dn
                log(f"USUWAM katalog roboczy: {dp}")
                if not dry_run:
                    _sh.rmtree(dp, ignore_errors=True)
                n += 1
    return n, size


def _gather_track_to_ram(status, ram_dir: Path, log: LogCB) -> Optional[Path]:
    """Kopiuje/wypakowuje JEDNĄ ścieżkę gry ze źródła (ToSort) na RAM i
    weryfikuje SHA-1 z DAT-em. Zwraca ścieżkę na RAM albo None (błąd/niezgoda).
    Docelowy katalog kolekcji NIGDY nie jest dotykany."""
    import shutil as _sh
    rom = status.rom
    dst = ram_dir / rom.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    src = Path(status.source_path) if status.source_path else None
    if src is None or not src.exists():
        log(f"  źródło ścieżki {rom.name} nie istnieje")
        return None
    try:
        if status.member:                       # ścieżka WEWNĄTRZ archiwum
            with zipfile.ZipFile(src) as zf, zf.open(status.member) as fh, \
                    open(dst, "wb") as out:
                _sh.copyfileobj(fh, out, 4 * 1024 * 1024)
        else:                                   # luźny plik
            with open(src, "rb") as fi, open(dst, "wb") as out:
                _sh.copyfileobj(fi, out, 8 * 1024 * 1024)
    except (OSError, zipfile.BadZipFile, KeyError) as e:
        log(f"  nie zebrano {rom.name}: {e}")
        return None
    try:
        crc, md5, sha1 = hash_file(dst)
        size = os.path.getsize(dst)
    except OSError:
        return None
    # WSZYSTKIE sumy kontrolne z DAT-a muszą się zgadzać (rozmiar+CRC+MD5+SHA-1);
    # puste pola nie blokują. Zła zawartość NIGDY nie trafia do kompresji.
    ok = ((not rom.size or size == rom.size)
          and (not rom.sha1 or sha1 == rom.sha1.lower())
          and (not rom.md5 or md5 == rom.md5.lower())
          and (not rom.crc or crc == rom.crc.lower().zfill(8)))
    if not ok:
        log(f"  {rom.name}: sumy kontrolne NIE zgadzają się z DAT-em — "
            f"pomijam grę (fallback)")
        return None
    return dst


def _purge_redundant_tosort_tracks(game, index, del_prefixes, needed_sha1,
                                   log: LogCB, needed_crc=None,
                                   kept_shared=None) -> int:
    """Kasuje z ToSort ŹRÓDŁO gry JUŻ zrobionej na CHD (w docelowym): luźne
    pliki ścieżek ORAZ archiwa ZIP/7z zawierające te ścieżki.

    Tory POTRZEBNE niezaspokojonym grom (`needed_sha1`/`needed_crc`) to zwykle
    WSPÓLNE filler-tory (np. GD-ROM „Track 2", identyczny w setkach gier). Nie
    trzymamy ich w dziesiątkach kopii — redukujemy do JEDNEJ w całym przebiegu
    (`kept_shared`), resztę kasujemy. Puste podkatalogi po skasowanych torach
    też usuwamy. Symlinki nietknięte. Zwraca ile skasowano.

    Dopasowanie jak w matcherze: po SHA-1, a gdy brak — po CRC32+rozmiar."""
    needed_crc = needed_crc or set()
    if kept_shared is None:
        kept_shared = set()
    n = 0
    touched_dirs: set = set()
    candidate_archives: set = set()
    for rom in game.roms:
        sha1 = (rom.sha1 or "").lower()
        crc = (rom.crc or "").lower().zfill(8) if rom.crc else ""
        size = rom.size or 0
        protected = ((sha1 and sha1 in needed_sha1)
                     or (crc and size and (crc, size) in needed_crc))
        # LUŹNE kopie ścieżki w ToSort (po SHA-1, w razie braku CRC32+rozmiar)
        rows = index.find_sha1(sha1, include_chd_content=False) if sha1 else []
        if not rows and crc and size:
            rows = index.find_crc(crc, size)
        copies = [r for r in rows
                  if any(os.path.normcase(r["path"]).startswith(dp)
                         for dp in del_prefixes)
                  and not r["is_link"] and not r["missing"]]

        if protected:
            # WSPÓLNY tor: zostaw dokładnie 1 kopię w CAŁYM przebiegu.
            key = sha1 or f"{crc}:{size}"
            if key in kept_shared:
                continue                      # 1 kopię już zachowaliśmy wcześniej
            kept_shared.add(key)
            victims = copies[1:]              # copies[0] zostaje jako ta jedna
        else:
            victims = copies                  # nikt nie potrzebuje → kasuj wszystkie

        for row in victims:
            p2 = row["path"]
            try:
                os.unlink(p2)
                index.remove_path(p2)
                n += 1
                touched_dirs.add(os.path.dirname(p2))
                tag = ("nadmiarowy wspólny tor" if protected
                       else "gra już na CHD")
                log(f"KASUJ z ToSort ({tag}): {p2}")
            except OSError as e:
                log(f"  nie skasowano {p2}: {e}")

        if protected:
            continue                          # archiwum ze wspólnym torem zostaw
        # ARCHIWA (ZIP/7z) zawierające tę ścieżkę — SHA-1, potem CRC+rozmiar
        try:
            marchs = index.find_member_sha1(sha1) if sha1 else []
            if not marchs and crc and size:
                marchs = index.find_member_crc(crc, size)
            for m in marchs:
                ap = m["archive"]
                if any(os.path.normcase(ap).startswith(dp)
                       for dp in del_prefixes):
                    candidate_archives.add(ap)
        except Exception:
            pass
    # skasuj archiwum tylko gdy ŻADEN jego członek nie jest potrzebny
    # niezaspokojonej grze (po SHA-1 albo CRC+rozmiar).
    for ap in candidate_archives:
        try:
            members = index._db.execute(
                "SELECT sha1, crc32, size FROM members WHERE archive=?",
                (ap,)).fetchall()
        except Exception:
            continue
        protected = False
        for r in members:
            ms = (r["sha1"] or "").lower()
            mc = (r["crc32"] or "").lower()
            msz = r["size"] or 0
            if ms and ms in needed_sha1:
                protected = True
                break
            if mc and msz and (mc, msz) in needed_crc:
                protected = True
                break
        if protected:
            continue                          # ZIP potrzebny innej grze — zostaw
        try:
            os.unlink(ap)
            index.remove_path(ap)
            n += 1
            touched_dirs.add(os.path.dirname(ap))
            log(f"KASUJ z ToSort archiwum (gra już na CHD): {ap}")
        except OSError as e:
            log(f"  nie skasowano archiwum {ap}: {e}")
    # posprzątaj PUSTE podkatalogi ToSort po skasowanych plikach (od najgłębszych)
    for d in sorted(touched_dirs, key=len, reverse=True):
        nd = os.path.normcase(d)
        if not any(nd.startswith(dp) for dp in del_prefixes):
            continue                          # tylko wewnątrz ToSort
        if any(nd + os.sep == dp for dp in del_prefixes):
            continue                          # nie kasuj korzenia ToSort
        try:
            if not os.listdir(d):
                os.rmdir(d)
                log(f"KASUJ pusty podkatalog ToSort: {d}")
        except OSError:
            pass
    return n


def _purge_child_loose_duplicates(game, loose_by_sha1, needed_sha1, index,
                                  log: LogCB, dry_run: bool) -> int:
    """DZIECKO jest/będzie zaspokojone przez CHD (rodzica) — z jego KATALOGU
    DOCELOWEGO kasuje LUŹNE fizyczne pliki torów tej gry (błędnie wypakowane we
    wcześniejszym przebiegu). Ich zawartość żyje w CHD, więc to bezpieczne.
    Nie rusza plików .chd, symlinków ani sha1 potrzebnych niezaspokojonym grom
    (`needed_sha1`). Zwraca ile skasowano (w dry_run: ile BY skasowano).

    `loose_by_sha1` — mapa sha1→[ścieżki] LUŹNYCH fizycznych plików (bez .chd,
    bez missing) w katalogu docelowym, zbudowana RAZ per katalog przez wołającego.
    Dawniej robiliśmy `index.all_under(target_dir)` PER GRA — dla katalogu z
    tysiącami CHD to O(gry²) zapytań: „Znajdź naprawy" stało minutami zanim
    pokazało pierwszą pozycję."""
    game_sha1 = {(r.sha1 or "").lower() for r in game.roms if r.sha1}
    if not game_sha1:
        return 0
    n = 0
    parents: dict = {}
    for sha1 in game_sha1:
        if not sha1 or sha1 in needed_sha1:
            continue                          # potrzebne niezaspokojonej grze
        for p in list(loose_by_sha1.get(sha1, ())):
            if dry_run:
                log(f"  (podgląd) KASUJ luźny w dziecku: {p}")
                n += 1
                continue
            try:
                os.unlink(p)
                index.remove_path(p)
                n += 1
                log(f"KASUJ luźny w dziecku (gra na CHD): {p}")
                pd = Path(p).parent
                parents[os.path.normcase(str(pd))] = pd
            except OSError as e:
                log(f"  nie skasowano {p}: {e}")
    for pd in parents.values():           # opustoszały podkatalog `<gra>\` → precz
        _rmdir_if_empty(pd, log)
    return n


def _link_child_to_parent(child_final: Path, parent_final: Path, make_links: bool,
                          links_blocked: list, dry_run: bool, log: LogCB) -> bool:
    """Tworzy SYMLINK child_final -> parent_final (dziecko dostaje własną nazwę,
    plik fizyczny zostaje u rodzica). Zasada: gdy symlinku NIE DA SIĘ utworzyć,
    nic nie kopiujemy (żadnych duplikatów) — zwracamy False."""
    from .linker import (LinkPrivilegeError, create_link, is_link, remove_link)
    if dry_run:
        log(f"  LINK(dziecko) {child_final} -> {parent_final} (podgląd)")
        return True
    if not make_links or links_blocked[0]:
        log(f"  SYMLINK pominięty (brak uprawnień/wyłączony): {child_final.name}")
        return False
    child_final.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(child_final):
        if is_link(child_final):
            remove_link(child_final)          # odśwież
        else:
            log(f"  KONFLIKT: {child_final} zajęte zwykłym plikiem")
            return False
    try:
        create_link(child_final, parent_final, is_dir=False)
    except OSError as e:
        if isinstance(e, LinkPrivilegeError):
            links_blocked[0] = True
            log(f"  UWAGA: {e} Symlinki POMIJAM (nic nie kopiuję).")
        else:
            log(f"  BŁĄD symlinku {child_final}: {e}")
        return False
    log(f"  LINK(dziecko) {child_final.name} -> {parent_final}")
    return True


def _relink_verified_duplicate(child: Path, parent: Path, prof, index,
                               make_links: bool, links_blocked: list,
                               dry_run: bool, log: LogCB) -> bool:
    """DZIECKO ma WŁASNY, fizyczny plik (CHD) o tej samej ZAWARTOŚCI co rodzic
    (ten sam `game_profile`/`data_sha1`) — powstały błędnie zamiast linka.
    Weryfikuje, że rodzic jest realnie obecny i ma tę zawartość, KASUJE fizyczną
    kopię dziecka i wstawia symlink do rodzica. Gdy linku nie da się utworzyć —
    ZOSTAWIA fizyczny plik (nic nie kasujemy, żadnych strat). Zwraca True gdy
    dziecko wskazuje już na rodzica."""
    from .linker import (LinkPrivilegeError, create_link, is_link,
                         remove_link)
    child = Path(child)
    parent = Path(parent)
    # rodzic MUSI być realnym plikiem — inaczej skasowalibyśmy jedyną kopię
    if not parent.exists():
        log(f"  POMIŃ relink: rodzic nie istnieje ({parent})")
        return False
    # weryfikacja zawartości rodzica po odcisku (jeśli indeks ma zapis)
    if index is not None and prof:
        try:
            prow = index.lookup(parent)
        except Exception:
            prow = None
        if prow is not None:
            pcontent = (prow["data_sha1"] or prow["sha1"] or "")
            if pcontent and pcontent.lower() != prof.lower():
                log(f"  POMIŃ relink: rodzic ma inny odcisk niż gra ({parent})")
                return False
    if dry_run:
        log(f"  RELINK(dziecko) {child} -> {parent} "
            f"(podgląd; skasuje błędną fizyczną kopię)")
        return True
    if not make_links or links_blocked[0]:
        log(f"  RELINK pominięty (brak uprawnień/wyłączony): {child.name} "
            f"— zostawiam fizyczny plik")
        return False
    child.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(child):
        if is_link(child):
            try:
                remove_link(child)                 # już link → odśwież cel
            except OSError:
                pass
        else:
            # ZWERYFIKOWANY duplikat: kasujemy błędną fizyczną kopię dziecka
            try:
                os.remove(child)
                if index is not None:
                    index.remove_path(child)
            except OSError as e:
                log(f"  BŁĄD kasowania fizycznej kopii {child}: {e}")
                return False
    try:
        create_link(child, parent, is_dir=False)
    except OSError as e:
        if isinstance(e, LinkPrivilegeError):
            links_blocked[0] = True
            log(f"  UWAGA: {e} Symlinki POMIJAM (nic nie kopiuję).")
        else:
            log(f"  BŁĄD symlinku {child}: {e}")
        return False
    if index is not None:
        try:
            index.mark_link(child)
        except Exception:
            pass
    log(f"  RELINK(dziecko) {child.name} -> {parent} "
        f"(skasowano błędną fizyczną kopię)")
    return True


def _rmdir_if_empty(d: Path, log: LogCB = lambda m: None) -> None:
    """Usuwa katalog TYLKO gdy jest pusty (po zabraniu z niego plików). Katalog
    platformy nigdy nie jest pusty (jest w nim świeży .chd + inne gry), więc to
    bezpieczne — kasuje wyłącznie opustoszały podfolder `<gra>\\`. Ciche błędy
    (nie pusty / nie istnieje / brak praw) = zostawiamy."""
    try:
        d.rmdir()
        log(f"  KASUJ pusty katalog gry: {d}")
    except OSError:
        pass


def _defer_or_purge_game_sources(sts, shared_srcs, deferred, index, dry_run,
                                 log: LogCB) -> None:
    """Źródła gry: UNIKALNE → kasuj OD RAZU (log); WSPÓŁDZIELONE → odrocz do
    końca (inna płyta/fallback/dziecko jeszcze ich potrzebuje). Po skasowaniu
    torów usuwa opustoszały podkatalog `<gra>\\` (bin/cue leżały w podfolderze
    pod katalogiem platformy — po konwersji na CHD zostawał pusty katalog)."""
    if dry_run:
        for s in sts:
            if s.source_path:
                deferred.append(Path(s.source_path))
        return
    seen: set = set()
    parents: dict = {}                        # katalogi do sprzątnięcia (jeśli puste)
    for s in sts:
        sp = s.source_path
        if not sp:
            continue
        np = os.path.normcase(str(sp))
        if np in seen:
            continue
        seen.add(np)
        if np in shared_srcs:
            deferred.append(Path(sp))
            log(f"  źródło współdzielone — skasuję po całości: {sp}")
        else:
            try:
                os.unlink(sp)
                if index is not None:
                    index.remove_path(sp)
                log(f"  KASUJ źródło: {sp}")
                pd = Path(sp).parent
                parents[os.path.normcase(str(pd))] = pd
            except OSError as e:
                log(f"  nie skasowano źródła {sp}: {e}")
    # opustoszałe podkatalogi gry (jeśli część torów była współdzielona i poszła
    # do `deferred`, katalog jeszcze nie jest pusty → rmdir cicho odpada, a
    # sprzątnie go końcowy flush odroczonych)
    for pd in parents.values():
        _rmdir_if_empty(pd, log)


def convert_from_source(reports, rules_fn, tools: dict, index=None, *,
                        dry_run: bool = False, log: LogCB = lambda m: None,
                        cancel=None, on_progress=None, detail=None,
                        on_converted=None, delete_roots=None, make_links=True,
                        slot=None):
    """Konwersja PROSTO ZE ŹRÓDŁA na RAM → w docelowym ląduje TYLKO finał.

    Dla gier, których źródłem są luźne pliki albo ścieżki w archiwum (ToSort),
    i które trzeba przekonwertować (chd/rvz/zip): zbiera ścieżki na RAM,
    weryfikuje SHA-1, kompresuje na RAM, weryfikuje (round-trip/verify) i
    przenosi finał do docelowego. Katalog kolekcji nigdy nie dostaje luźnych
    plików. Źródła kasowane DOPIERO po WSZYSTKICH grach (współdzielone ścieżki
    gier wielopłytowych dostępne do końca — brak D2).

    Zwraca (ConvertStats, done_keys) — done_keys to zbiór kluczy gier
    obsłużonych tutaj; placement MUSI je pominąć. Gry, których funkcja nie
    umie/nie chce ruszyć, zostawia nietknięte (obsłuży zwykły placement +
    stara konwersja) — bezpieczny fallback.
    """
    from .dirrules import resolve_format
    from .matcher import RomState

    from .datfile import game_profile
    st = ConvertStats()
    done: set = set()
    deferred: list = []                       # WSPÓŁDZIELONE źródła (kasuj po całości)
    # ODCISK gry (game_profile) -> ścieżka finalnego pliku (rodzic). Kolejne
    # DAT-y z tym samym odciskiem (DZIECI, np. 1G1R) NIE robią drugiego CHD —
    # dostają SYMLINK z WŁASNĄ nazwą do pliku rodzica (jedna kopia fizyczna).
    final_by_profile: dict = {}
    _links_blocked = [False]                   # brak uprawnień → nic nie kopiujemy
    # Które źródła są WSPÓŁDZIELONE przez >1 grę (np. ścieżka audio dzielona
    # przez płyty zestawu, albo plik potrzebny też grze idącej do fallbacku)?
    # Takie kasujemy DOPIERO na końcu. Unikalne (jednopłytowe) — od razu po
    # konwersji, żeby ToSort zwalniał się w trakcie długiej naprawy.
    from collections import defaultdict
    _games_by_src: dict = defaultdict(set)
    for _rep in reports:
        for _s in _rep.statuses:
            if _s.source_path:
                _games_by_src[os.path.normcase(_s.source_path)].add(
                    (id(_rep.entry), _s.game))
    shared_srcs = {src for src, gs in _games_by_src.items() if len(gs) > 1}
    # SHA-1 ścieżek potrzebnych przez gry NIEzaspokojone (choć jeden ROM nie na
    # miejscu) — takich luźnych plików NIE wolno skasować z ToSort, nawet jeśli
    # są też ścieżką gry już zrobionej na CHD (inna gra ich jeszcze potrzebuje).
    # ...oraz CRC32+rozmiar tychże (członkowie archiwum ze skanu SZYBKIEGO nie
    # mają SHA-1 — bez ochrony po CRC dałoby się skasować ZIP wciąż potrzebny).
    _needed_sha1: set = set()
    _needed_crc: set = set()
    for _rep in reports:
        _bg: dict = defaultdict(list)
        for _s in _rep.statuses:
            _bg[_s.game].append(_s)
        for _sts in _bg.values():
            unsat = any(_s.state in (RomState.ELSEWHERE, RomState.WRONG_NAME,
                                     RomState.MISSING, RomState.NO_HASH)
                        for _s in _sts)
            if unsat:
                for _s in _sts:
                    if _s.rom.sha1:
                        _needed_sha1.add(_s.rom.sha1.lower())
                    if _s.rom.crc and _s.rom.size:
                        _needed_crc.add(
                            (_s.rom.crc.lower().zfill(8), _s.rom.size))
    del_prefixes = [os.path.normcase(str(Path(os.path.abspath(r)))).rstrip("\\/")
                    + os.sep for r in (delete_roots or []) if r]
    n_total = sum(len(r.entry.games) for r in reports) or 1
    gi = 0
    # CACHE luźnych plików per KATALOG DOCELOWY (sha1 → [ścieżki]): budowany RAZ
    # z `index.all_under` przy pierwszej grze via_chd danego katalogu, reużywany
    # przez wszystkie kolejne gry tego katalogu. Bez tego `_purge_child_loose_
    # duplicates` robił all_under PER GRA → O(gry²) → „Znajdź naprawy" stało
    # minutami na katalogach z tysiącami CHD.
    _loose_cache: dict = {}

    def _loose_by_sha1(target_dir) -> dict:
        k = os.path.normcase(str(target_dir))
        m = _loose_cache.get(k)
        if m is None:
            m = {}
            if index is not None:
                try:
                    for row in index.all_under(target_dir, physical_only=True):
                        p = row["path"]
                        if p.lower().endswith(".chd") or row["missing"]:
                            continue
                        s = (row["sha1"] or "").lower()
                        if s:
                            m.setdefault(s, []).append(p)
                except Exception:
                    m = {}
            _loose_cache[k] = m
        return m
    # WSPÓLNE tory (np. filler GD-ROM „Track 2", identyczny w setkach gier):
    # chronione przez needed_sha1 nieposiadanych gier. Zamiast trzymać dziesiątki
    # kopii — redukujemy do JEDNEJ w całym przebiegu. Klucz sha1/crc:size, który
    # już ma zachowaną 1 kopię.
    _kept_shared: set = set()
    # BUDŻET MIEJSCA — RAZ na cały przebieg (tylko realna naprawa; dry-run i tak
    # nie konwertuje). Zmiana nazwy/katalogu idzie przez rebuilder i miejsca NIE
    # potrzebuje; pyta tylko KONWERSJA. Budujemy na scratchu (RAM, gdy się
    # mieści) i podmieniamy źródło finałem, więc zapas potrzebny „na chwilę".
    # Reguła (wg usera): jeśli scratch ma >= NAJWIĘKSZA gra ×10 wolnego, wszystko
    # się zmieści (nawet równolegle) → NIE pytamy o miejsce per gra (na NAS to
    # wolne, blokujące zapytanie). Inaczej (ciasno) — sprawdzamy per gra.
    # POTOK (nakładanie pobierz‖konwertuj‖wyślij). Scratch dobierany PER GRA
    # (RAM-dysk gdy gra się mieści, inaczej dysk fizyczny) — NIE zależy już od
    # „największa×10" (to blokowało potok globalnie, gdy jest choćby jedna wielka
    # gra jak PS2 34.8 GB → 348 GB, choć małe gry 3DO/PS1 spokojnie by się
    # nakładały). Budżet potoku = wolne na RAM-dysku (tam trafiają małe,
    # nakładane gry); StagePipeline rezerwuje per-zadanie, więc gra większa niż
    # budżet idzie sama (bez zakleszczenia), a duże scratch i tak dostają dysk
    # fizyczny per gra. Kompresja zawsze 1 na raz (CPU); nakładamy tylko I/O.
    # Potok bezpieczny gdy: jest RAM-dysk (budżet) i BRAK współdzielonych odcisków
    # (żadne dziecko nie linkuje do rodzica → zero zależności kolejnościowych).
    _pipe = None
    _fed: list = []                      # (key, handle) — pogodzenie `done` przy błędzie
    _pipe_ram_budget = 0
    if not dry_run:
        try:
            import shutil as _sh0

            from . import ramdisk as _rd
            _ram = _rd.active_root()
            if _ram is not None:
                _pipe_ram_budget = int(_sh0.disk_usage(str(_ram)).free * 0.85)
        except Exception:
            _pipe_ram_budget = 0
    # WSPÓŁDZIELONE odciski (ten sam `game_profile` w >1 grze — np. 1G1R dziecko
    # linkujące do rodzica, albo klony arcade dzielące ROM-y). TE gry wymagają
    # kolejności rodzic→dziecko (dziecko linkuje do FIZYCZNIE gotowego rodzica),
    # więc idą ŚCIEŻKĄ SERYJNĄ. Reszta (UNIKATOWE odciski: dyski CD 3DO/PS1/Saturn)
    # nie ma zależności → leci POTOKIEM RÓWNOLEGŁYM. Dawniej pojedynczy współdzielony
    # odcisk GDZIEKOLWIEK wyłączał potok dla CAŁEGO przebiegu (all-or-nothing), więc
    # 3DO nigdy nie zrównoleglone. Teraz gate jest PER GRA.
    # KLUCZ DEDUP = (platforma, odcisk). Dedup (link dziecko→rodzic) działa TYLKO
    # w OBRĘBIE PLATFORMY. Dwie gry o identycznej treści na RÓŻNYCH platformach
    # (np. ten sam dump na MSX i Master System) to DWA legalne pliki fizyczne —
    # NIE rodzic/dziecko, żadnych cross-platformowych symlinków. Globalny dedug
    # po samym odcisku robił „wojnę między katalogami" i błędnie linkował.
    from .datstore import platform_key as _pk

    def _plat_key(entry) -> str:
        alias = rules_fn(entry).get("platform", "")
        return _pk(str(alias)) if alias else _pk(entry.name)

    _shared_profiles: set = set()
    if not dry_run and _pipe_ram_budget > 0:
        from collections import Counter as _Counter
        _profc: _Counter = _Counter()
        for _rep in reports:
            _eff = rules_fn(_rep.entry)
            if _eff.get("skip"):
                continue
            if resolve_format(_eff.get("format", "keep"), _rep.entry) in (
                    "keep", "", "extract"):
                continue
            _pl = _plat_key(_rep.entry)
            for _g in _rep.entry.games:
                pr = game_profile(_g.data_roms)
                if pr:
                    _profc[(_pl, pr)] += 1
        _shared_profiles = {k for k, c in _profc.items() if c > 1}
        import dataclasses as _dc

        from .convert_pipeline import StagePipeline
        # RÓWNOLEGŁA KONWERSJA: N chdman/DolphinTool naraz. Cel — obłożyć
        # 8 rdzeni WYDAJNYCH (bez HT) po JEDNEJ konwersji, zamiast jednej
        # gry ciągnącej wszystkie rdzenie (małe CD 3DO/PS1/Saturn tak nie
        # sycą CPU/NAS). Ile: ~połowa logicznych, ale nie więcej niż 8
        # (na tej maszynie 20 log. → 8). Każda konwersja dostaje 1 wątek
        # chdman (-np 1), więc 8 konwersji ≈ 8 P-rdzeni (bez przeciążenia).
        _logical = os.cpu_count() or 4
        _cw = getattr(tools.get("settings"), "convert_workers", 0) or 0
        if _cw and int(_cw) > 0:
            _build_workers = max(1, min(int(_cw), _logical))   # z ustawień
        else:
            _build_workers = max(1, min(8, _logical // 2))     # auto
        _tools_pipe = tools
        if _build_workers > 1:
            _s = tools.get("settings")
            try:
                _s2 = _dc.replace(_s, threads=1)   # 1 wątek chdman / zadanie
                _tools_pipe = dict(tools)
                _tools_pipe["settings"] = _s2
            except Exception:
                _tools_pipe = tools
        _pipe = StagePipeline(
            gather=lambda j: _conv_gather_phase(j, log),
            build=lambda j, g: _conv_build_phase(j, _tools_pipe, log, detail,
                                                 slot=slot),
            upload=lambda j, b: _conv_upload_phase(j, detail, log),
            finalize=lambda j, r: _conv_finalize_phase(
                j, r, index, on_converted, st, shared_srcs, deferred, log),
            release=_conv_release, ram_budget=_pipe_ram_budget, log=log,
            cancel=cancel, build_workers=_build_workers, ordered=False)
        _pipe.start()
        _shared_note = (f"; {len(_shared_profiles)} współdzielonych odcisków "
                        f"seryjnie" if _shared_profiles else "")
        log(f"Potok konwersji WŁ ({_build_workers} równoległych, budżet RAM "
            f"{_pipe_ram_budget/1024**3:.1f} GB){_shared_note} — pobieranie i "
            f"wysyłka nakładane na kompresję.")

    for rep in reports:
        if cancel is not None and cancel.is_set():
            break
        eff = rules_fn(rep.entry)
        if eff.get("skip"):
            continue
        fmt = resolve_format(eff.get("format", "keep"), rep.entry)
        if fmt in ("keep", "", "extract"):
            continue
        # KATALOG-RODZIC („wszystkie rodzicami", parent_priority): jego DAT-y
        # ZAWSZE dostają plik FIZYCZNY — nigdy nie linkują się (nawet identyczna
        # treść między platformami/DAT-ami w rodzicu). Tylko DAT-y spoza rodzica
        # (dzieci) mogą linkować do fizycznego pliku rodzica.
        is_parent = bool(eff.get("parent_priority"))
        subdir = bool(eff.get("subdir_per_game", True))
        by_game: dict = {}
        for s in rep.statuses:
            by_game.setdefault(s.game, []).append(s)
        # KOLEJNOŚĆ: NAJPIERW gry, których źródło jest JUŻ w katalogu docelowym
        # (naprawa W MIEJSCU: zła nazwa/format/opakowanie po zmianie ustawień
        # DAT), DOPIERO POTEM te z ToSort (uzupełnianie braków). Bez tego kopia
        # z ToSort mogła zostać keeperem (odciskiem) przed własną kopią kolekcji,
        # a to kolekcja jest źródłem prawdy. `sorted` jest stabilne → w obrębie
        # każdej grupy kolejność DAT-u zachowana. Nie rusza rodzic-przed-dzieckiem
        # (to kolejność MIĘDZY raportami, tu zmieniamy tylko wewnątrz jednego).
        _tprefix = os.path.normcase(str(rep.entry.target_dir)).rstrip("\\/") + os.sep

        def _in_place_first(g, _bg=by_game, _tp=_tprefix) -> int:
            for s in _bg.get(g.name, ()):
                sp = s.source_path
                if sp and os.path.normcase(sp).startswith(_tp):
                    return 0            # źródło w kolekcji → w miejscu (pierwsze)
            return 1                    # ToSort / gdzie indziej / brak → później

        for game in sorted(rep.entry.games, key=_in_place_first):
            if cancel is not None and cancel.is_set():
                break
            gi += 1
            sts = by_game.get(game.name, [])
            if not sts:
                continue
            # DYSK w JEDNYM archiwum (cue/gdi + tory) → CHD: buduj CHD WPROST z
            # archiwum jego WŁASNYM cue (nazwy w środku pasują do torów). Ratuje
            # przypadek, gdy DAT-owy cue ma inne nazwy → wg DAT „brak" cue, ale
            # w archiwum cue JEST. Robimy to PRZED skipem na MISSING.
            if fmt == "chd" and index is not None and not dry_run:
                arch_srcs = {s.source_path for s in sts
                             if s.member and s.source_path}
                miss_cue = any(
                    s.state in (RomState.MISSING, RomState.NO_HASH)
                    and s.rom.name.lower().endswith((".cue", ".gdi"))
                    for s in sts)
                # NAJWIĘKSZY tor DANYCH gry MUSI pochodzić z TEGO archiwum.
                # Bez tego jeden PRZYPADKOWO współdzielony tor (płyty GD-ROM
                # naomi mają wspólne/puste tory) kazał zbudować CAŁY dysk z
                # CUDZEGO archiwum i zapisać go pod nazwą tej gry (utrata
                # tożsamości treści — np. Virtua Striker 3 jako „Dynamic Golf").
                _data_sts = [s for s in sts
                             if not s.rom.name.lower().endswith(
                                 (".cue", ".gdi"))]
                _main = max(_data_sts, key=lambda s: s.rom.size or 0,
                            default=None)
                _main_ok = bool(
                    _main and _main.member and _main.source_path
                    and len(arch_srcs) == 1
                    and os.path.normcase(_main.source_path)
                    == os.path.normcase(next(iter(arch_srcs))))
                if (len(arch_srcs) == 1 and miss_cue and _main_ok
                        and Path(next(iter(arch_srcs))).suffix.lower()
                        in (".zip", ".7z")):
                    arch = Path(next(iter(arch_srcs)))
                    _pr0 = game_profile(game.data_roms)
                    # rejestracja keepera (platforma, odcisk) — także dla RODZICA,
                    # by DZIECI mogły linkować; is_parter blokuje tylko linkowanie
                    _pk0 = (_plat_key(rep.entry), _pr0) if _pr0 else None
                    if arch.is_file() and _try_disc_archive_chd(
                            rep.entry, game, arch, tools, index, log, st,
                            detail, on_converted, final_by_profile, pkey=_pk0):
                        done.add(f"{id(rep.entry)}::{game.name}")
                        _defer_or_purge_game_sources(sts, shared_srcs, deferred,
                                                     index, dry_run, log)
                        continue
            # WARUNKI (inaczej fallback do placementu):
            #  - żadna ścieżka nie MISSING/NO_HASH (kompletna),
            #  - źródło to luźne pliki/członki archiwum (nie via_chd,
            #    nie via_archive-całej-gry — te obsłuży placement),
            #  - jest co konwertować (nie same HAVE w docelowym formacie).
            _miss = [s for s in sts
                     if s.state in (RomState.MISSING, RomState.NO_HASH)]
            if _miss:
                # Płyta na CHD: brak SAMEGO opisu ścieżek (.cue/.gdi/.toc) NIE
                # blokuje — zsyntetyzujemy go z torów danych (o ile wszystkie
                # tory danych są). Reszta przypadków (brak toru danych, inne
                # formaty) → pomiń, jak dotąd.
                only_desc_missing = fmt == "chd" and all(
                    s.rom.name.rsplit(".", 1)[-1].lower() in _DISC_DESC_EXTS
                    for s in _miss)
                if not only_desc_missing:
                    continue
            if any(s.via_chd or s.via_archive for s in sts):
                # źródło/wynik to CHD lub całe archiwum — konwersji nie robimy.
                is_havechd = (all(s.state in (RomState.HAVE, RomState.HAVE_CHD)
                                  for s in sts)
                              and any(s.state == RomState.HAVE_CHD
                                      for s in sts))
                # HIERARCHIA rodzic/dziecko dla gier na CHD. Opieramy się na
                # WŁASNEJ ścieżce kanonicznej gry (deterministycznie), nie na
                # tym, który CHD zwrócił matcher (kolejność DB bywa różna).
                # Pierwsze wystąpienie odcisku (RODZIC, raporty parent-first)
                # z fizycznym CHD u siebie = KEEPER; kolejne (DZIECKO) z WŁASNYM
                # fizycznym CHD → skasuj błędną kopię i wstaw symlink do rodzica.
                # „w child tylko linki".
                if any(s.via_chd for s in sts) and index is not None:
                    prof = game_profile(game.data_roms)
                    # dedup CHD też w OBRĘBIE PLATFORMY (cross-platform = oba fizyczne)
                    pkey = (_plat_key(rep.entry), prof) if prof else None
                    own = rep.entry.target_dir / f"{game.name}.chd"
                    if prof:
                        keeper = final_by_profile.get(pkey)
                        # STAN WŁASNEGO CHD z INDEKSU (lokalny SQLite), a NIE stat
                        # na NAS: os.path.isfile/lstat PER GRA na dysku sieciowym
                        # to były „przystanki" w „Znajdź naprawy" (tysiące gier
                        # CHD = tysiące zapytań SMB). Indeks jest świeży po skanie;
                        # realny relink i tak re-weryfikuje przed zmianą.
                        try:
                            orow = index.lookup(own)
                        except Exception:
                            orow = None
                        # zawartość WŁASNEGO pliku musi pasować do gry, inaczej
                        # to obcy plik — nie ruszamy (żadnych strat).
                        own_phys = bool(orow is not None
                                        and not orow["is_link"]
                                        and not orow["missing"])
                        own_ok = bool(own_phys
                                      and (orow["data_sha1"] or "").lower()
                                      == prof.lower())
                        cn = os.path.normcase(os.path.abspath(str(own)))
                        if keeper is None and own_ok:
                            # RODZIC — jego fizyczny CHD zostaje keeperem
                            final_by_profile[pkey] = own
                        elif (not is_parent and keeper is not None and own_ok
                              and os.path.normcase(os.path.abspath(
                                  str(keeper))) != cn):
                            # DZIECKO z redundantnym fizycznym CHD → relink
                            # (gra z katalogu-RODZICA nigdy: zostaje fizyczna)
                            if _relink_verified_duplicate(
                                    own, keeper, prof, index,
                                    make_links, _links_blocked, dry_run, log):
                                st.relinked += 1
                                if on_converted is not None and not dry_run:
                                    on_converted(own)
                # LUŹNE fizyczne tory tej gry w katalogu DOCELOWYM (błędnie
                # wypakowane wcześniej) — gra jest na CHD, więc je sprzątamy.
                if index is not None:
                    st.tosort_purged += _purge_child_loose_duplicates(
                        game, _loose_by_sha1(rep.entry.target_dir),
                        _needed_sha1, index, log, dry_run)
                # ALE gdy CHD jest JUŻ w docelowym (HAVE_CHD), a luźne ścieżki
                # tej gry wciąż leżą w ToSort — posprzątaj je (redundantne).
                if (del_prefixes and index is not None and not dry_run
                        and is_havechd):
                    st.tosort_purged += _purge_redundant_tosort_tracks(
                        game, index, del_prefixes, _needed_sha1, log,
                        needed_crc=_needed_crc, kept_shared=_kept_shared)
                continue
            if all(s.state in (RomState.HAVE, RomState.HAVE_CHD) for s in sts):
                # NAPRAWA W MIEJSCU: platforma dyskowa (fmt=chd), a KOMPLET gry
                # leży LUŹNO w katalogu docelowym (bin/cue/iso). Ustawienie DAT
                # „płyty jako CHD" wymaga konwersji, mimo że pliki są „na
                # miejscu" (HAVE) — bo to zły FORMAT, nie brak. NIE pomijamy:
                # spadamy niżej do konwersji ze źródła (źródłem są luźne pliki z
                # kolekcji; po zweryfikowanym CHD luźne tory sprząta blok na
                # końcu). Pozostałe formaty (rvz-jednoplikowy już jako .rvz,
                # zip/keep) są FAKTYCZNIE zaspokojone → pomijamy jak dotąd.
                _loose_disc_in_place = (
                    fmt == "chd"
                    and not any(s.state == RomState.HAVE_CHD for s in sts))
                if not _loose_disc_in_place:
                    # zaspokojona bez konwersji — jeśli przez CHD i luźne kopie
                    # leżą w ToSort, też posprzątaj
                    if (del_prefixes and index is not None and not dry_run
                            and any(s.state == RomState.HAVE_CHD for s in sts)):
                        st.tosort_purged += _purge_redundant_tosort_tracks(
                            game, index, del_prefixes, _needed_sha1, log,
                            needed_crc=_needed_crc, kept_shared=_kept_shared)
                    continue
            if on_progress:
                on_progress(gi, n_total, f"konwersja (ze źródła): {game.name}")
            key = f"{id(rep.entry)}::{game.name}"
            prof = game_profile(game.data_roms)
            # KLUCZ DEDUP zawężony do PLATFORMY — cross-platformowe duble treści
            # zostają OBA fizyczne (patrz komentarz przy _shared_profiles).
            pkey = (_plat_key(rep.entry), prof) if prof else None

            # DUPLIKAT (dziecko, np. 1G1R): ten sam odcisk zawartości już
            # zrobiony przez rodzica → SYMLINK z WŁASNĄ nazwą do pliku rodzica,
            # NIE druga kopia. Nazwa dziecka może się różnić (inny DAT). Gra z
            # katalogu-RODZICA NIE linkuje (zawsze fizyczna) — patrz is_parent.
            if not is_parent and pkey is not None and pkey in final_by_profile:
                parent_final = final_by_profile[pkey]
                ext = parent_final.suffix
                child_final = rep.entry.target_dir / f"{game.name}{ext}"
                if _link_child_to_parent(child_final, parent_final, make_links,
                                         _links_blocked, dry_run, log):
                    done.add(key)
                    if on_converted is not None and not dry_run:
                        on_converted(child_final)
                    # źródła dziecka są współdzielone z rodzicem → odrocz/kasuj
                    _defer_or_purge_game_sources(sts, shared_srcs, deferred,
                                                 index, dry_run, log)
                continue

            # Gra ze WSPÓŁDZIELONYM odciskiem (rodzic grupy rodzic→dziecko) NIE
            # idzie potokiem: dziecko (dalej w pętli) linkuje do FIZYCZNIE gotowego
            # rodzica, a potok finalizuje poza kolejnością i ustawia `final` PRZED
            # sukcesem — link mógłby wisieć. Taki rodzic → konwersja SERYJNA
            # (blokująca), `final_by_profile` ustawiane dopiero po sukcesie.
            _pipe_ok = _pipe is not None and (
                pkey is None or pkey not in _shared_profiles)
            if _pipe_ok:
                # POTOK: zleć zadanie (pobranie→konwersja→wysyłka w tle); finalize
                # (indeks/źródła) i tak w TYM wątku (SQLite jednowątkowe).
                pjob = _conv_prepare(rep.entry, game, sts, fmt, tools, log)
                if pjob is not None:
                    # scratch PER GRA: RAM-dysk gdy się mieści, inaczej fizyczny
                    # (duże PS2 nie przepełnią R:). None → brak miejsca nigdzie →
                    # nie zlecamy, fallback placement dokończy.
                    sc = _conv_scratch_for(pjob["roms"], fmt, pjob["target_dir"],
                                           None, tools, pjob["base"], log)
                    if sc is not None:
                        pjob["scratch"] = sc
                        cost = int(sum(max(r.size, 0)
                                       for r in pjob["roms"]) * 1.7)
                        _fed.append((key, _pipe.feed(pjob, cost=cost)))
                        done.add(key)
                        if pkey is not None:
                            final_by_profile[pkey] = pjob["final"]
                # pjob None / brak scratcha → nie oznaczamy done → fallback
            else:
                res = _convert_game_from_source(
                    rep.entry, game, sts, fmt, subdir, tools, index, dry_run, log,
                    st, detail, deferred, on_converted, shared_srcs,
                    scratch_override=None)
                if res is not None:
                    done.add(key)
                    if pkey is not None:
                        final_by_profile[pkey] = res

    if _pipe is not None:
        _pipe.drain()                    # dokończ i zfinalizuj wszystkie (kolejno)
        _pipe.close()
        for k, h in _fed:                # nieudane → cofnij z done (placement dokończy)
            if getattr(h, "failed_stage", ""):
                done.discard(k)
    # SPRZĄTANIE PO KONWERSJI NA CHD: gdy gra jest na (ZWERYFIKOWANYM) CHD, a OBOK
    # leżą pozostałości tej samej treści — REDUNDANTNE archiwum `<gra>.zip/.7z`
    # (zły format / import) ORAZ LUŹNE tory `.bin/.cue/.gdi` (np. Dreamcast po
    # konwersji) → kasujemy (treść żyje w CHD). Robione TU (per gra, ODPORNE na
    # Przerwij), a nie w globalnym „clean" na końcu naprawy, który przy przerwaniu
    # jest pomijany — stąd user widział zip+chd (3DO) i bin/cue+chd (Dreamcast).
    if index is not None:
        for rep in reports:
            if cancel is not None and cancel.is_set():
                break
            eff = rules_fn(rep.entry)
            if eff.get("skip"):
                continue
            if resolve_format(eff.get("format", "keep"), rep.entry) != "chd":
                continue                 # tylko platformy dyskowe (kanoniczny CHD)
            tdir = rep.entry.target_dir
            _lmap = None                 # mapa luźnych sha1→ścieżki (leniwie, raz)
            for game in rep.entry.games:
                st.tosort_purged += _purge_redundant_target_archives(
                    game, tdir, index, log, dry_run, needed_sha1=_needed_sha1)
                # LUŹNE tory (Dreamcast bin/cue/gdi itp.): tylko gdy gra na CHD
                gsha = {(r.sha1 or "").lower() for r in game.roms if r.sha1}
                if not gsha:
                    continue
                if _lmap is None:
                    _lmap = _loose_by_sha1(tdir)
                if not any(s in _lmap for s in gsha):
                    continue             # brak luźnych kandydatów → 0 I/O NAS
                if not _disc_on_verified_chd(game, tdir, index, dry_run):
                    continue             # CHD niezweryfikowany → NIE kasujemy
                st.tosort_purged += _purge_child_loose_duplicates(
                    game, _lmap, _needed_sha1, index, log, dry_run)
    # NIE kasujemy tu — oryginalne źródła (unikalne) zwracamy, a kasuje je
    # dopiero KONIEC całej naprawy (po placemencie i fallbacku), żeby żadna
    # współdzielona ścieżka nie zniknęła zanim ktoś jej jeszcze potrzebuje.
    uniq = list({os.path.normcase(str(p)): p for p in deferred}.values())
    return st, done, uniq


def purge_loose_on_verified_chd(reports, rules_fn, index, *,
                                log: LogCB = lambda m: None, dry_run: bool = False,
                                cancel=None) -> int:
    """BEZPIECZNY, PRZERYWALNY przebieg czyszczący pozostałości gier JUŻ na CHD.

    Dla każdej gry, która jest na ZWERYFIKOWANYM CHD w katalogu docelowym
    (`data_sha1 == game_profile`), kasuje redundantną tę samą treść leżącą obok:
    luźne tory `.bin/.cue/.gdi` ORAZ archiwum `<gra>.zip/.7z` — treść żyje w CHD.
    Usuwa też opustoszały podkatalog `<gra>\\`.

    W ODRÓŻNIENIU od zmiatania do ToSort i dedupu (które przy niepełnym dopasowaniu
    mogą uznać znany plik za śmieć i dlatego są POMIJANE po Przerwaniu) — to jest
    kasowanie per-gra o UDOWODNIONEJ redundancji (zweryfikowany CHD tej samej
    treści), więc NIE wymaga pełnego obrazu kolekcji i jest bezpieczne nawet po
    przerwaniu. Dzięki temu można je puścić NA POCZĄTKU naprawy i sprząta
    pozostałości po wcześniejszych przebiegach (CHD z ToSort, a docelowe bin/cue
    nietknięte), niezależnie od tego, jak wcześnie użytkownik przerwie."""
    if index is None:
        return 0
    from collections import defaultdict
    from .matcher import RomState
    from .dirrules import resolve_format
    # OCHRONA `needed_sha1`: NIE kasuj luźnego toru, jeśli potrzebuje go inna gra,
    # która NAPRAWDĘ powstanie w tej naprawie. KLUCZOWE zawężenie: tylko gry
    # BUDOWALNE — takie, które mają WSZYSTKIE tory DANYCH obecne (choćby pod złą
    # nazwą / w ToSort). Gra BRAKUJĄCA (brak toru danych, np. 6800 płyt z DAT-a,
    # których user nie ma) NIGDY nie powstanie, więc nie ma sensu chronić dla niej
    # współdzielonych torów audio — a to właśnie one blokowały całe sprzątanie
    # (każdy tor „potrzebny" jakiejś brakującej grze). Współdzielony tor i tak
    # potrzebny jest tylko w JEDNYM miejscu, a jego treść żyje w zweryfikowanym CHD.
    _DESC = (".cue", ".gdi", ".toc")
    needed_sha1: set = set()
    for rep in reports:
        bg: dict = defaultdict(list)
        for s in rep.statuses:
            bg[s.game].append(s)
        for sts in bg.values():
            unsat = any(s.state in (RomState.ELSEWHERE, RomState.WRONG_NAME,
                                    RomState.MISSING, RomState.NO_HASH)
                        for s in sts)
            if not unsat:
                continue
            data = [s for s in sts
                    if not s.rom.name.lower().endswith(_DESC)]
            buildable = bool(data) and all(
                s.state not in (RomState.MISSING, RomState.NO_HASH) for s in data)
            if not buildable:
                continue                      # gra brakująca → nie chroni torów
            for s in sts:
                if s.rom.sha1:
                    needed_sha1.add(s.rom.sha1.lower())
    loose_cache: dict = {}

    def _loose(td) -> dict:
        k = os.path.normcase(str(td))
        m = loose_cache.get(k)
        if m is None:
            m = {}
            try:
                for row in index.all_under(td, physical_only=True):
                    p = row["path"]
                    if p.lower().endswith(".chd") or row["missing"]:
                        continue
                    s = (row["sha1"] or "").lower()
                    if s:
                        m.setdefault(s, []).append(p)
            except Exception:
                m = {}
            loose_cache[k] = m
        return m

    n = 0
    for rep in reports:
        if cancel is not None and cancel.is_set():
            break
        eff = rules_fn(rep.entry)
        if eff.get("skip"):
            continue
        if resolve_format(eff.get("format", "keep"), rep.entry) != "chd":
            continue                          # tylko platformy dyskowe (CHD)
        tdir = rep.entry.target_dir
        lmap = None
        for game in rep.entry.games:
            if cancel is not None and cancel.is_set():
                break
            n += _purge_redundant_target_archives(
                game, tdir, index, log, dry_run, needed_sha1=needed_sha1)
            gsha = {(r.sha1 or "").lower() for r in game.roms if r.sha1}
            if not gsha:
                continue
            if lmap is None:
                lmap = _loose(tdir)
            if not any(s in lmap for s in gsha):
                continue                      # brak luźnych kandydatów → 0 I/O
            if not _disc_on_verified_chd(game, tdir, index, dry_run):
                continue                      # CHD niezweryfikowany → NIE kasujemy
            n += _purge_child_loose_duplicates(
                game, lmap, needed_sha1, index, log, dry_run)
    return n


def _disc_on_verified_chd(game, target_dir, index, dry_run) -> bool:
    """Czy gra JEST na kanonicznym, ZWERYFIKOWANYM CHD w katalogu docelowym:
    `<gra>.chd` w indeksie fizyczny (nie link/missing) i `data_sha1 == game_profile`
    (to NA PEWNO treść tej gry). W realnym biegu dokładamy FIZYCZNY dowód
    (os.path) — indeks bywa nieaktualny, a kasujemy po tym luźne tory/archiwa."""
    if index is None:
        return False
    from .datfile import game_profile
    prof = game_profile(game.data_roms)
    if not prof:
        return False
    chd = Path(target_dir) / f"{game.name}.chd"
    crow = index.lookup(chd)
    if (crow is None or crow["is_link"] or crow["missing"]
            or (crow["data_sha1"] or "").lower() != prof.lower()):
        return False
    if not dry_run and not chd.is_file():
        return False
    return True


def _purge_redundant_target_archives(game, target_dir, index, log, dry_run,
                                     needed_sha1=None) -> int:
    """Gra jest już na CHD → archiwum `<gra>.zip/.7z` LEŻĄCE OBOK niej w katalogu
    docelowym jest REDUNDANTNE (ta sama treść jest w CHD) → kasujemy.

    Bezpieczniki (nic nie kasujemy, jeśli którykolwiek nie spełniony):
    - kanoniczny `<gra>.chd` jest w indeksie FIZYCZNIE (nie link/missing) i ma
      `data_sha1 == game_profile` (CHD to ZWERYFIKOWANA treść tej gry),
    - archiwum jest FIZYCZNE, a jego CZŁONKOWIE to WYŁĄCZNIE ścieżki tej gry
      (sumy ⊆ sum ROM-ów gry) — nie kasujemy nadzbioru/cudzego archiwum,
    - żadna suma nie jest jeszcze POTRZEBNA innej niezaspokojonej grze
      (needed_sha1),
    - FIZYCZNY dowód istnienia (os.path) tuż przed usunięciem (indeks bywa
      nieaktualny). NAS-owe staty robimy DOPIERO, gdy w indeksie jest kandydat.
    dry_run → tylko „(podgląd)". Zwraca liczbę skasowanych archiwów."""
    if index is None:
        return 0
    from .datfile import game_profile
    from .linker import is_link
    prof = game_profile(game.data_roms)
    if not prof:
        return 0
    target_dir = Path(target_dir)
    chd = target_dir / f"{game.name}.chd"
    crow = index.lookup(chd)
    if (crow is None or crow["is_link"] or crow["missing"]
            or (crow["data_sha1"] or "").lower() != prof.lower()):
        return 0
    game_sha = {r.sha1.lower() for r in game.data_roms if r.sha1}
    if not game_sha:
        return 0
    n = 0
    for ext in (".zip", ".7z"):
        arch = target_dir / f"{game.name}{ext}"
        arow = index.lookup(arch)
        if arow is None or arow["is_link"] or arow["missing"]:
            continue                       # brak kandydata w indeksie → 0 I/O NAS
        # Porównujemy tylko TORY DANYCH (bez .cue/.gdi/.toc — cue bywa inaczej
        # wygenerowany, ale to nie zmienia tożsamości gry). Każdy tor danych
        # archiwum MUSI być torem tej gry; brak sumy = nie ruszamy (bezpiecznik).
        _desc = (".cue", ".gdi", ".toc")
        mdata: set = set()
        _bad = False
        for m in index.members_of(arch):
            if os.path.splitext(m["name"])[1].lower() in _desc:
                continue
            sh = (m["sha1"] or "").lower()
            if not sh:
                _bad = True
                break
            mdata.add(sh)
        if _bad or not mdata or not mdata.issubset(game_sha):
            continue                       # archiwum ma tor spoza tej gry
        if needed_sha1 and (mdata & needed_sha1):
            continue                       # jeszcze potrzebne gdzie indziej
        # FIZYCZNY dowód (dopiero teraz staty NAS — tylko dla realnych dubli)
        if not dry_run and not (chd.is_file() and arch.is_file()
                                and not is_link(arch)):
            continue
        log(("(podgląd) " if dry_run else "")
            + f"KASUJ redundantne archiwum (gra jest na CHD): {arch}")
        if not dry_run:
            try:
                os.unlink(arch)
                index.remove_path(arch)
            except OSError as e:
                log(f"  nie skasowano {arch}: {e}")
                continue
        n += 1
    return n


def purge_source_files(paths, index=None, log: LogCB = lambda m: None,
                       dry_run: bool = False) -> int:
    """Kasuje ORYGINALNE pliki źródłowe skonsumowane przez konwersję ze źródła.
    Wołane na SAMYM KOŃCU naprawy — współdzielone ścieżki gier wielopłytowych
    były dostępne do końca. Zwraca liczbę skasowanych."""
    if not paths or dry_run:
        return 0
    n = 0
    parents: dict = {}
    for p in paths:
        try:
            os.unlink(p)
            if index is not None:
                index.remove_path(p)
            n += 1
            pd = Path(p).parent
            parents[os.path.normcase(str(pd))] = pd
        except OSError:
            pass
    # opustoszałe podkatalogi `<gra>\` po zabraniu wszystkich (także współdzielonych)
    # torów — teraz mogą być już puste; rmdir cicho odpada gdy coś zostało.
    for pd in parents.values():
        _rmdir_if_empty(pd, log)
    if n:
        log(f"Skasowano {n} plików źródłowych po konwersji ze źródła "
            f"(współdzielone ścieżki były dostępne do końca).")
    return n


def _try_disc_archive_chd(entry, game, archive, tools, index, log, st, detail,
                          on_converted, final_by_profile, pkey=None) -> bool:
    """Buduje CHD gry-płyty WPROST z jej archiwum (cue/gdi w środku), umieszcza
    finał w docelowym, wpisuje odcisk (game_profile) do indeksu. True gdy OK.
    Używane, gdy DAT-owy cue nie pasuje nazwą, ale cue jest w archiwum."""
    from .scratch import pick_scratch_root
    chd = tools.get("chdman")
    if chd is None:
        return False
    target_dir = entry.target_dir
    final = target_dir / f"{game.name}.chd"
    try:
        need = int(sum(max(r.size, 0) for r in game.roms) * 2.4)
    except Exception:
        need = 0
    scratch = pick_scratch_root(
        need, prefer=str(target_dir), log=log,
        fallback=getattr(tools.get("settings"), "scratch_dir", "") or None)
    if scratch is None:
        return False
    import tempfile
    work = Path(tempfile.mkdtemp(prefix="chdbuddy_da_", dir=str(scratch)))
    tmp_out = work / final.name
    try:
        def _dtl(pct, msg=""):
            if detail is not None:
                detail(int(pct), 100, f"CHD {game.name}: {msg or f'{int(pct)}%'}")
        r = disc_archive_to_chd(archive, tmp_out, chd, tools["settings"],
                                scratch=work, log=log, on_progress=_dtl)
        if r is None or not r.ok:
            return False
        built = r.dst if (r.dst and Path(r.dst).is_file()) else tmp_out
        if not Path(built).is_file():
            return False
        # STRAŻNIK TREŚCI: zbudowany CHD MUSI mieć zawartość TEJ gry. Archiwum
        # buduje się z WŁASNEGO cue, więc treść = treść archiwum — jeśli to
        # było cudze archiwum (współdzielony tor), powstałby CHD złej gry pod
        # tą nazwą. Round-trip (źródło↔chd) tego NIE łapie — sprawdza kodowanie.
        if not _content_matches_game(Path(built), game, chd, work, log):
            log(f"  ODRZUCONE: treść zbudowanego CHD nie odpowiada grze "
                f"„{game.name}” (archiwum {archive.name} to inna płyta lub "
                f"tylko współdzielony tor) — NIE umieszczam, źródło zostaje.")
            return False
        target_dir.mkdir(parents=True, exist_ok=True)
        log(f"  finał → {final}")
        _place_cross(Path(built), final, detail=detail,
                     label=f"przenoszę {final.name}")
        try:
            from .datfile import game_profile
            crc, md5, sha1 = hash_file(final)
            index.record_file(final, crc, md5, sha1)
            prof = game_profile(game.data_roms)
            if prof:
                index.set_data_sha1(final, prof)
                if pkey is not None:
                    final_by_profile[pkey] = final
        except OSError:
            pass
        if on_converted is not None:
            on_converted(final)
        st.converted += 1
        return True
    finally:
        import shutil as _sh
        _sh.rmtree(work, ignore_errors=True)


def _conv_scratch_for(roms, fmt, target_dir, scratch_override, tools, base, log):
    """Katalog scratch dla konwersji — PER GRA (RAM-dysk gdy gra się mieści),
    a `scratch_override` (dysk z budżetu ×10) to tylko FALLBACK dla gier ZA
    DUŻYCH na RAM. Dawniej override był zwracany OD RAZU → nawet mała gra szła na
    dysk z budżetu (np. NAS Z:), bo ×10 największej gry (348 GB) nie mieści się na
    RAM-dysku — a przecież pojedyncza gra i owszem. None = brak miejsca nigdzie."""
    from .scratch import pick_scratch_root
    try:
        need = int(sum(max(r.size, 0) for r in roms)
                   * (_FREE_FACTOR.get(fmt, 1.5) + 1.0))
    except Exception:
        need = 0
    # RAM-dysk najpierw (pick_scratch_root ma go w priorytecie, gdy `need` się
    # mieści); override i scratch_dir z ustawień to fallback dla dużych gier.
    fb = (str(scratch_override) if scratch_override
          else getattr(tools.get("settings"), "scratch_dir", "") or None)
    sc = pick_scratch_root(need, prefer=str(target_dir), log=log, fallback=fb)
    if sc is None and scratch_override is not None:
        sc = Path(scratch_override)          # ostatnia deska: dysk z budżetu
    if sc is None:
        log(f"POMIJAM (ze źródła) {base}: brak miejsca (~{need/1024**3:.1f} GB)")
    return sc


def _conv_gather_phase(job, log):
    """ETAP 1 (I/O): źródła NAS→RAM w katalogu roboczym. Zwraca listę zebranych
    plików albo None (niezgodność → fallback placement). Katalog roboczy zawsze
    tworzony (sprząta go `_conv_release`)."""
    import tempfile
    from .scratch import resilient_dir
    # ODPORNE na ZNIKNIĘCIE scratchu w trakcie (RAM-dysk odmontowany nagle):
    # utwórz katalog tuż przed użyciem, spróbuj odtworzyć RAM-dysk, a gdy się nie
    # da — systemowy temp (dysk fizyczny), byle konwersja szła dalej.
    scratch = resilient_dir(job["scratch"], log=log)
    work = Path(tempfile.mkdtemp(prefix="chdbuddy_src_", dir=str(scratch)))
    ram_in = work / "in"
    ram_in.mkdir()
    job["work"] = work
    job["ram_in"] = ram_in
    gathered = []
    for r in job["roms"]:
        s = job["st_by_rom"][r.name]
        _src = s.source_path + (f"::{s.member}" if s.member else "")
        log(f"  źródło: {_src}")
        g = _gather_track_to_ram(s, ram_in, log)
        if g is None:
            return None
        gathered.append(g)
    job["gathered"] = gathered
    return gathered


def _conv_build_phase(job, tools, log, detail, slot=None):
    """ETAP 2 (CPU): kompresja na RAM (zip/chd/rvz) + strażnik treści. Zwraca
    ścieżkę zbudowanego pliku albo None (pominięcie — źródło zostaje).

    Gdy potok działa RÓWNOLEGLE, każde zadanie ma swój numer slotu w
    `job["_pipe_slot"]` — postęp idzie wtedy na WŁASNY pasek (`slot(idx,…)`),
    nie na wspólny `detail`. Slot zwalniamy na końcu (chowamy pasek)."""
    fmt = job["fmt"]
    base = job["base"]
    game = job["game"]
    gathered = job["gathered"]
    work = job["work"]
    ram_in = job["ram_in"]
    final = job["final"]

    _sidx = job.get("_pipe_slot") if isinstance(job, dict) else None
    _use_slot = slot is not None and _sidx is not None
    if _use_slot:
        def _dtl(d, t, txt):
            slot(_sidx, d, t, txt)
    else:
        def _dtl(d, t, txt):
            if detail is not None:
                detail(d, t, txt)

    try:
        return _conv_build_run(job, tools, log, _dtl, fmt, base, game,
                               gathered, work, ram_in, final)
    finally:
        if _use_slot:
            slot(_sidx, -1, 0, "")            # zwolnij pasek slotu


def _conv_build_run(job, tools, log, _dtl, fmt, base, game, gathered, work,
                    ram_in, final):
    """Właściwa kompresja (patrz _conv_build_phase); `_dtl` kieruje postęp na
    slot równoległy albo wspólny pasek `detail`."""
    tmp_out = work / final.name
    if fmt == "zip":
        _dtl(0, 0, f"pakowanie ZIP: {base}")
        r = pack_zip(gathered, tmp_out, log=log,
                     level=getattr(tools.get("settings"), "zip_level", 6),
                     method=getattr(tools.get("settings"), "zip_method",
                                    "deflate"))
        cue_synth = False
    elif fmt == "chd":
        main = min(gathered, key=lambda f: (_DISC_MAIN_PRIORITY.get(
            f.suffix.lower().lstrip("."), 9), f.name.lower()))
        chd = tools.get("chdman")
        if chd is None:
            log("  brak chdman — pomijam")
            return None
        cue_synth = False
        if main.suffix.lower().lstrip(".") not in _CHD_SOURCE_EXTS:
            cue = ram_in / f"{base}.cue"
            if not _synthesize_cue(gathered, cue, log):
                log(f"  POMIJAM CHD {base}: brak opisu ścieżek i żadnego "
                    f".bin do syntezy cue.")
                return None
            main = cue
            cue_synth = True
        _dtl(0, 0, f"kompresja CHD: {base}")
        r = disc_to_chd(main, tmp_out, chd, tools["settings"], log=log,
                        on_progress=lambda pct, msg="": _dtl(
                            int(pct), 100, f"CHD {base}: {msg or f'{int(pct)}%'}"))
    else:  # rvz
        iso = next((f for f in gathered if f.suffix.lower() == ".iso"), None)
        dt = tools.get("dolphintool")
        if iso is None or dt is None:
            log(f"  RVZ: brak iso/DolphinTool — pomijam {base}")
            return None
        cue_synth = False
        _dtl(0, 0, f"kompresja RVZ: {base}")
        r = iso_to_rvz(iso, tmp_out, dt, log=log,
                       level=getattr(tools.get("settings"), "rvz_level", 5),
                       block_kb=getattr(tools.get("settings"), "rvz_block_kb", 128))
    if not r.ok:
        log(f"  BŁĄD konwersji {base}: {r.message}")
        return None
    built = r.dst if (r.dst and Path(r.dst).is_file()) else tmp_out
    if not Path(built).is_file():
        return None
    # STRAŻNIK TREŚCI (CHD z syntezowanym cue): obraz MUSI zawierać TĘ grę.
    if fmt == "chd" and cue_synth and not _content_matches_game(
            Path(built), game, tools.get("chdman"), work, log):
        log(f"  ODRZUCONE: zsyntetyzowany układ nie daje treści gry "
            f"„{base}” — NIE umieszczam, źródło zostaje.")
        return None
    job["built"] = Path(built)
    return job["built"]


def _conv_upload_phase(job, detail, log):
    """ETAP 3 (I/O): finał RAM→NAS + policz sumy pliku docelowego. Zwraca
    (crc, md5, sha1); ("","","") gdy przeniesienie OK, ale hash się nie udał."""
    final = job["final"]
    built = job["built"]
    if detail is not None:
        detail(0, 0, f"przenoszę: {final.name}")
    final.parent.mkdir(parents=True, exist_ok=True)
    log(f"  finał → {final}")
    _place_cross(Path(built), final, detail=detail,
                 label=f"przenoszę {final.name}")
    try:
        return hash_file(final)
    except OSError:
        return ("", "", "")


def _conv_finalize_phase(job, sums, index, on_converted, st, shared_srcs,
                         deferred, log):
    """FINALIZACJA (WŁAŚCICIEL, jednowątkowo): zapis do indeksu, callback, licznik,
    odroczenie/kasowanie źródeł."""
    final = job["final"]
    if index is not None and sums and sums[2]:
        try:
            if job["fmt"] == "chd":
                index.record_file(final, sums[0], sums[1], sums[2])
                from .datfile import game_profile
                prof = game_profile(job["game"].data_roms)
                if prof:
                    index.set_data_sha1(final, prof)
            elif str(final).lower().endswith((".zip", ".7z")):
                # ARCHIWUM: zaindeksuj plik ORAZ jego członków, inaczej NASTĘPNY
                # skan wypakowywałby świeżo spakowane archiwum, by policzyć
                # członków (wolny skan „po fix", choć plik stworzył sam program).
                index.reindex_archive(final, full=True)
            else:
                index.record_file(final, sums[0], sums[1], sums[2])  # RVZ itp.
        except OSError:
            pass
    if on_converted is not None:
        on_converted(final)
    st.converted += 1
    _defer_or_purge_game_sources(job["sts"], shared_srcs, deferred, index,
                                 False, log)


def _conv_release(job):
    """ZAWSZE po zadaniu: sprzątnij katalog roboczy (zwalnia RAM/scratch)."""
    import shutil as _sh
    w = job.get("work")
    if w:
        _sh.rmtree(w, ignore_errors=True)


def _conv_prepare(entry, game, sts, fmt, tools, log):
    """Przygotowanie (BEZ I/O): ścieżka finalna, zbieralne tory, walidacja. Zwraca
    słownik-zadanie albo None (gra nie do konwersji tą ścieżką). Wspólne dla skanu
    serialnego i potoku — pozwala pętli poznać `final` przed zleceniem."""
    base = game.name
    target_dir = entry.target_dir
    if fmt == "zip":
        final = target_dir / f"{base}.zip"
    elif fmt == "chd":
        final = target_dir / f"{base}.chd"
    elif fmt == "rvz":
        final = target_dir / f"{base}.rvz"
    else:
        return None
    st_by_rom = {}
    for s in sts:
        st_by_rom.setdefault(s.rom.name, s)
    roms = [r for r in game.roms if r.name in st_by_rom]
    if not roms:
        return None
    from .matcher import RomState

    def _gatherable(r) -> bool:
        s = st_by_rom[r.name]
        return (s.state not in (RomState.MISSING, RomState.NO_HASH)
                and bool(s.source_path))

    if fmt == "chd":
        data_missing = [r for r in roms if not _gatherable(r)
                        and r.name.rsplit(".", 1)[-1].lower()
                        not in _DISC_DESC_EXTS]
        if data_missing:
            log(f"  POMIJAM (ze źródła) {base}: brak torów DANYCH "
                f"{[r.name for r in data_missing]} — nie złożę płyty.")
            return None
        roms = [r for r in roms if _gatherable(r)]     # opis dołożymy syntezą
    elif any(not _gatherable(r) for r in roms):
        return None                                    # kartridż musi mieć wszystko
    if not roms:
        return None
    return {"entry": entry, "game": game, "sts": sts, "fmt": fmt, "base": base,
            "target_dir": target_dir, "final": final, "roms": roms,
            "st_by_rom": st_by_rom}


def _convert_game_from_source(entry, game, sts, fmt, subdir, tools, index,
                              dry_run, log, st, detail, deferred,
                              on_converted, shared_srcs=frozenset(),
                              scratch_override=None) -> bool:
    """Jedna gra SERYJNIE: zbierz ścieżki na RAM → kompresuj → weryfikuj → finał.
    True gdy obsłużona (placement ją pomija). Te same fazy napędza też potok."""
    job = _conv_prepare(entry, game, sts, fmt, tools, log)
    if job is None:
        return None
    base = job["base"]
    final = job["final"]
    roms = job["roms"]
    st_by_rom = job["st_by_rom"]
    target_dir = job["target_dir"]

    # PODGLĄD (dry-run): NIE odpytujemy wolnego miejsca (na NAS to blokujące) —
    # tylko zapowiadamy plan; miejsce sprawdzimy przy faktycznej naprawie.
    if dry_run:
        log(f"KONWERSJA(ze źródła)→{fmt.upper()}: {base}")
        st.converted += 1
        log(f"  finał → {final} (podgląd)")
        for r in roms:
            sp = st_by_rom[r.name].source_path
            if sp:
                deferred.append(Path(sp))
        return final

    # KONWERSJA w 3 FAZACH (te same fazy używa też potok równoległy):
    # gather (I/O) → build (CPU) → upload (I/O), potem finalize (indeks/źródła).
    scratch = _conv_scratch_for(roms, fmt, target_dir, scratch_override,
                                tools, base, log)
    if scratch is None:
        return None
    job["scratch"] = scratch
    log(f"KONWERSJA(ze źródła)→{fmt.upper()}: {base}")
    try:
        if _conv_gather_phase(job, log) is None:
            return None                         # niezgodność → fallback placement
        if _conv_build_phase(job, tools, log, detail) is None:
            return None
        sums = _conv_upload_phase(job, detail, log)
        _conv_finalize_phase(job, sums, index, on_converted, st, shared_srcs,
                             deferred, log)
        return final
    finally:
        if detail is not None:
            detail(-1, 0, "")
        _conv_release(job)


def _place_cross(new: Path, dst: Path, detail=None, label: str = "") -> None:
    """Przenosi gotowy plik na miejsce: os.replace (ten sam dysk, atomowo)
    albo kopia blokami z postępem (między dyskami — RAM → fizyczny)."""
    from .fileops import move_with_progress
    dst.unlink(missing_ok=True)
    move_with_progress(new, dst, on_progress=detail, label=label)


def _convert_one(files, target_dir, base, fmt, subdir, n_roms, tools, index,
                 dry_run, log, st, detail=None, on_converted=None,
                 deferred=None, deferred_dirs=None, game=None) -> bool:
    import shutil as _sh
    import tempfile
    from .scratch import pick_scratch_root
    _settings = tools.get("settings")
    dst_dir = (target_dir / base if subdir and n_roms > 1 else target_dir)
    # docelowa ścieżka finalnego pliku
    if fmt == "zip":
        final = (dst_dir.parent if subdir and n_roms > 1 else target_dir) \
            / f"{base}.zip"
    elif fmt == "chd":
        final = target_dir / f"{base}.chd"
    elif fmt == "rvz":
        final = target_dir / f"{base}.rvz"
    else:
        return False
    log(f"KONWERSJA→{fmt.upper()}: {base}")
    if dry_run:
        return True

    # BUDUJEMY na SCRATCH (RAM, gdy się mieści) — nie na dysku docelowym.
    # Dzięki temu D: nie potrzebuje miejsca na (źródło + nowy plik) naraz:
    # po weryfikacji KASUJEMY źródło (zwalnia D:), potem przenosimy gotowy
    # plik na miejsce. Zajętość dysku kolekcji nie rośnie.
    try:
        need = int(sum(f.stat().st_size for f in files)
                   * _FREE_FACTOR.get(fmt, 1.5))
    except OSError:
        need = 0
    scratch = pick_scratch_root(
        need, prefer=str(target_dir), log=log,
        fallback=getattr(_settings, "scratch_dir", "") or None)
    if scratch is None:
        log(f"POMIJAM {base}: brak miejsca (RAM/dysk) na ~{need/1024**3:.1f} GB")
        st.skipped += 1
        return False
    work = Path(tempfile.mkdtemp(prefix="chdbuddy_conv_", dir=str(scratch)))
    tmp_out = work / final.name
    synth_cue = None          # tymczasowy cue obok binów (sprzątany w finally)

    def _dtl(done: int, total: int, text: str) -> None:
        if detail is not None:
            detail(done, total, text)

    try:
        if fmt == "zip":
            _dtl(0, 0, f"pakowanie ZIP: {base}")     # szybkie — pasek pulsuje
            r = pack_zip(files, tmp_out, log=log,
                         level=getattr(_settings, "zip_level", 6),
                         method=getattr(_settings, "zip_method", "deflate"))
        elif fmt == "chd":
            main = min(files, key=lambda f: (_DISC_MAIN_PRIORITY.get(
                f.suffix.lower().lstrip("."), 9), f.name.lower()))
            chd = tools.get("chdman")
            if chd is None:
                log("  brak chdman — pomijam"); st.errors += 1; return False
            # createcd/dvd POTRZEBUJE opisu ścieżek (cue/gdi/toc) albo obrazu
            # (iso/img). GOŁY .bin bez opisu → ZSYNTETYZUJ cue OBOK binów
            # (createcd czyta tory względem katalogu cue). Nigdy nie wołamy
            # createcd na gołym binie (zawiesza się) — dajemy mu cue.
            if main.suffix.lower().lstrip(".") not in _CHD_SOURCE_EXTS:
                cue = target_dir / f"{base}.chdbuddy_synth.cue"
                if not _synthesize_cue(files, cue, log):
                    log(f"  POMIJAM CHD {base}: brak opisu ścieżek i żadnego "
                        f".bin do syntezy cue.")
                    st.skipped += 1
                    return False
                synth_cue = cue
                main = cue
            log(f"  (z {main.name})")
            _dtl(0, 0, f"kompresja CHD: {base}")
            r = disc_to_chd(
                main, tmp_out, chd, tools["settings"], log=log,
                on_progress=lambda pct, msg="": _dtl(
                    int(pct), 100, f"CHD {base}: {msg or f'{int(pct)}%'}"))
        else:  # rvz
            iso = next((f for f in files if f.suffix.lower() == ".iso"), None)
            dt = tools.get("dolphintool")
            if iso is None or dt is None:
                log(f"  RVZ: brak iso/DolphinTool — pomijam {base}")
                st.errors += 1; return False
            _dtl(0, 0, f"kompresja RVZ: {base}")      # DolphinTool bez % — pulsuje
            r = iso_to_rvz(iso, tmp_out, dt, log=log,
                           level=getattr(_settings, "rvz_level", 5),
                           block_kb=getattr(_settings, "rvz_block_kb", 128))

        if not r.ok:
            log(f"  BŁĄD konwersji {base}: {r.message}")
            st.errors += 1
            return False
        # r.dst może wskazywać plik pod inną nazwą (fixer stem) — znormalizuj
        built = r.dst if (r.dst and Path(r.dst).is_file()) else tmp_out
        if not Path(built).is_file():
            log(f"  BŁĄD: brak pliku wyjściowego {base}"); st.errors += 1
            return False
        # STRAŻNIK TREŚCI (CHD): tylko przy ZSYNTETYZOWANYM cue (układ niepewny)
        # i gdy znamy grę — zbudowany obraz MUSI ją zawierać (ekstrakcja +
        # game_profile). Przy realnym cue/iso treść odpowiada źródłu (round-trip).
        if (fmt == "chd" and synth_cue is not None and game is not None
                and not _content_matches_game(
                    Path(built), game, tools.get("chdman"), work, log)):
            log(f"  ODRZUCONE: zsyntetyzowany układ nie daje treści gry "
                f"„{base}” — NIE umieszczam, źródło zostaje.")
            st.skipped += 1
            return False
        # gotowy plik ZWERYFIKOWANY (round-trip/verify). SHA-1 zawartości
        # źródła (do indeksu) POBIERAMY PRZED skasowaniem źródła.
        data_sha1 = ""
        if fmt == "chd" and index is not None:
            # ODCISK ZAWARTOŚCI = game_profile (to samo, co liczy matcher po
            # ekstrakcji). Bez tego następny skan wypakowałby CHD niepotrzebnie.
            try:
                if game is not None:
                    from .datfile import game_profile
                    data_sha1 = game_profile(game.data_roms)
                if not data_sha1:            # brak gry → fallback: suma źródła
                    row = index.lookup(min(files, key=lambda f: (
                        _DISC_MAIN_PRIORITY.get(f.suffix.lower().lstrip("."), 9),
                        f.name.lower())))
                    if row is not None:
                        data_sha1 = row["sha1"] or ""
            except Exception:
                data_sha1 = ""
        # 1) UMIEŚĆ gotowy plik na miejscu (RAM/scratch → D:, cross-drive).
        #    Źródła NIE kasujemy tu od razu — patrz niżej: przy grach
        #    WIELOPŁYTOWYCH współdzielona ścieżka musi zostać dostępna dla
        #    kolejnych płyt zestawu; kasujemy DOPIERO po całej konwersji.
        _dtl(0, 0, f"przenoszę: {final.name}")
        _place_cross(Path(built), final, detail=detail,
                     label=f"przenoszę {final.name}")
        # 2) źródło: odroczone (kasuje convert_reports po WSZYSTKICH grach)
        #    albo natychmiast (gdy wołane bez listy odroczeń).
        if deferred is not None:
            deferred.extend(Path(f) for f in files)
            if subdir and n_roms > 1 and deferred_dirs is not None:
                deferred_dirs.append(target_dir / base)
        else:
            for f in files:
                try:
                    os.unlink(f)
                    if index is not None:
                        index.remove_path(f)
                except OSError:
                    pass
            if subdir and n_roms > 1:
                try:
                    (target_dir / base).rmdir()
                except OSError:
                    pass
        if index is not None:
            try:
                crc, md5, sha1 = hash_file(final)
                index.record_file(final, crc, md5, sha1)
                if data_sha1:
                    index.set_data_sha1(final, data_sha1)
            except OSError:
                pass
        # zgłoś NOWĄ ścieżkę kanoniczną — inaczej faza sprzątania uznałaby
        # świeży CHD/RVZ/ZIP za nieznany i wrzuciła go do ToSort
        if on_converted is not None:
            on_converted(final)
        return True
    finally:
        _dtl(-1, 0, "")          # schowaj pasek szczegółowy po tym pliku
        if synth_cue is not None:
            try:
                synth_cue.unlink(missing_ok=True)   # nasz tymczasowy cue
            except OSError:
                pass
        _sh.rmtree(work, ignore_errors=True)


