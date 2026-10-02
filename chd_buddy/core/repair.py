"""Formuła NAPRAWY KOLEKCJI — jedno miejsce, bez GUI.

Wcześniej cały przebieg siedział w oknie (`SuiteWindow._collection_fix`), więc
nie dało się go uruchomić ani sprawdzić w całości poza programem: ciche miejsca
wychodziły dopiero u usera, platforma po platformie. Tu ten sam przebieg jest
funkcją: GUI tylko ją woła, a podgląd (dry_run) można puścić headless na całej
kolekcji (audyt, testy).

Kolejność (katalog po katalogu, z góry na dół):
  1) sprzątnięcie pozostałości obok gotowych CHD,
  2) IN-PLACE — konwersja ze źródła (luźne→CHD/RVZ/ZIP na RAM, do celu finał),
  3) placement (rename/repack w miejscu + uzupełnienie z ToSort) + fallback
     konwersji + sprzątanie TEGO katalogu,
  4) złe kontenery CHD, kasowanie źródeł skonwertowanych.
Na końcu RAZ: dedup (dziecko→rodzic), porządki w ToSort, sieroty → ToSort.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .i18n import tr

LogCB = Callable[[str], None]


@dataclass
class RepairOptions:
    dats: str
    roms: str
    tosort: str = ""                    # główny ToSort (tam trafiają nieznane)
    tosorts: list = field(default_factory=list)   # wszystkie ToSort
    clean: bool = True
    only_complete: bool = True
    dedup: bool = True
    del_tosort: bool = True
    convert: bool = True
    make_links: bool = True
    dry: bool = True


def _save_state(reports, log: LogCB) -> None:
    """Zapis podsumowania (komplet / do naprawy / brak) per DAT — to, co okno
    pokazuje po starcie. Błąd zapisu nie może przerwać naprawy."""
    try:
        from .datcache import save_report_states
        save_report_states(reports)
    except Exception as e:
        log(f"   (nie zapisano stanu do okna: {e})")


def repair_collection(opts: RepairOptions, settings, entries, idx, *,
                      log: LogCB = lambda m: None,
                      progress: Callable = lambda d, t, s: None,
                      cancel=None, detail=None, slot=None,
                      on_game: Optional[Callable] = None,
                      on_reload: Optional[Callable] = None):
    """Cały przebieg naprawy/podglądu. Zwraca RebuildStats albo None, gdy
    bezpiecznik (nieistniejący rom_root) zatrzymał pracę przed dotknięciem
    plików.

    `on_game(dat_key, gra, {rom: RomState})` — gra naprawiona (stan NA ŻYWO,
    jak w RomVault: wypadkowa operacji, bez dopasowania); `on_reload(stan)` —
    zapisany stan wszystkich DAT-ów odświeżony (po etapie 1)."""
    import threading
    from .dirrules import DirRules, missing_roots, scan_roots
    from .rebuilder import Rebuilder
    if cancel is None:
        cancel = threading.Event()
    dats, roms, dry = opts.dats, opts.roms, opts.dry
    tosort, tosorts = opts.tosort, list(opts.tosorts or [])
    convert, clean = opts.convert, opts.clean
    # biblioteka cue (<ToSort>/cues) — źródło tylko do odczytu, nigdy
    # kasowane ani przenoszone (user 01.10)
    from .paths import protect, protected_dirs_for
    protect(protected_dirs_for([tosort, *tosorts]))

    rules = DirRules(dats)
    if rules.fatal:                        # bezpiecznik: bez reguł nic nie ruszamy
        log(f"BŁĄD: {rules.error}")
        return None
    if rules.error:
        log(f"UWAGA: {rules.error}")
    # DAT-y: z pamięci (jeśli wczytane), inaczej odkryj TERAZ (cache per DAT →
    # sekundy). Pozwala kliknąć Napraw od razu po starcie.
    _ents = entries
    if not _ents:
        from .datstore import DatStore
        from .dirrules import apply_rule_targets
        progress(0, 0, tr("wczytywanie DAT-ów…"))
        _ents = DatStore(dats, roms).discover(log=log, cancel=cancel)
        apply_rule_targets(_ents, rules, roms, log=log)
    # BEZPIECZNIK: nieistniejący rom_root => naprawa przeniosłaby całą
    # kolekcję. Przerywamy PRZED dotknięciem plików.
    bad = missing_roots(_ents, rules, roms)
    if bad:
        log("PRZERWANO — nieistniejące katalogi bazowe (rom_root):")
        for name, path in bad:
            log(f"   {path}   (reguła dla: {name})")
        return None
    sroots = scan_roots(_ents, rules, roms, tosorts)
    if not dry:
        from .convert import purge_temp_artifacts
        from .linker import remove_broken_links
        # ŚMIECI po przerwanych konwersjach: DUŻE temp żyją na SCRATCHU
        # (RAM-dysk / scratch_dir / work_dir), NIE w kolekcji — więc zamiatamy
        # TYLKO scratch. Pełny os.walk po NAS-owej kolekcji przy KAŻDEJ Naprawie
        # to były minuty ciszy w „Start…".
        from . import ramdisk as _rd
        _scratch_roots: list = []
        _ram = _rd.active_root()
        if _ram:
            _scratch_roots.append(str(_ram))
        for _sd in (settings.scratch_dir, settings.work_dir):
            if _sd and Path(_sd).is_dir():
                _scratch_roots.append(_sd)
        if _scratch_roots:
            progress(0, 0, tr("sprzątanie śmieci po konwersjach…"))
            n_t, sz_t = purge_temp_artifacts(_scratch_roots, log=log,
                                             cancel=cancel)
            if n_t:
                log(f"Sprzątnięto {n_t} śmieci po przerwanych konwersjach "
                    f"({sz_t/1024**3:.2f} GB odzyskane).")
        # zerwane symlinki (cel przeniesiony/skonwertowany) — psują konwersje;
        # usuwamy, odtworzą się przy naprawie. Po INDEKSIE + responsywny cancel.
        progress(0, 0, tr("zerwane linki…"))
        n_b = remove_broken_links(sroots, index=idx, log=log, cancel=cancel)
        if n_b:
            log(f"Usunięto {n_b} zerwanych symlinków.")
    # PRZEPIS Z INDEKSU (bez skanu plików): dopasowanie w locie. Włączone DAT-y
    # (skip=false); wynik odzwierciedla stan indeksu, więc gry już naprawione
    # (HAVE) wypadają → WZNAWIANIE.
    _enabled = [e for e in _ents if not rules.for_entry(e)["skip"]]
    try:
        from .translations import TranslationStore
        _tsub = TranslationStore(
            Path(settings.rom_root) / TranslationStore.FILENAME).subs
    except Exception:
        _tsub = {}
    from .matcher import match_reports
    # wiedza o CHD od bliźniaków (hardlinki/kopie) — sam indeks, bez NAS; także
    # w podglądzie (to wiedza o treści, nie zmiana plików). Bez tego np. hardlink
    # dziecka nie wie, że kontener rodzica jest zły/dobry.
    try:
        idx.fill_from_twins(log)
    except Exception as e:
        log(f"UWAGA: wiedza od bliźniaków niedostępna ({e})")
    progress(0, 0, tr("dopasowanie z indeksu…"))
    reports = match_reports(
        _enabled, idx, subs=_tsub, log=log,
        on_progress=lambda i, n, t: progress(i, n, t),
        detail=detail, cancel=cancel, label=tr("dopasowanie"))
    log(f"{'PODGLĄD' if dry else 'NAPRAWA'} z przepisu: {len(reports)} DAT-ów "
        f"(dopasowanie z indeksu, bez skanu plików).")
    # PODGLĄD nic nie zmienia → te raporty SĄ aktualnym stanem kolekcji (GUI
    # odświeża nimi liczby „do naprawy" bez ponownego dopasowania)
    _state_reports = reports if dry else None
    dedup_roots = [Path(r) for r in sroots] if opts.dedup else []
    # „usuń z ToSort pliki już na miejscu" działa dla WSZYSTKICH katalogów
    # ToSort (kopia potwierdzona gdzie indziej = zbędna)
    del_from = [Path(t) for t in tosorts if t] if opts.del_tosort else []
    rb = Rebuilder(idx, tosort=Path(tosort) if tosort else None,
                   dry_run=dry, log=log, make_links=opts.make_links,
                   detail=detail, zip_level=settings.zip_level,
                   zip_method=getattr(settings, "zip_method", "deflate"))
    # dedup wg hierarchii DAT-ów (wszystkie, także pominięte — ich katalogi
    # trzymają kopie fizyczne): kopia u rodzica → dziecko linkuje
    rb.set_hierarchy(_ents, rules)

    # STAN NA ŻYWO: rebuilder zgłasza naprawioną grę → do okna jej stan ROM-ów
    def _emit_game(entry, game):
        if on_game is None or dry:
            return
        rep = _rep_by_entry.get(id(entry))
        if rep is None:
            return
        roms = {x.rom.name.lower(): x.state for x in rb._statuses_of(rep, game)}
        try:
            on_game(str(Path(os.path.abspath(entry.dat_path))), game, roms)
        except Exception:
            pass

    _rep_by_entry: dict = {id(r.entry): r for r in reports}
    rb.on_game_fixed = _emit_game

    def _mark_converted(rep, keys) -> None:
        """Gry skonwertowane ze źródła (CHD/RVZ/ZIP gotowe) → „jest"."""
        pre = f"{id(rep.entry)}::"
        for k in keys or ():
            if k.startswith(pre):
                rb.mark_game_fixed(rep, k[len(pre):])

    def _mark_rebuilt(rep) -> None:
        """Złe kontenery CHD naprawione w tym DAT-cie (indeks: bad_container=0)."""
        for x in rep.statuses:
            if not getattr(x, "bad_container", False) or not x.source_path:
                continue
            try:
                r = idx.lookup(x.source_path)
            except Exception:
                r = None
            if r is not None and r["bad_container"] == 0:
                rb.mark_game_fixed(rep, x.game, x.canonical_path)

    def _make_tools():
        from .convert import detect_dolphintool
        emu = settings.emulators_dir
        tools = {"settings": settings, "chdman": None}
        try:
            from .chdman import CHDMan
            tools["chdman"] = CHDMan(settings.chdman_path or None)
        except Exception:
            tools["chdman"] = None
        tools["dolphintool"] = (detect_dolphintool(Path(emu))
                                if emu and Path(emu).is_dir() else None)
        return tools

    from .convert import (convert_from_source, convert_reports,
                          purge_loose_on_verified_chd, purge_source_files)
    _tools = _make_tools()
    # zależności naprawy kontenera CHD budujemy RAZ (nie per katalog: CueLibrary
    # czyta katalog cues) i wołamy per katalog.
    _bad_chd_ctx = None
    _rebuild_seen: set = set()             # jeden plik = jedna odbudowa w przebiegu
    if convert:
        try:
            from .chdman import CHDMan
            from .cuelib import CueLibrary
            _bad_chd_ctx = (CHDMan(settings.chdman_path or None),
                            CueLibrary(Path(dats) / "cues", log=log),
                            [Path(t) for t in tosorts
                             if t and Path(t).is_dir()])
        except Exception as _e:
            log(f"Naprawa kontenera CHD niedostępna: {_e}")
            _bad_chd_ctx = None

    from .prune import prune_empty_trees, purge_orphan_descriptors
    ntot = len(reports)

    # ── ETAP 1/2: SZYBKIE operacje we WSZYSTKICH katalogach ────────────────
    # Linki (hardlinki dziecko → rodzic), przeniesienia i zmiany nazw na tym
    # samym dysku, spłaszczanie, wypakowania — sekundy, bez przesyłania danych.
    # Dawniej szły katalog po katalogu RAZEM z wolną konwersją/odbudową CHD, więc
    # przerwanie w ROMS (dni odbudowy PS2 przez internet) zostawiało No-intro i
    # 1G1R bez ani jednego linku. Gry, które pójdą do KONWERSJI, pomijamy tu —
    # ich listę daje podgląd konwersji (z indeksu, bez NAS), a zrobi je etap 2.
    log("══ ETAP 1/2: szybkie operacje (linki, przeniesienia, zmiany nazw) "
        "we wszystkich katalogach")
    rb.defer_slow = True          # przepakowania zipów → etap 2
    _plan_finals: dict = {}                     # plan konwersji (dzieci → rodzic)
    for rep_i, rep in enumerate(reports):
        if cancel.is_set():
            break
        eff = rules.for_entry(rep.entry)
        if eff and eff.get("skip"):
            continue
        name = rep.entry.name
        progress(rep_i, ntot, f"etap 1/2 — {rep_i + 1}/{ntot}: {name}")
        _npre = purge_loose_on_verified_chd([rep], rules.for_entry, idx,
                                            log=log, dry_run=dry, cancel=cancel)
        if _npre:
            log(f"   sprzątnięto {_npre} pozostałości obok CHD.")
        pending: set = set()
        if convert:
            _, pending, _ = convert_from_source(
                [rep], rules.for_entry, _tools, index=idx, dry_run=True,
                log=lambda m: None, cancel=cancel, delete_roots=del_from,
                make_links=opts.make_links, hierarchy=rb.hierarchy,
                finals=_plan_finals, only_complete=opts.only_complete)
        rb.run([rep], clean=False, only_complete=opts.only_complete,
               rules=rules.for_entry, delete_placed_from=del_from,
               cancel=cancel, converted_games=pending, on_progress=progress,
               defer_global=True)
        # stan DAT-u po jego operacjach (te same statusy, przestawione na
        # bieżąco) → zapis; zamknięcie w trakcie nie zostawia starych liczb
        if not dry:
            _save_state([rep], log)
        if rb.cancelled:
            break
    if cancel.is_set() or rb.cancelled:
        log("PRZERWANO w etapie 1 — wykonane operacje są na dysku i w indeksie; "
            "kolejne „Napraw” dokończy resztę.")
        rb.stats.cancelled = True
        rb.stats.reports = reports if dry else None
        return rb.stats
    # ToSort: zbędne archiwa (cała treść już w kolekcji) i opisy ścieżek bez
    # torów — bezpieczne już teraz (treść leży w kolekcji), więc nie czekają na
    # wolny etap 2 (który użytkownik często przerywa)
    # (w PODGLĄDZIE nic nie znika, więc finał pokazałby te same pozycje drugi
    # raz — tam robi to tylko finał)
    if del_from and not dry:
        progress(0, 0, tr("ToSort: zbędne archiwa…"))
        rb._purge_redundant_tosort_archives(del_from, cancel)
        purge_orphan_descriptors(idx, del_from, log=log, dry_run=dry,
                                 cancel=cancel, progress=progress)
    # liczniki STANU (nie operacji) liczy od nowa etap 2 na świeżym przepisie —
    # inaczej „niekompletne"/„już OK"/„zły kontener" wychodziły podwójnie
    # (bad_container NIE: etap 2 widzi te ścieżki jako już obsłużone i ich
    # nie liczy — zostaje liczba z etapu 1, raz na plik CHD)
    rb.stats.already_ok = 0
    rb.stats.incomplete = 0

    # ── ETAP 2/2: WOLNE operacje katalog po katalogu ───────────────────────
    # konwersje (pobranie → kompresja → wysyłka), odbudowa złych CHD,
    # sprzątanie katalogu, kasowanie źródeł. Przepis PRZELICZONY z indeksu —
    # etap 1 zmienił kolekcję (podgląd: indeks bez zmian → te same raporty).
    log("══ ETAP 2/2: konwersje, odbudowa CHD, sprzątanie (katalog po katalogu)")
    rb.defer_slow = False
    if not dry:
        progress(0, 0, tr("dopasowanie z indeksu…"))
        reports = match_reports(
            _enabled, idx, subs=_tsub, log=log,
            on_progress=lambda i, n, t: progress(i, n, t),
            detail=detail, cancel=cancel, label=tr("dopasowanie"))
        if cancel.is_set():
            rb.stats.cancelled = True
            rb.stats.reports = None
            return rb.stats
        ntot = len(reports)
        # LICZBY NA EKRANIE NA BIEŻĄCO: ten przepis to stan PO etapie 1 dla
        # wszystkich DAT-ów — zapisujemy go od razu (za darmo, i tak policzony).
        # Dalej po każdym DAT-cie etapu 2 zapis tylko jego stanu. Dzięki temu
        # zapisane podsumowanie zawsze odpowiada indeksowi — nawet po zamknięciu
        # programu w trakcie naprawy start nie musi niczego przeliczać.
        _save_state(reports, log)
        _rep_by_entry.clear()
        _rep_by_entry.update({id(r.entry): r for r in reports})
        if on_reload is not None:
            try:
                from .datcache import states_from_reports
                on_reload(states_from_reports(reports))   # wątek naprawy, nie okna
            except Exception:
                pass
    done_reports: list = []
    # (platforma, odcisk) → plik finalny, WSPÓLNE dla wszystkich katalogów:
    # dziecko linkuje do CHD zrobionego przez rodzica wcześniej w tej naprawie
    _finals: dict = {}
    for rep_i, rep in enumerate(reports):
        if cancel.is_set():
            log(f"PRZERWANO naprawę na katalogu {rep_i}/{ntot} — katalogi WYŻEJ "
                f"są w pełni domknięte (in-place → ToSort → sprzątanie).")
            break
        eff = rules.for_entry(rep.entry)
        name = rep.entry.name
        progress(rep_i, ntot, f"katalog {rep_i + 1}/{ntot}: {name}")
        if eff and eff.get("skip"):
            log(f"══ {name}: POMINIĘTY (reguła skip)")
            continue
        log(f"══ KATALOG {rep_i + 1}/{ntot}: {name}")

        # 1) pozostałości obok gotowych CHD (przerywalne, samodzielne)
        _npre = purge_loose_on_verified_chd([rep], rules.for_entry, idx,
                                            log=log, dry_run=dry, cancel=cancel)
        if _npre:
            log(f"   sprzątnięto {_npre} pozostałości obok CHD.")

        # 2) IN-PLACE: konwersja prosto ze źródła (luźne/archiwum → CHD/RVZ na
        #    RAM, do celu trafia tylko finał).
        converted_games: set = set()
        src_to_purge: list = []
        if convert and not cancel.is_set():
            cst0, converted_games, src_to_purge = convert_from_source(
                [rep], rules.for_entry, _tools, index=idx, dry_run=dry,
                log=log, cancel=cancel, detail=detail, on_progress=progress,
                on_converted=rb.add_canonical, delete_roots=del_from,
                make_links=opts.make_links, slot=slot, hierarchy=rb.hierarchy,
                finals=_finals, only_complete=opts.only_complete)
            if converted_games:
                log(f"   konwersja ze źródła: {cst0.summary()} "
                    f"({len(converted_games)} gier).")
                if not dry:
                    _mark_converted(rep, converted_games)
            # źródła do skasowania po domknięciu katalogu — sprzątanie ich nie
            # przenosi do ToSort
            rb.add_pending_purge(src_to_purge)

        # fallback-konwersja „w miejscu" PO placemencie (dla gier, których nie
        # dało się zrobić prosto ze źródła).
        def _do_convert_one(_r=rep):
            if not (convert and not cancel.is_set()):
                return
            cst = convert_reports(
                [_r], rules.for_entry, _tools, index=idx, log=log,
                cancel=cancel, detail=detail, on_converted=rb.add_canonical,
                on_progress=lambda i, n, t: progress(i, n, f"konwersja: {t}"))
            if cst.converted:
                log(f"   konwersja w miejscu: {cst.summary()}")

        # 2+3) placement + fallback-konwersja + sprzątanie TEGO katalogu
        #      (clean → ToSort, puste podkatalogi). DEDUP odroczony.
        rb.run([rep], clean=clean, only_complete=opts.only_complete,
               rules=rules.for_entry, dedup_roots=dedup_roots,
               delete_placed_from=del_from, cancel=cancel,
               after_place=_do_convert_one, converted_games=converted_games,
               on_progress=progress, defer_global=True)

        # złe kontenery CHD (in-place) — DVD zrobione jako CD itp.
        if _bad_chd_ctx and convert and not cancel.is_set():
            from .chdrebuild import rebuild_bad_chds
            _chd, _lib, _extra = _bad_chd_ctx
            try:
                _rst = rebuild_bad_chds(
                    [rep.entry], _lib, _chd, settings, idx, extra_roots=_extra,
                    dry_run=dry, log=log, on_progress=progress, detail=detail,
                    cancel=cancel, slot=slot, seen=_rebuild_seen)
                if _rst.rebuilt or _rst.verify_failed or _rst.errors:
                    log(f"   naprawa kontenera CHD: {_rst.summary()}")
                if not dry and _rst.rebuilt:
                    _mark_rebuilt(rep)
            except Exception as _e:
                log(f"   naprawa kontenera CHD pominięta: {_e}")

        # 4) kasowanie źródeł gier skonwertowanych ze źródła — dopiero po
        #    DOMKNIĘCIU katalogu (współdzielone tory wielopłytowe były dostępne
        #    przez cały placement/fallback tego katalogu).
        if src_to_purge and not dry and not rb.cancelled:
            progress(0, 0, f"{name}: kasuję źródła po konwersji…")
            purge_source_files(src_to_purge, index=idx, log=log, dry_run=dry)

        # stan TEGO DAT-u po jego domknięciu → zapis. To te same statusy,
        # które operacje przestawiały na bieżąco — BEZ ponownego dopasowania.
        if not dry:
            _save_state([rep], log)

        if not rb.cancelled:
            done_reports.append(rep)

    # „Przerwij" MIĘDZY DAT-ami kończy pętlę przez `cancel`, ale nie ustawia
    # flagi rebuildera — bez tego finał (sieroty, dedup) szedł dalej jeszcze
    # godzinę po przerwaniu (30.09: 15:18 → 16:13)
    if cancel.is_set():
        rb.cancelled = True
    # FINAŁ GLOBALNY: dedup (dziecko→rodzic) + sprzątanie zbędnych archiwów i
    # pustych katalogów w ToSort. Wymaga PEŁNEGO obrazu, więc PO pętli i
    # pomijany przy przerwaniu.
    if not rb.cancelled and (dedup_roots or del_from):
        progress(0, 0, tr("finał: dedup i porządki w ToSort…"))
        rb.finalize_global(done_reports, dedup_roots=dedup_roots,
                           delete_placed_from=del_from, rules=rules.for_entry,
                           cancel=cancel)
    # OPISY ŚCIEŻEK bez torów (cue/gdi/toc zostawione po konwersji na CHD)
    if not rb.cancelled and not cancel.is_set() and del_from:
        purge_orphan_descriptors(idx, del_from, log=log, dry_run=dry,
                                 cancel=cancel, progress=progress)
    # PUSTE KATALOGI w ToSort i POD katalogami DAT-ów (same katalogi docelowe
    # i korzenie zostają). Obchód katalogów po NAS — tylko przy realnej
    # naprawie (podgląd nie dotyka NAS per katalog).
    if not dry and not rb.cancelled and not cancel.is_set():
        progress(0, 0, tr("finał: puste katalogi…"))
        _targets = [e.target_dir for e in _ents]
        _roots = [Path(t) for t in tosorts if t] + [
            Path(r.entry.target_dir) for r in done_reports]
        _np = prune_empty_trees(_roots, keep=_targets, log=log, cancel=cancel,
                                progress=progress)
        if _np:
            log(f"Usunięto {_np} pustych katalogów.")
    # SIEROTY: katalogi/pliki BEZ DAT-a (np. MAME) → ToSort. Używa WSZYSTKICH
    # odkrytych DAT-ów, więc platforma tylko WYŁĄCZONA NIE jest ruszana. Tylko
    # gdy włączone „sprzątanie" i bez przerwania (pełny obraz).
    from .datstore import failed_dats
    _failed = failed_dats()
    if clean and not rb.cancelled and tosort and _failed:
        # BEZPIECZNIK: katalog DAT-u, którego nie wczytano, wyglądałby na
        # sierotę → jego pliki do ToSort / skasowane (01.10, 1608 plików)
        log(f"POMIJAM sprzątanie sierot: nie wczytano {len(_failed)} DAT-ów "
            f"(np. {_failed[0]}) — ich katalogi wyglądałyby na sieroty. "
            f"Wczytaj DAT-y ponownie i powtórz naprawę.")
    elif clean and not rb.cancelled and tosort:
        progress(0, 0, tr("finał: nieznane pliki → ToSort…"))
        from .dirrules import stray_dirs as _stray
        _strays = _stray(_ents, rules, roms)
        n_orph = rb.sweep_orphans(_strays, [Path(roms)])
        if n_orph:
            log(f"Nieznane (brak DAT-a) → ToSort: {n_orph} plików (treść "
                f"niepasująca do żadnego DAT-u; pasujące przeniesiono do "
                f"targetów).")
    # flaga przerwania na STATS — GUI po niej odświeża stan z INDEKSU (bez skanu)
    rb.stats.cancelled = rb.cancelled or cancel.is_set()
    rb.stats.reports = _state_reports
    return rb.stats
