"""Odbudowa kanonicznych CHD z prawidłowym cue (biblioteka Redump Cuesheets).

Problem: CHD utworzone ze złym/bez cue ma SKLEJONY układ ścieżek (metadane
mówią „1 ścieżka", a gra ma ich N — dane + audio CDDA). Zawartość bywa
poprawna (tniemy wg rozmiarów z DAT-a i sumy się zgadzają), ale kontener
jest niekanoniczny.

Odbudowa per gra:
1. wykrycie: liczba ścieżek CD w metadanych CHD != liczba ścieżek w DAT;
2. ekstrakcja ``extractcd -sb``; jeden sklejony bin => cięcie wg ROZMIARÓW
   z DAT-a; KAŻDA ścieżka weryfikowana SHA-1 z DAT-em (złe dane => stop);
3. ścieżki pod nazwami z DAT-a + cue z biblioteki (sha1 cue też z DAT-a);
4. ``chdman createcd -i <cue>`` + round-trip verify (fixer);
5. dopiero po sukcesie podmiana starego pliku i aktualizacja indeksu.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from .cuelib import CueLibrary
from .models import CD_METADATA_TAGS, MediaType

LogCB = Callable[[str], None]


@dataclass
class RebuildChdStats:
    checked: int = 0
    ok_layout: int = 0        # układ ścieżek już zgodny z DAT-em
    rebuilt: int = 0
    no_cue: int = 0           # brak cue w bibliotece
    verify_failed: int = 0    # ścieżki nie przeszły sum z DAT-em
    skipped_space: int = 0
    errors: int = 0

    def summary(self) -> str:
        return (f"sprawdzono {self.checked}, układ OK {self.ok_layout}, "
                f"ODBUDOWANO {self.rebuilt}, brak cue {self.no_cue}, "
                f"weryfikacja nieudana {self.verify_failed}, "
                f"pominięte (miejsce) {self.skipped_space}, "
                f"błędy {self.errors}")


def _scratch_tmp(chd_path: Path, need: int, log: LogCB, fallback=None):
    """Katalog roboczy odbudowy: RAM-dysk (gdy się mieści) → `fallback`
    (dedykowany scratch_dir z ustawień, gdy podany i lokalny). NIGDY „obok pliku"
    — bo pliki leżą na NAS-ie (Z:\\), a wielogigowy scratch DVD przez SMB
    zwiesza potok i sypie `createdvd kod 1`. Gdy nic lokalnego się nie mieści →
    None => zadanie POMINIĘTE (skipped_space) i wznowione następnym przebiegiem
    (odbudowa jest idempotentna). Finalny plik i tak przenosimy na miejsce."""
    from .scratch import _SCRATCH_NAME, _free
    from . import ramdisk
    need = max(int(need), 0)
    roots: list = []
    ram = ramdisk.active_root()
    if ram is not None:
        roots.append((str(ram), "RAM dysk"))
    if fallback:
        roots.append((str(fallback), "scratch_dir"))
    if ram is None:
        # brak RAM-dysku (tryb seryjny) → ostatnia deska: LOKALNY temp systemowy
        # (na C:/dysku systemowym, nie na NAS). Przy 1 zadaniu naraz to bezpieczne.
        roots.append((tempfile.gettempdir(), "temp systemowy"))
    for root, label in roots:
        try:
            if _free(root) < need:
                continue
            p = Path(root) / _SCRATCH_NAME
            p.mkdir(parents=True, exist_ok=True)
            log(f"scratch: {label} {root} ({_free(root)/1024**3:.1f} GB wolne, "
                f"potrzeba {need/1024**3:.1f} GB).")
            return Path(tempfile.mkdtemp(prefix="chdbuddy_rebuild_", dir=str(p)))
        except OSError:
            continue
    log(f"scratch: brak miejsca lokalnie (~{need/1024**3:.1f} GB) na RAM-dysku "
        f"ani w scratch_dir — POMIJAM (wznowię przy następnej odbudowie). "
        f"NIE spadam na NAS (SMB scratch = zwis).")
    return None


def _mk_detail(detail, name: str):
    """Adapter: chdman woła on_progress(pct, msg); pasek UI bierze
    (done, total, text). Zwraca callback dla chdman albo None."""
    if detail is None:
        return None

    def dp(pct: float, msg: str = "") -> None:
        if pct is not None and pct >= 0:
            detail(int(pct), 100, f"CHD {name}: {msg or f'{int(pct)}%'}")
        else:
            detail(0, 0, f"CHD {name}: {msg}".rstrip(": "))
    return dp


def _mk_slot_dp(slot, idx: int, name: str, what: str):
    """Adapter paska RÓWNOLEGŁEGO (slot): konwencja chdman on_progress(pct, msg)
    → set_slot(idx, done, total, text). Dawniej _rb_build podawał chdmanowi
    callback o sygnaturze (done, total, text) — do paska trafiał TEKST jako
    `total`, obsługa w UI się wywracała i własne paski nigdy się nie pokazały
    (wszystko widać było tylko na wspólnym pasku pobierania/wysyłki)."""
    def dp(pct: float, msg: str = "") -> None:
        if pct is not None and pct >= 0:
            slot(idx, int(pct), 100,
                 f"{what} {name}: {msg or f'{int(pct)}%'}")
        else:
            slot(idx, 0, 0, f"{what} {name}: {msg}".rstrip(": "))
    return dp


def _place_final(new: Path, dst: Path, detail=None) -> None:
    """Przenosi gotowy plik na miejsce; os.replace na tym samym dysku
    (atomowo), kopia blokami z postępem między dyskami (RAM → fizyczny).

    STARY plik NIE jest kasowany przed wysyłką: nowy trafia obok jako
    `*.chdbuddy_move_tmp` i dopiero KOMPLETNY zastępuje stary (os.replace).
    Dawniej `dst.unlink()` przed wysyłką zostawiał przez całą (przez internet
    — godzinną) wysyłkę JEDYNĄ kopię gry na ulotnym RAM-dysku."""
    from . import netguard
    from .fileops import move_with_progress
    # zerwany NAS (uśpienie laptopa, restart routera) → czekaj i powtórz
    netguard.call(lambda: move_with_progress(new, dst, on_progress=detail,
                                             label=f"przenoszę {dst.name}"),
                  new, dst, what=f"wysyłka {dst.name}")


def _chd_cd_tracks(chd, path: Path) -> int:
    """Liczba ścieżek CD w metadanych CHD (0 gdy info nieczytelne)."""
    try:
        info = chd.info(path)
    except OSError:
        return 0
    return sum(1 for t in info.metadata_tags if t in CD_METADATA_TAGS)


def _write_split_by_dat(src_bin: Path, tracks, out_dir: Path,
                        log: LogCB) -> Optional[list]:
    """Tnie sklejony bin wg rozmiarów z DAT-a, weryfikując sha1 KAŻDEJ
    ścieżki w locie. Zwraca listę plików albo None (niezgodność)."""
    out = []
    with open(src_bin, "rb") as fh:
        for rom in tracks:
            h = hashlib.sha1()
            dst = out_dir / rom.name
            left = rom.size
            with open(dst, "wb") as o:
                while left > 0:
                    chunk = fh.read(min(1 << 22, left))
                    if not chunk:
                        break
                    h.update(chunk)
                    o.write(chunk)
                    left -= len(chunk)
            if left != 0 or h.hexdigest() != rom.sha1.lower():
                log(f"   ścieżka {rom.name}: suma NIE zgadza się z DAT-em")
                return None
            out.append(dst)
    return out


# --- fazy POTOKU (równoległa odbudowa, gdy jest RAM-dysk) --------------------
# Kontrakt jak w convert.StagePipeline: gather(I/O)→build(CPU)→upload(I/O),
# finalize/release w wątku WŁAŚCICIELA (SQLite jednowątkowe). Payload = dict.
# chdman NIE dostaje cancel — rozpoczęta konwersja się DOKAŃCZA; przerwanie
# tylko wstrzymuje FEED nowych zadań (właściciel), a drain() domyka rozpoczęte.

def _rb_gather(payload):
    """I/O: scratch + ekstrakcja CHD + deframe/split + weryfikacja SHA-1."""
    chd = payload["chd"]
    log = payload["log"]
    # równoległe pobierania → KAŻDE na własnym pasku (slot nadaje potok)
    gidx = payload.get("_gather_slot")
    slot = payload.get("slot")
    if slot is not None and gidx is not None:
        dp = _mk_slot_dp(slot, gidx, payload["chd_path"].name, "pobieranie")
    else:
        dp = _mk_detail(payload["detail"], payload["chd_path"].name)
    try:
        return _rb_gather_run(payload, chd, log, dp)
    finally:
        if slot is not None and gidx is not None:
            slot(gidx, -1, 0, "")               # zwolnij pasek pobierania


def _rb_gather_run(payload, chd, log, dp):
    """ETAP POBIERANIA = TYLKO kopia CHD z NAS na RAM. Rozpakowanie (chdman
    extractcd — jednowątkowe, ~1–1,5 min na grę PS2) robi etap PRZERÓBKI: przez
    internet (Tailscale, ~7 MB/s) łącze jest wąskim gardłem, więc następne
    pobranie ma ruszać zaraz po skopiowaniu, a nie po rozpakowaniu."""
    tmp = _scratch_tmp(payload["chd_path"], payload["need"], log,
                       fallback=payload["fallback"])
    if tmp is None:
        payload["outcome"] = "skipped_space"
        return None
    payload["scratch"] = tmp
    local = _local_source(payload["chd_path"], tmp, dp, log)
    payload["local"] = local
    return local


def _rb_prepare(payload, chd, log, dp):
    """Rozpakowanie pobranej kopii + deframe/podział + weryfikacja SHA-1 (etap
    przeróbki). Zwraca źródło do createdvd/createcd albo None (outcome ustawiony)."""
    tmp = payload["scratch"]
    local = payload.get("local")
    if payload["kind"] == "dvd":
        src, oc = _prep_dvd(payload["chd_path"], payload["game_name"],
                            payload["iso_rom"], tmp, chd, log, dp, local=local)
        payload["split"] = src.parent if src else None
    else:
        src, split, oc = _prep_cd(payload["chd_path"], payload["game_name"],
                                  payload["data"], payload["cue_rom"],
                                  payload["cue_bytes"], tmp, chd, log, dp,
                                  local=local)
        payload["split"] = split
    if oc:
        payload["outcome"] = oc
        return None
    payload["src"] = src
    return src


def _rb_build(payload, gathered):
    """CPU: createcd/createdvd + round-trip verify (bez cancel — dokończ)."""
    from . import fixer
    if gathered is None:
        return None
    log = payload["log"]
    sidx = payload.get("_pipe_slot")
    slot = payload.get("slot")
    if slot is not None and sidx is not None:
        dp = _mk_slot_dp(slot, sidx, payload["chd_path"].name, "CHD")
    else:
        dp = _mk_detail(payload["detail"], payload["chd_path"].name)
    media = MediaType.DVD if payload["kind"] == "dvd" else MediaType.CD
    # ROZPAKOWANIE pobranej kopii (gdy etap pobierania tylko kopiował)
    if "local" in payload and "src" not in payload:
        if slot is not None and sidx is not None:
            dpx = _mk_slot_dp(slot, sidx, payload["chd_path"].name,
                              "rozpakowanie")
        else:
            dpx = dp
        try:
            gathered = _rb_prepare(payload, payload["chd"], log, dpx)
        except Exception:
            if slot is not None and sidx is not None:
                slot(sidx, -1, 0, "")
            raise
        if gathered is None:
            if slot is not None and sidx is not None:
                slot(sidx, -1, 0, "")
            return None
    # WĄTKI chdman liczone TUŻ PRZED kompresją: pula / ile przeróbek trwa (z tą).
    # Sama gra → cała pula (8); dwie → po 4 itd. (extractcd/verify w chdman są
    # zawsze jednowątkowe — tego nie przyspieszymy, kompresję tak).
    settings = payload["settings"]
    pool = payload.get("threads_pool") or 0
    _afn = payload.get("_pipe_active_fn")
    act = (_afn() if callable(_afn) else 0) or payload.get("_pipe_active") or 0
    if pool and act:
        import dataclasses as _dc
        nth = max(1, pool // act)
        try:
            settings = _dc.replace(settings, threads=nth)
        except Exception:
            pass
        log(f"   kompresja: {nth} wątków chdman (trwa {act} kompresji naraz)")
    try:
        out = fixer.create_from_source(
            payload["chd"], gathered, media, payload["split"],
            settings, compression=payload["comp"],
            log=lambda m: log(f"   {m}"), cancel_event=None, on_progress=dp)
    finally:
        if slot is not None and sidx is not None:
            slot(sidx, -1, 0, "")               # zwolnij pasek slotu
    if not out.ok:
        payload["outcome"] = "errors"
        log(f"   create/verify: {out.message}")
        return None
    new_chd = payload["split"] / (Path(gathered).stem + ".chd")
    if not new_chd.is_file():
        payload["outcome"] = "errors"
        return None
    payload["new_chd"] = new_chd
    return new_chd


def _rb_upload(payload, built):
    """I/O: sumy z pliku w SCRATCHU (RAM) + atomowa podmiana starego CHD nowym.

    KLUCZOWE: sumy liczymy z `built` (RAM) PRZED podmianą — treść jest identyczna
    i już zweryfikowana round-tripem. Liczenie z pliku docelowego na NAS PO
    przeniesieniu oznaczało PONOWNY odczyt całego CHD przez SMB — pasek stał na
    100% (move gotowy), a proces po cichu czytał minuty z sieci."""
    if built is None:
        return None
    from .fileindex import hash_file
    try:
        sums = hash_file(built)               # RAM — szybkie, bez odczytu z NAS
    except OSError:
        sums = ("", "", "")
    _place_final(built, payload["chd_path"], payload["detail"])
    return sums


def _rb_finalize(payload, sums, index, log):
    """WŁAŚCICIEL: zapis do indeksu (SQLite jednowątkowe) po sukcesie."""
    if sums is None:
        return
    payload["outcome"] = "rebuilt"
    if index is None:
        return
    crc, md5, sha1 = sums
    if crc or sha1:
        index.record_file(payload["chd_path"], crc, md5, sha1)
    if payload["kind"] == "dvd":
        index.set_data_sha1(payload["chd_path"], payload["iso_rom"].sha1.lower())
    else:
        from .datfile import game_profile
        index.set_data_sha1(payload["chd_path"], game_profile(payload["data"]))
        index.set_layout_ok(payload["chd_path"], 1)
    index.set_bad_container(payload["chd_path"], 0)
    from .linker import relink_twins
    relink_twins(payload["chd_path"], payload.get("twins"), index, log)


def _rb_release(payload, st, log):
    """WŁAŚCICIEL: sprzątnij scratch i policz statystyki wg wyniku zadania."""
    tmp = payload.get("scratch")
    if tmp is not None:
        shutil.rmtree(tmp, ignore_errors=True)
    oc = payload.get("outcome")
    if oc == "rebuilt":
        st.rebuilt += 1
        log(f"   ✔ kontener podmieniony: {payload['chd_path'].name}")
    elif oc == "verify_failed":
        st.verify_failed += 1
    elif oc == "skipped_space":
        st.skipped_space += 1
        log(f"   POMIJAM (brak miejsca ~{payload['need']/1024**3:.1f} GB): "
            f"{payload['chd_path'].name}")
    elif oc == "errors":
        st.errors += 1


def rebuild_bad_chds(
    entries: Sequence,
    lib: CueLibrary,
    chd,                                   # CHDMan
    settings,
    index=None,
    *,
    extra_roots: Sequence = (),
    dry_run: bool = False,
    log: LogCB = lambda m: None,
    on_progress=None,
    detail=None,
    cancel=None,
    slot=None,
    seen: Optional[set] = None,
) -> RebuildChdStats:
    """Odbudowuje CHD o złym układzie ścieżek:

    1. kanoniczne pliki ``<gra>.chd`` w katalogach docelowych `entries`;
    2. ZIDENTYFIKOWANE CHD leżące jeszcze w `extra_roots` (np. ToSort) —
       rozpoznane po odcisku kompletu (data_sha1); odbudowa W MIEJSCU,
       przenosiny/nazwę załatwia potem naprawa.

    Gdy jest RAM-dysk (i nie dry_run) — odbudowa RÓWNOLEGŁA przez StagePipeline
    (kilka `chdman` naraz, limit = budżet RAM). Przerwanie jest ŁAGODNE:
    rozpoczęte konwersje kończą się i są zatwierdzane (podmiana + indeks +
    zdjęcie flagi bad_container), NIEROZPOCZĘTE zostają z bad_container=1 i
    następny przebieg je wznowi. Oryginał nie jest kasowany bez zweryfikowanego
    zamiennika (podmiana atomowa dopiero po round-trip).
    """
    from . import presets
    st = RebuildChdStats()
    comp = presets.compression_for(settings.compression_preset, MediaType.CD)
    comp_dvd = presets.compression_for(settings.compression_preset,
                                       MediaType.DVD)

    # POSTĘP: realny licznik „zrobione / wszystkie" (nie indeks DAT-u). `total`
    # ustawiamy po pre-liczeniu; `done` rośnie przy KAŻDYM zakończonym zadaniu
    # (sukces/porażka/pominięcie) — w potoku z release, seryjnie po _dispatch.
    _prog = {"done": 0, "total": 0}

    def _tick(name: str = "") -> None:
        _prog["done"] += 1
        if on_progress and _prog["total"]:
            on_progress(_prog["done"], _prog["total"],
                        f"Odbudowa CHD: {name}" if name else "Odbudowa CHD")

    def _release_and_tick(payload) -> None:
        _rb_release(payload, st, log)
        _tick(payload["chd_path"].name)

    # POTOK gdy jest RAM-dysk (tam trafia scratch) i realnie coś robimy.
    _pipe = None
    _budget = 0
    _bw = 1
    # PULA wątków do ROZDZIELENIA między równoległe konwersje (nie „1 na zadanie"):
    # ile realnie biegnie naraz ogranicza budżet RAM (duży DVD → 1 → cała pula
    # dla niego; małe CD → kilka → pula podzielona). Domyślnie 8 (P-rdzenie).
    _logical = os.cpu_count() or 8
    _total_threads = max(1, min(8, _logical))    # pula (user: „8 do dyspozycji")
    if not dry_run:
        try:
            from . import ramdisk as _rd
            _ram = _rd.active_root()
        except Exception:
            _ram = None
        if _ram is not None:
            try:
                import shutil as _sh
                from .convert_pipeline import StagePipeline
                # 0.6 (nie 0.85): scratch na RAM-dysku to TEN SAM fizyczny RAM,
                # o który walczą OS + cache odczytu z NAS + chdman. Zapełnianie
                # R: pod korek wypychało 17-30 GB na pagefile C: (thrash) i przy
                # dryfie księgowania budżet≠realne wolne R: → spadanie scratchu
                # na NAS (zwis). Zapas 40% trzyma RAM pod kontrolą.
                _budget = int(_sh.disk_usage(str(_ram)).free * 0.6)
                _cw = getattr(settings, "convert_workers", 0) or 0
                _bw = (max(1, min(int(_cw), _logical)) if _cw and int(_cw) > 0
                       else max(1, min(8, _logical // 2)))
                _pipe = StagePipeline(
                    gather=_rb_gather,
                    build=_rb_build,
                    upload=_rb_upload,
                    finalize=lambda p, r: _rb_finalize(p, r, index, log),
                    release=_release_and_tick,
                    ram_budget=_budget, log=log, cancel=None,
                    build_workers=_bw, ordered=False,
                    gather_workers=max(1, int(getattr(
                        settings, "download_workers", 1) or 1)))
                _pipe.start()
                log(f"Odbudowa CHD: potok WŁ (do {_bw} równoległych, "
                    f"{_pipe._gather_workers} pobierań naraz, "
                    f"{_total_threads} wątków dzielonych między równoległe, "
                    f"budżet RAM {_budget/1024**3:.1f} GB); przerwanie dokańcza "
                    f"rozpoczęte.")
            except Exception as _e:
                log(f"Odbudowa CHD: potok niedostępny ({_e}) — seryjnie.")
                _pipe = None
    # mapa odcisk gry -> ("cd", gra multi-track z cue) albo ("dvd", gra .iso)
    # — do rozpoznania plików w ToSort i naprawy kontenera
    from .datfile import game_profile
    by_prof: dict = {}
    for entry in entries:
        entry.load()
        for game in entry.games:
            data = game.data_roms
            cue_rom = next((r for r in game.roms
                            if r.name.lower().endswith(".cue")), None)
            if (len(data) == 1 and game.media == MediaType.DVD
                    and data[0].sha1):
                by_prof.setdefault(game_profile(data),
                                   ("dvd", game, data, None))
            elif len(data) >= 2 and cue_rom is not None and cue_rom.sha1:
                by_prof.setdefault(game_profile(data),
                                   ("cd", game, data, cue_rom))

    def _cancelled() -> bool:
        return cancel is not None and cancel.is_set()

    def _dispatch(chd_path: Path, game_name: str, kind: str, data, cue_rom) -> bool:
        """Jedna gra: seryjnie (bez potoku) albo — z potokiem — tanie pre-checki
        w wątku właściciela + `feed` ciężkiej pracy (ekstrakcja/create/verify).
        Zwraca True, gdy zadanie ODDANO DO POTOKU (licznik `done` podbije release);
        False, gdy obsłużone seryjnie albo pominięte na pre-checku (licznik
        podbija wtedy pętla od razu)."""
        from . import netguard
        netguard.checkpoint(cancel)          # NAS padł → czekaj na powrót
        if _pipe is None:
            if kind == "dvd":
                _rebuild_dvd_one(chd_path, game_name, data[0], chd, settings,
                                 comp_dvd, index, st, dry_run, log, cancel,
                                 detail)
            else:
                _rebuild_one(chd_path, game_name, data, cue_rom, lib, chd,
                             settings, comp, index, st, dry_run, log, cancel,
                             detail)
            return False
        # POTOK: pre-checki (info/tracks/cue) TANIO i seryjnie (właściciel),
        # ciężka praca do potoku.
        st.checked += 1
        cue_bytes = None
        iso_rom = None
        if kind == "dvd":
            try:
                info = chd.info(chd_path)
            except OSError:
                st.errors += 1
                return False
            if not info.is_cd_typed:
                st.ok_layout += 1
                if index is not None:
                    try:
                        index.set_bad_container(chd_path, 0)
                    except Exception:
                        pass
                return False
            iso_rom = data[0]
        else:
            n_chd = _chd_cd_tracks(chd, chd_path)
            if n_chd == len(data):
                st.ok_layout += 1
                if index is not None:
                    try:
                        index.set_bad_container(chd_path, 0)
                        index.set_layout_ok(chd_path, 1)
                    except Exception:
                        pass
                return False
            cue_bytes = lib.load(cue_rom.sha1)
            if cue_bytes is None:
                st.no_cue += 1
                log(f"BRAK CUE w bibliotece: {game_name}")
                return False
        # SKĄD → DOKĄD: pełne ścieżki (odbudowa podmienia plik W MIEJSCU)
        log(f"ODBUDOWA {'CD→DVD' if kind == 'dvd' else 'kontenera'} (potok): "
            f"{chd_path}  →  {chd_path} (w miejscu)  [{game_name}]")
        need = int(chd_path.stat().st_size * 3.2)
        # WĄTKI chdman dla TEGO zadania = pula / ile takich zmieści się na raz
        # w budżecie RAM. Duży DVD (need≈budżet) → 1 równolegle → cała pula (8);
        # małe CD → kilka równolegle → pula podzielona (np. 4 CD → po 2).
        _conc = max(1, min(_bw, _budget // max(need, 1))) if _budget else 1
        _jthreads = max(1, _total_threads // _conc)
        try:
            import dataclasses as _dc
            _sjob = _dc.replace(settings, threads=_jthreads)
        except Exception:
            _sjob = settings
        from .linker import hardlink_twins
        _pipe.feed({
            "twins": hardlink_twins(chd_path, index),   # przed podmianą
            "kind": kind, "chd_path": chd_path, "game_name": game_name,
            "need": need, "comp": comp_dvd if kind == "dvd" else comp,
            "iso_rom": iso_rom, "data": data, "cue_rom": cue_rom,
            "cue_bytes": cue_bytes, "chd": chd, "settings": _sjob,
            "threads_pool": _total_threads,
            "log": log, "detail": detail, "slot": slot,
            "fallback": getattr(settings, "scratch_dir", "") or None,
            "outcome": None,
        }, cost=need)
        return True

    # PRE-LICZENIE: zbierz pliki DO PRZEROBIENIA (z SZYBKIM WZNAWIANIEM) i pogrupuj
    # per katalog docelowy (= platforma + dysk), by pasek pokazał realne
    # „zrobione / wszystkie", a log — z jakich kolekcji i skąd lecą pliki.
    def _bad_container(chd_path: Path) -> int:
        """Wartość bad_container z indeksu (-1 gdy brak/niesprawdzony)."""
        if index is None:
            return -1
        try:
            row = index.lookup(chd_path)
            if row is None:
                return -1
            return row["bad_container"] if "bad_container" in row.keys() else -1
        except Exception:
            return -1

    def _layout_ok(chd_path: Path) -> bool:
        """CHD gry CD z układem ścieżek już POTWIERDZONYM jako zgodny z DAT
        (layout_ok=1 w indeksie; zeruje się, gdy plik się zmieni)."""
        if index is None:
            return False
        try:
            row = index.lookup(chd_path)
            return bool(row is not None and "layout_ok" in row.keys()
                        and row["layout_ok"] == 1)
        except Exception:
            return False

    def _already_ok(chd_path: Path, kind: str) -> bool:
        # DVD: kontener DVD potwierdzony (bad_container=0); CD: układ ścieżek
        # potwierdzony (layout_ok=1). Oba BEZ czytania nagłówka z NAS.
        if kind == "dvd":
            return _bad_container(chd_path) == 0
        return _layout_ok(chd_path)

    def _header_verdict(chd_path: Path, hit) -> Optional[bool]:
        """Werdykt z NAGŁÓWKA zapisanego w indeksie przy skanie (bez NAS):
        True = kontener/układ zgodny z DAT, False = na pewno do odbudowy,
        None = nagłówek nieznany (stary wpis — sprawdzi naprawa albo skan)."""
        if index is None:
            return None
        # zły kontener stwierdzony sondą CHD (bad_container=1) to WERDYKT —
        # dawniej liczył się tylko zapisany typ nagłówka i 503 złe CHD PS2 bez
        # niego wypadały z podglądu jako „nieznane" (0 do odbudowy)
        if _bad_container(chd_path) == 1:
            return False
        try:
            trk, cdt = index.chd_header(chd_path)
        except Exception:
            return None
        kind, _g, data, _cue = hit
        if kind == "dvd":
            return None if cdt < 0 else cdt == 0
        return None if trk < 0 else trk == len(data)

    def _mark_ok(chd_path: Path, kind: str) -> None:
        if index is None:
            return
        try:
            index.set_bad_container(chd_path, 0)
            if kind != "dvd":
                index.set_layout_ok(chd_path, 1)
        except Exception:
            pass

    targets: list = []          # (chd_path, game_name, hit)
    skipped_done = 0            # już potwierdzone jako poprawne (bez NAS)
    unknown = 0                 # podgląd: nagłówek nieznany w indeksie
    for entry in entries:
        # ISTNIENIE <gra>.chd z INDEKSU (jedno zapytanie na katalog), NIE
        # `is_file` per gra: PSX = ~4600 gier z DAT-u → ~3 min szeregowych
        # zapytań SMB w CISZY przed pierwszą linią logu („program zawieszony").
        # Odbudowę i tak poprzedza odczyt nagłówka pliku (błąd = pominięcie).
        present = None
        if index is not None:
            try:
                present = {os.path.normcase(r["path"])
                           for r in index.all_under(entry.target_dir)
                           if r["path"].lower().endswith(".chd")}
            except Exception:
                present = None
        _ng = len(entry.games)
        for _gi, game in enumerate(entry.games, 1):
            if _cancelled():
                break
            # WIDOCZNOŚĆ: które gry i ile zostało (co 25, by nie zalać GUI)
            if on_progress and (_gi % 25 == 0 or _gi == _ng):
                on_progress(_gi, _ng, f"Odbudowa CHD — przeliczam: {game.name}")
            data = game.data_roms
            hit = by_prof.get(game_profile(data)) if data else None
            if hit is None:
                continue
            chd_path = Path(entry.target_dir) / f"{game.name}.chd"
            if present is not None:
                if os.path.normcase(os.path.abspath(str(chd_path))) not in present:
                    continue
            elif not chd_path.is_file():
                continue
            # SZYBKIE WZNAWIANIE: plik już potwierdzony jako poprawny (DVD:
            # kontener DVD; CD: układ ścieżek zgodny z DAT) — POMIŃ bez czytania
            # nagłówka z NAS. Nie-potwierdzone trafiają do SPRAWDZENIA.
            if _already_ok(chd_path, hit[0]):
                skipped_done += 1
                st.ok_layout += 1
                continue
            verdict = _header_verdict(chd_path, hit)
            if verdict is True:                  # zgodny wg nagłówka z indeksu
                _mark_ok(chd_path, hit[0])
                skipped_done += 1
                st.ok_layout += 1
                continue
            if verdict is None and dry_run:      # podgląd NIE czyta nagłówków
                unknown += 1
                continue
            targets.append((chd_path, game.name, hit))
    # ToSort: zidentyfikowane CHD leżące jeszcze poza targetem (kontener w miejscu)
    for root in (extra_roots or []):
        if index is None or _cancelled():
            break
        for row in index.identified_chds_under(root):
            p = row["path"]
            hit = by_prof.get(row["data_sha1"])
            if hit is None:
                continue
            chd_path = Path(p)
            # istnienie z INDEKSU (identified_chds_under = missing=0); NAS
            # pytamy tylko w realnej naprawie — podgląd nie dotyka dysku
            if not dry_run and not chd_path.is_file():
                continue
            if _already_ok(chd_path, hit[0]):
                skipped_done += 1
                st.ok_layout += 1
                continue
            verdict = _header_verdict(chd_path, hit)
            if verdict is True:
                _mark_ok(chd_path, hit[0])
                skipped_done += 1
                st.ok_layout += 1
                continue
            if verdict is None and dry_run:
                unknown += 1
                continue
            targets.append((chd_path, hit[1].name, hit))

    # JEDEN plik = JEDNA odbudowa na cały przebieg naprawy: CHD z ToSort
    # (extra_roots) widzi każdy DAT tej platformy (ROMS/REDUMP/1G1R) — bez
    # wspólnego `seen` szedł do podglądu (i do sprawdzenia) po razie na DAT.
    if seen is not None:
        _fresh = []
        for t in targets:
            k = os.path.normcase(os.path.abspath(str(t[0])))
            if k not in seen:
                seen.add(k)
                _fresh.append(t)
        targets = _fresh

    # HARDLINKI jednego pliku = JEDNA odbudowa: przebudowujemy plik fizyczny,
    # jego pozostałe nazwy przepina `relink_twins` po podmianie. Inaczej każda
    # nazwa szłaby osobno (ponowne pobranie przez NAS i druga kopia fizyczna).
    if index is not None and targets:
        tset = {os.path.normcase(str(t[0])) for t in targets}
        kept = []
        for t in targets:
            try:
                r = index.lookup(t[0])
                lo = (r["link_of"] or "") if r is not None else ""
            except Exception:
                lo = ""
            if lo and os.path.normcase(lo) in tset:
                continue
            kept.append(t)
        if len(kept) != len(targets):
            log(f"Odbudowa CHD: {len(targets) - len(kept)} hardlinków innych "
                f"celów — przepięte po odbudowie ich pliku, bez osobnej pracy.")
        targets = kept

    from collections import Counter as _Ctr
    _bydir = _Ctr(str(t[0].parent) for t in targets)
    _prog["total"] = len(targets)
    # DAT bez żadnego CHD (kartridże itp.) — bez linii „0 plików" w logu
    _quiet = not targets and not skipped_done and not unknown
    _msg = (f"Odbudowa CHD: {len(targets)} plików do SPRAWDZENIA "
        f"(czytam nagłówek; przerobione zostaną tylko te ze złym kontenerem/"
        f"układem — linie „ODBUDOWA”)"
        + (f"; {skipped_done} już potwierdzonych jako OK — pominięte"
           if skipped_done else "")
        + (f"; {unknown} bez zapisanego nagłówka — sprawdzi je naprawa "
           f"(albo najbliższy skan)" if unknown else "")
        + (f" w {len(_bydir)} katalogach:" if _bydir else "."))
    if not _quiet:
        log(_msg)
    for d, n in sorted(_bydir.items(), key=lambda kv: -kv[1]):
        log(f"  {n:5}  {d}")
    if on_progress:
        on_progress(0, _prog["total"] or 1, "Odbudowa CHD: start")

    for chd_path, game_name, hit in targets:
        if _cancelled():
            break
        if on_progress:
            on_progress(_prog["done"], _prog["total"] or 1,
                        f"CHD wg cue: {game_name}")
        kind, _g, data, cue_rom = hit
        if dry_run:
            # PODGLĄD z indeksu (nagłówek zapisany przy skanie) — bez NAS
            st.checked += 1
            st.rebuilt += 1
            trk, _cdt = (index.chd_header(chd_path) if index is not None
                         else (-1, -1))
            what = ("CD→DVD" if kind == "dvd"
                    else f"(ścieżki w CHD: {trk}, w DAT: {len(data)})")
            log(f"ODBUDOWA {what}: {chd_path}  →  {chd_path} (w miejscu)  "
                f"[{game_name}] (podgląd)")
            _tick(game_name)
            continue
        fed = _dispatch(chd_path, game_name, kind, data, cue_rom)
        if not fed:                  # seryjnie/pominięte → licznik od razu
            _tick(game_name)         # (oddane do potoku podbije release)

    if _pipe is not None:
        # dokończ i zatwierdź WSZYSTKIE rozpoczęte (drain finalizuje po kolei);
        # po przerwaniu nowe nie były już podawane, więc kończą się tylko te,
        # które ruszyły.
        _pipe.drain()
        _pipe.close()
    return st


def _local_source(chd_path: Path, tmp: Path, dp, log: LogCB) -> Path:
    """Kopia CAŁEGO CHD do scratchu (RAM) jednym strumieniem, dużymi blokami —
    ZANIM chdman go rozpakuje. chdman czyta CHD kawałkami (hunk po hunku), a przez
    internet (Tailscale, 33 ms na odczyt) to 39 MB/s wyjścia zamiast 101 MB/s
    lokalnie (pomiar na PS2). Kopia na NAS-owym dysku lokalnym i tak nic nie
    kosztuje. Gdy kopia się nie uda (poza zerwaniem NAS, które netguard przeczeka)
    — czytamy wprost z NAS jak dawniej. Budżet `need` (×3,2) mieści kopię: znika
    zaraz po ekstrakcji, przed powstaniem obrazu i nowego CHD."""
    from . import netguard
    from .fileops import copy_parallel
    local = tmp / ("src_" + chd_path.name)

    def _cb(done, total, label):
        if dp is not None:
            dp((done * 100.0 / total) if total else -1, label)
    try:
        netguard.call(lambda: copy_parallel(
            chd_path, local, _cb, f"pobieram {chd_path.name}"),
            chd_path, what=f"pobieranie {chd_path.name}")
        return local
    except OSError as e:
        log(f"   kopia lokalna nieudana ({e}) — czytam wprost z NAS")
        local.unlink(missing_ok=True)
        return chd_path


def _drop_local(src: Path, chd_path: Path) -> None:
    """Usuń lokalną kopię CHD (zwolnij RAM przed kolejnymi etapami)."""
    if src != chd_path:
        src.unlink(missing_ok=True)


def _sha1_file(path: Path) -> str:
    """SHA-1 pliku strumieniowo (nie `read_bytes()` — cały tor w pamięci)."""
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _prep_dvd(chd_path: Path, game_name: str, iso_rom, tmp: Path, chd, log: LogCB,
              dp, local: Optional[Path] = None) -> tuple:
    """Ekstrakcja CHD (CD-typed) → deframe 2352→2048 → weryfikacja SHA-1 obrazu
    z DAT-em. Zwraca (iso_path w tmp/split | None, outcome): outcome '' = OK,
    'errors' / 'verify_failed'. NIE podaje cancel do chdman — rozpoczęta operacja
    ma się DOKOŃCZYĆ (przerwanie zatrzymuje dopiero start następnej gry)."""
    from . import imageops
    raw = tmp / (game_name + ".cue")
    # `local` — kopia pobrana już w etapie POBIERANIA potoku; bez niej (tryb
    # seryjny) pobieramy tutaj
    src = local if local is not None else _local_source(chd_path, tmp, dp, log)
    try:
        res = chd.extract("extractcd", src, raw, cancel_event=None,
                          on_progress=dp)
    finally:
        _drop_local(src, chd_path)
    if not res.ok:
        log("   ekstrakcja nieudana")
        return None, "errors"
    try:
        cue = imageops.parse_cue(raw)
    except Exception as e:
        log(f"   cue nieczytelne: {e}")
        return None, "errors"
    if cue.bin_path is None or not cue.bin_path.is_file():
        log("   brak .bin po ekstrakcji")
        return None, "errors"
    split = tmp / "split"
    split.mkdir(exist_ok=True)
    iso = split / iso_rom.name
    # SHA-1 obrazu W LOCIE przy deframingu (bez drugiego odczytu i bez całego
    # obrazu w pamięci programu), surowy .bin kasowany od razu — zwalnia RAM
    # przed createdvd
    h = hashlib.sha1()
    imageops.bin_to_iso(cue.bin_path, cue.sector_size, iso, hasher=h)
    cue.bin_path.unlink(missing_ok=True)
    got = h.hexdigest()
    if got != iso_rom.sha1.lower():
        log("   SHA-1 obrazu po deframe nie zgadza się z DAT-em — pomijam")
        return None, "verify_failed"
    return iso, ""


def _prep_cd(chd_path: Path, game_name: str, data, cue_rom, cue_bytes: bytes,
             tmp: Path, chd, log: LogCB, dp, local: Optional[Path] = None) -> tuple:
    """Ekstrakcja CHD (extractcd -sb) → podział wg DAT-a + weryfikacja SHA-1 +
    cue z biblioteki. Zwraca (cue_path | None, split_dir | None, outcome).
    NIE podaje cancel do chdman (patrz `_prep_dvd`)."""
    raw = tmp / (game_name + ".cue")
    src = local if local is not None else _local_source(chd_path, tmp, dp, log)
    try:
        res = chd.extract("extractcd", src, raw, cancel_event=None,
                          extra_args=["-sb"], on_progress=dp)
        if not res.ok:
            res = chd.extract("extractcd", src, raw, cancel_event=None,
                              on_progress=dp)
    finally:
        _drop_local(src, chd_path)
    if not res.ok:
        log("   ekstrakcja nieudana")
        return None, None, "errors"
    bins = sorted(p for p in tmp.iterdir() if p.suffix.lower() == ".bin")
    split = tmp / "split"
    split.mkdir(exist_ok=True)
    if len(bins) == 1:
        tracks = _write_split_by_dat(bins[0], data, split, log)
        bins[0].unlink(missing_ok=True)       # sklejony bin zbędny — zwolnij RAM
    elif len(bins) == len(data):
        tracks = []
        for b, rom in zip(bins, data):
            h = _sha1_file(b)
            if h != rom.sha1.lower():
                tracks = None
                log(f"   {b.name}: suma nie zgadza się z DAT-em")
                break
            t = split / rom.name
            os.replace(b, t)
            tracks.append(t)
    else:
        tracks = None
        log(f"   dziwny podział ({len(bins)} bin vs {len(data)} w DAT) — pomijam")
    if not tracks:
        return None, None, "verify_failed"
    cue_path = split / cue_rom.name
    cue_path.write_bytes(cue_bytes)
    return cue_path, split, ""


def _rebuild_dvd_one(chd_path: Path, game_name: str, iso_rom, chd, settings,
                     comp_dvd, index, st: RebuildChdStats, dry_run: bool,
                     log: LogCB, cancel, detail=None) -> None:
    """Gra DVD (PS2: pojedynczy .iso) spakowana JAKO CD (createcd) —
    przepakowanie kontenera na createdvd (SERYJNIE). Przerwanie NIE ubija
    bieżącej konwersji — pętla wyżej sprawdza cancel PRZED kolejną grą."""
    from . import fixer
    st.checked += 1
    try:
        info = chd.info(chd_path)
    except OSError:
        st.errors += 1
        return
    if not info.is_cd_typed:
        st.ok_layout += 1               # już DVD — kontener poprawny
        if index is not None:
            try:
                index.set_bad_container(chd_path, 0)
            except Exception:
                pass
        return
    log(f"ODBUDOWA CD→DVD: {chd_path}  →  {chd_path} (w miejscu)  "
        f"[{game_name}]")
    if dry_run:
        st.rebuilt += 1
        return
    need = int(chd_path.stat().st_size * 3.2)
    tmp = _scratch_tmp(chd_path, need, log,
                       fallback=getattr(settings, "scratch_dir", "") or None)
    if tmp is None:
        st.skipped_space += 1
        log(f"   POMIJAM: brak miejsca (RAM/dysk) na ~{need/1024**3:.1f} GB")
        return
    try:
        dp = _mk_detail(detail, chd_path.name)
        iso, oc = _prep_dvd(chd_path, game_name, iso_rom, tmp, chd, log, dp)
        if oc == "errors":
            st.errors += 1
            return
        if oc == "verify_failed":
            st.verify_failed += 1
            return
        split = iso.parent
        out = fixer.create_from_source(
            chd, iso, MediaType.DVD, split, settings,
            compression=comp_dvd, log=lambda m: log(f"   {m}"),
            cancel_event=None, on_progress=dp)
        if not out.ok:
            st.errors += 1
            log(f"   createdvd/verify: {out.message}")
            return
        new_chd = split / (iso.stem + ".chd")
        if not new_chd.is_file():
            st.errors += 1
            return
        # sumy z pliku w SCRATCHU (RAM) PRZED podmianą — bez ponownego odczytu
        # całego CHD z NAS po przeniesieniu (to potrafiło „stać" minuty na 100%).
        _sums = None
        if index is not None:
            from .fileindex import hash_file
            try:
                _sums = hash_file(new_chd)
            except OSError:
                _sums = None
        from .linker import hardlink_twins, relink_twins
        twins = hardlink_twins(chd_path, index)     # przed podmianą
        _place_final(new_chd, chd_path, detail)
        st.rebuilt += 1
        log(f"   ✔ kontener CD→DVD podmieniony: {chd_path.name}")
        if index is not None and _sums is not None:
            crc, md5, sha1 = _sums
            index.record_file(chd_path, crc, md5, sha1)
            index.set_data_sha1(chd_path, iso_rom.sha1.lower())
            index.set_bad_container(chd_path, 0)   # kontener naprawiony
        relink_twins(chd_path, twins, index, log)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _rebuild_one(chd_path: Path, game_name: str, data, cue_rom, lib, chd,
                 settings, comp, index, st: RebuildChdStats, dry_run: bool,
                 log: LogCB, cancel, detail=None) -> None:
    """Odbudowa JEDNEGO pliku CHD do kanonicznego kontenera (per gra)."""
    from . import fixer
    st.checked += 1
    n_chd = _chd_cd_tracks(chd, chd_path)
    if n_chd == len(data):
        st.ok_layout += 1
        if index is not None:
            try:
                index.set_bad_container(chd_path, 0)
                index.set_layout_ok(chd_path, 1)   # następnym razem bez NAS
            except Exception:
                pass
        return                              # kontener już kanoniczny
    cue_bytes = lib.load(cue_rom.sha1)
    if cue_bytes is None:
        st.no_cue += 1
        log(f"BRAK CUE w bibliotece: {game_name}")
        return
    log(f"ODBUDOWA (ścieżki w CHD: {n_chd}, w DAT: {len(data)}): "
        f"{chd_path}  →  {chd_path} (w miejscu)  [{game_name}]")
    if dry_run:
        st.rebuilt += 1
        return
    need = int(chd_path.stat().st_size * 3.2)   # obraz+ścieżki+nowy CHD
    tmp = _scratch_tmp(chd_path, need, log,
                       fallback=getattr(settings, "scratch_dir", "") or None)
    if tmp is None:
        st.skipped_space += 1
        log(f"   POMIJAM: brak miejsca (RAM/dysk) na ~{need/1024**3:.1f} GB")
        return
    try:
        dp = _mk_detail(detail, chd_path.name)
        cue_path, split, oc = _prep_cd(chd_path, game_name, data, cue_rom,
                                       cue_bytes, tmp, chd, log, dp)
        if oc == "errors":
            st.errors += 1
            return
        if oc == "verify_failed":
            st.verify_failed += 1
            return
        out = fixer.create_from_source(
            chd, cue_path, MediaType.CD, split, settings,
            compression=comp, log=lambda m: log(f"   {m}"),
            cancel_event=None, on_progress=dp)
        if not out.ok:
            st.errors += 1
            log(f"   createcd/verify: {out.message}")
            return
        new_chd = split / (cue_path.stem + ".chd")
        if not new_chd.is_file():
            st.errors += 1
            return
        # sumy ze SCRATCHU (RAM) PRZED podmianą — patrz uwaga w _rebuild_dvd_one.
        _sums = None
        if index is not None:
            from .fileindex import hash_file
            try:
                _sums = hash_file(new_chd)
            except OSError:
                _sums = None
        from .linker import hardlink_twins, relink_twins
        twins = hardlink_twins(chd_path, index)     # przed podmianą
        _place_final(new_chd, chd_path, detail)
        st.rebuilt += 1
        log(f"   ✔ kanoniczny CHD podmieniony: {chd_path.name}")
        if index is not None and _sums is not None:
            from .datfile import game_profile
            crc, md5, sha1 = _sums
            index.record_file(chd_path, crc, md5, sha1)
            # odcisk KOMPLETU ścieżek (nie pojedynczej — 1S vs 5S!)
            index.set_data_sha1(chd_path, game_profile(data))
            index.set_bad_container(chd_path, 0)   # kontener kanoniczny
            index.set_layout_ok(chd_path, 1)
        relink_twins(chd_path, twins, index, log)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
