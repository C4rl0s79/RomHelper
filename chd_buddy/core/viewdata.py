"""Dane widoku drzewa DAT-ów liczone w WĄTKU ROBOCZYM (0.6.96).

Po zakończeniu skanu / podglądu / naprawy / wczytania DAT-ów okno liczyło to
samo w swoim wątku: zapis i odczyt stanu wszystkich DAT-ów (~1 mln gier: 11 s),
liczby gier per DAT, reguły (NAS), licznik ToSort (NAS), warianty tłumaczeń —
„Brak odpowiedzi" na dziesiątki sekund. Tu jest to policzone przed końcem
zadania; okno tylko podstawia gotowe dane i rysuje (`SuiteWindow._fill_dats`
z `view=`).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional, Sequence


def dat_key(entry) -> str:
    """Klucz DAT-u jak w oknie (`SuiteWindow._dat_key`)."""
    return str(Path(os.path.abspath(entry.dat_path)))


def counts_from_states(states: dict) -> tuple:
    """(gry, komplet, do naprawy, brak) z {gra: {rom: status|RomState}}."""
    from .matcher import game_stats_from_states
    m = {g: {rn: getattr(s, "state", s) for rn, s in roms.items()}
         for g, roms in (states or {}).items()}
    return game_stats_from_states(m)


def dat_counts(entries: Sequence, states: dict, reports=None) -> dict:
    """{dat_key: (gry, komplet, naprawa, brak)} — świeży raport ma
    pierwszeństwo przed zapisanym stanem (jak `_game_statuses_for`). DAT bez
    stanu nie ma wpisu (w drzewie: tylko liczba gier, bez kolorów)."""
    live: dict = {}
    for r in reports or ():
        live[dat_key(r.entry)] = r
    out: dict = {}
    for e in entries:
        k = dat_key(e)
        rep = live.get(k)
        if rep is not None:
            g: dict = {}
            for s in rep.statuses:
                g.setdefault(s.game, {})[s.rom.name.lower()] = s.state
        else:
            g = (states or {}).get(k)
        if g:
            out[k] = counts_from_states(g)
    return out


def tree_extras(entries: Sequence, dat_root, tosort_dirs: Sequence = ()) -> dict:
    """Odczyty z NAS potrzebne drzewu: reguła skip per DAT (_reguly.json) i
    liczba pozycji w każdym ToSort (iterdir)."""
    skip: dict = {}
    try:
        if dat_root and Path(str(dat_root)).is_dir():
            from .dirrules import DirRules
            rules = DirRules(Path(str(dat_root)))
            skip = {dat_key(e): bool(rules.for_entry(e)["skip"])
                    for e in entries}
    except Exception:
        skip = {}
    tosort: list = []
    for ts in tosort_dirs or ():
        exists = Path(str(ts)).is_dir()
        n = ""
        if exists:
            try:
                n = str(sum(1 for _ in Path(str(ts)).iterdir()))
            except OSError:
                n = "?"
        tosort.append((str(ts), exists, n))
    return {"skip": skip, "tosort": tosort}


def live_view(entries: Sequence, states: dict, dat_root,
              tosort_dirs: Sequence = ()) -> dict:
    """Widok dla odświeżenia W TRAKCIE naprawy (po etapie 1): stany są już
    policzone w wątku naprawy, dokładamy liczby i odczyty z NAS."""
    v = {"states": states, "counts": dat_counts(entries, states)}
    v.update(tree_extras(entries, dat_root, tosort_dirs))
    return v


def prepare_view(entries: Sequence, *, reports=None, save: bool = False,
                 dat_root=None, tosort_dirs: Sequence = (), rom_root=None,
                 saved=None, log: Optional[Callable[[str], None]] = None,
                 progress: Optional[Callable] = None) -> dict:
    """Wszystko, czego drzewo DAT-ów potrzebuje po operacji.

    reports — świeże raporty (skan / podgląd); `save` — zapisz je do stanu
    (DOKŁADAJĄC do zapamiętanego — DAT-y wyłączone w tym skanie zachowują
    ostatni stan); `saved` — (saved_at, states) już wczytane (bez ponownego
    odczytu)."""
    from .datcache import load_report_states, save_report_states
    if progress:
        progress(0, 0, "przygotowuję widok…")
    view: dict = {"variant_index": None, "trans_store": None,
                  "summary": None, "error": None}
    if reports is not None and save:
        try:
            save_report_states(reports)
        except Exception as e:                    # zapis cache nie może ubić wyniku
            view["error"] = f"nie zapisano cache raportu: {e}"
            if log:
                log(f"UWAGA: {view['error']}")
    if saved is None:
        try:
            saved = load_report_states(known_keys={dat_key(e) for e in entries})
        except Exception as e:
            saved = (None, {})
            if log:
                log(f"UWAGA: nie wczytano stanu raportu: {e}")
    view["saved_at"], view["states"] = saved
    view["counts"] = dat_counts(entries, view["states"], reports)
    view.update(tree_extras(entries, dat_root, tosort_dirs))
    # tłumaczenia + podsumowanie gier (tylko przy świeżych raportach)
    if reports is not None:
        try:
            from .dirrules import DirRules
            from .translations import TranslationStore, build_variant_index
            view["trans_store"] = TranslationStore(
                Path(str(rom_root)) / TranslationStore.FILENAME)
            _dr = DirRules(Path(str(dat_root)))
            view["variant_index"] = build_variant_index(
                reports, lambda e: _dr.for_entry(e))
        except Exception as e:                    # tłumaczenia nie mogą ubić skanu
            view["variant_error"] = str(e)
        stats = [r.game_stats() for r in reports]
        view["summary"] = (len(reports), sum(s[1] for s in stats),
                           sum(s[2] for s in stats), sum(s[3] for s in stats))
    return view
