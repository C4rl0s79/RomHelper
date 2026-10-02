"""Sprzątanie po naprawie: osierocone opisy ścieżek w ToSort i puste katalogi.

- OPISY bez torów: `.cue`/`.gdi`/`.toc` leżący w ToSort w katalogu, w którym
  nie ma już żadnego toru (bin/img/iso/…), jest bezużyteczny — tory zabrała
  konwersja na CHD (cue ze zrzutu bywa bajtowo inny niż w DAT-cie, więc nie
  schodził razem z torami) albo nigdy ich nie było. Program ma własną bibliotekę
  cue (DatRoot\\cues), a paczki cue są do pobrania — kasujemy (decyzja usera).
  Decyzja z INDEKSU (zero rund SMB na plik); realne kasowanie sprawdza dysk.
- PUSTE KATALOGI: równoległy obchód drzew (NAS przez internet — jedna runda
  SMB na katalog, więc wątki), usuwanie od najgłębszych. Korzeni i katalogów
  docelowych DAT-ów (oraz ich przodków) NIE ruszamy — pusty katalog systemu
  (układ ES) to nie śmieć.
"""
from __future__ import annotations

import os
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, Optional

from .paths import is_protected

LogCB = Callable[[str], None]
ProgCB = Callable[[int, int, str], None]

DESC_EXTS = (".cue", ".gdi", ".toc")
# pliki „przy okazji" — nie są torami, więc nie ratują opisu przed skasowaniem
JUNK_EXTS = (".txt", ".nfo", ".url", ".xml", ".sfv", ".md5", ".sha1", ".jpg",
             ".jpeg", ".png", ".diz", ".dat", ".log")


def purge_orphan_descriptors(index, roots: Iterable, *, log: LogCB = lambda m: None,
                             dry_run: bool = False, cancel=None,
                             progress: Optional[ProgCB] = None) -> int:
    """Kasuje z `roots` (katalogi ToSort) opisy ścieżek bez żadnego toru obok.
    Zwraca liczbę skasowanych (w podglądzie: zaplanowanych)."""
    n = 0
    for root in roots:
        if not root:
            continue
        by_dir: dict[str, list[str]] = defaultdict(list)
        try:
            for row in index.all_under(root, physical_only=True):
                if row["missing"]:
                    continue
                p = row["path"]
                by_dir[os.path.normcase(os.path.dirname(p))].append(p)
        except Exception as e:
            log(f"Sprzątanie opisów ścieżek pominięte ({root}): {e}")
            continue
        victims = []
        for _d, files in by_dir.items():
            descs = [p for p in files if p.lower().endswith(DESC_EXTS)]
            if not descs:
                continue
            other = [p for p in files if not p.lower().endswith(DESC_EXTS)
                     and not p.lower().endswith(JUNK_EXTS)]
            if not other:                       # żadnego toru w katalogu
                # biblioteka cue (<ToSort>/cues) — tylko odczyt, nie kasujemy
                victims.extend(d for d in descs if not is_protected(d))
        total = len(victims) or 1
        for i, p in enumerate(sorted(victims), 1):
            if cancel is not None and cancel.is_set():
                return n
            if progress:
                progress(i, total, f"opisy bez torów: {os.path.basename(p)}")
            if dry_run:
                log(f"(podgląd) KASUJ z ToSort (opis ścieżek bez torów): {p}")
                n += 1
                continue
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass
            except OSError as e:
                log(f"  nie skasowano {p}: {e}")
                continue
            try:
                index.remove_path(p)
            except Exception:
                pass
            log(f"KASUJ z ToSort (opis ścieżek bez torów): {p}")
            n += 1
    return n


def prune_empty_trees(roots: Iterable, keep: Iterable = (), *,
                      log: LogCB = lambda m: None, dry_run: bool = False,
                      cancel=None, progress: Optional[ProgCB] = None,
                      workers: int = 8) -> int:
    """Usuwa puste katalogi POD `roots` (same korzenie zostają). `keep` —
    katalogi, których nie wolno usunąć (np. katalogi docelowe DAT-ów); ich
    przodkowie też są chronieni. Zwraca liczbę usuniętych (podgląd: do usunięcia)."""
    norm = os.path.normcase
    keep_set = set()
    for k in keep:
        p = Path(os.path.abspath(str(k)))
        keep_set.add(norm(str(p)))
        for a in p.parents:
            keep_set.add(norm(str(a)))
    roots = [Path(os.path.abspath(str(r))) for r in roots if r]
    for r in roots:
        keep_set.add(norm(str(r)))
    # obchód równoległy: katalog → (liczba plików, podkatalogi)
    info: dict[str, tuple[int, list[str]]] = {}
    lock = threading.Lock()
    seen = [0]

    def _scan(d: str) -> list[str]:
        files, subs = 0, []
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            subs.append(e.path)
                        else:
                            files += 1
                    except OSError:
                        files += 1               # nie wiadomo co to — nie ruszaj
        except OSError:
            files = 1                            # niedostępny — nie ruszaj
        with lock:
            info[d] = (files, subs)
            seen[0] += 1
            if progress and seen[0] % 50 == 0:
                progress(seen[0], 0, f"puste katalogi: {os.path.basename(d)}")
        return subs

    frontier = [str(r) for r in roots if r.is_dir()]
    with ThreadPoolExecutor(max(1, workers)) as ex:
        while frontier:
            if cancel is not None and cancel.is_set():
                return 0
            nxt: list[str] = []
            for subs in ex.map(_scan, frontier):
                nxt.extend(subs)
            frontier = nxt
    # od najgłębszych: pusty = 0 plików i wszystkie podkatalogi usunięte
    removed: set[str] = set()
    n = 0
    for d in sorted(info, key=lambda x: x.count(os.sep), reverse=True):
        if cancel is not None and cancel.is_set():
            break
        files, subs = info[d]
        if files or norm(d) in keep_set:
            continue
        if any(norm(s) not in removed for s in subs):
            continue
        if dry_run:
            log(f"(podgląd) USUŃ pusty katalog: {d}")
        else:
            try:
                os.rmdir(d)
            except OSError:
                continue                         # jednak coś w nim jest
            log(f"USUŃ pusty katalog: {d}")
        removed.add(norm(d))
        n += 1
    return n
