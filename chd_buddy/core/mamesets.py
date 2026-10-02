"""Składanie zestawów arcade (MAME/FBNeo) w wybranym formacie — CZYSTA logika.

DAT split/merged niesie relacje, z których DA SIĘ złożyć dowolny format:
- `cloneof`  — klon → nazwa rodzica,
- `merge=`   — ROM klona WSPÓŁDZIELONY z rodzicem (w merged/split bierze się go z
               rodzica; jest wypisany w liście ROM-ów klona),
- `isbios`   — set BIOS (pgm/neogeo/skns…),
- `romof`    — zależność od BIOS-u/rodzica.

Formaty (per DAT, wybór w regule):
- **non-merged** — każdy set (rodzic, klon, BIOS) = własny KOMPLETNY zip: wszystkie
  swoje ROM-y pod własnymi nazwami. BIOS zostaje osobnym setem (ROM-ów BIOS-u NIE
  wtapiamy w gry — emulator i tak wymaga zipa BIOS-u).
- **split** — klon = tylko ROM-y UNIKALNE (bez `merge=`); współdzielone dobiera z
  rodzica w czasie gry. Rodzic i BIOS = własne ROM-y.
- **merged** — rodzic = swoje ROM-y + UNIKALNE ROM-y wszystkich klonów; klony NIE
  mają własnego zipa. BIOS osobno.

Wszystko tu jest CZYSTE (bez dostępu do dysku/indeksu) — wejściem są obiekty DAT-u
(`DatGame`/`DatRom`), więc łatwo to przetestować i użyć w matcherze/rebuilderze.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

FORMATS = ("non-merged", "split", "merged")
DEFAULT_FORMAT = "non-merged"


def normalize_format(fmt: str | None) -> str:
    f = (fmt or "").strip().lower().replace("_", "-")
    return f if f in FORMATS else DEFAULT_FORMAT


def has_parent_clone(games: Sequence) -> bool:
    """Czy DAT ma logikę MAME parent/clone/BIOS (cloneof/romof/isbios). Tylko dla
    TAKICH DAT-ów wybór `arcade_format` (split/merged/non-merged) ma sens — reszta
    (zwykłe kolekcje) go ignoruje."""
    for g in games:
        if getattr(g, "cloneof", "") or getattr(g, "romof", "") \
                or getattr(g, "isbios", False):
            return True
    return False


def _has_parent(g, by_name: dict) -> bool:
    return bool(g.cloneof) and g.cloneof in by_name


def plan_sets(games: Sequence, fmt: str) -> Dict[str, List]:
    """Zwraca {nazwa_setu: [DatRom, …]} — co POWINIEN fizycznie zawierać każdy zip
    w danym formacie. Nazwa członka = `rom.name` (nazwa z listy danego setu).

    Klon-sierota (rodzic spoza tego DAT-u) jest traktowany jak samodzielny set
    (jego pełna lista ROM-ów), żeby nigdy nie zgubić danych."""
    fmt = normalize_format(fmt)
    by_name = {g.name: g for g in games}
    clones_of: Dict[str, list] = {}
    for g in games:
        if g.cloneof:
            clones_of.setdefault(g.cloneof, []).append(g)

    out: Dict[str, List] = {}

    if fmt == "non-merged":
        for g in games:
            out[g.name] = list(g.roms)
        return out

    if fmt == "split":
        for g in games:
            if _has_parent(g, by_name):
                out[g.name] = [r for r in g.roms if not r.merge]
            else:
                out[g.name] = list(g.roms)
        return out

    # merged: klon wchodzi do rodzica; klon-sierota zostaje samodzielny
    for g in games:
        if _has_parent(g, by_name):
            continue
        roms = list(g.roms)
        seen = {r.name for r in roms}
        for cl in clones_of.get(g.name, []):
            for r in cl.roms:
                if not r.merge and r.name not in seen:
                    roms.append(r)
                    seen.add(r.name)
        out[g.name] = roms
    for g in games:                       # klony-sieroty (rodzic spoza DAT-u)
        if _has_parent(g, by_name) is False and g.cloneof and g.name not in out:
            out[g.name] = list(g.roms)
    return out


def set_exists(game, games: Sequence, fmt: str) -> bool:
    """Czy dana gra ma WŁASNY zip w tym formacie. W merged klon (z obecnym
    rodzicem) NIE ma własnego setu — jego ROM-y są w rodzicu."""
    fmt = normalize_format(fmt)
    if fmt != "merged":
        return True
    by_name = {g.name: g for g in games}
    return not _has_parent(game, by_name)


def target_roms(game, games: Sequence, fmt: str) -> List:
    """Lista ROM-ów, które powinien zawierać WŁASNY zip danej gry (pusta, gdy w
    tym formacie gra nie ma własnego setu — merged klon)."""
    return plan_sets(games, fmt).get(game.name, [])


def _by_name(entry) -> dict:
    """{nazwa: gra} dla DAT-u (cache na obiekcie entry)."""
    m = getattr(entry, "_game_by_name", None)
    if m is None:
        m = {g.name: g for g in (getattr(entry, "games", None) or [])}
        try:
            entry._game_by_name = m
        except Exception:
            pass
    return m


def bios_rom_names(game, by_name: dict) -> set:
    """Nazwy ROM-ów dostarczanych przez BIOS gry (łańcuch `romof` aż do setu
    `isbios`). Pusty zbiór, gdy gra nie zależy od BIOS-u z tego DAT-u."""
    seen: set = set()
    g = game
    while True:
        dep = getattr(g, "romof", "") or ""
        if not dep or dep in seen or dep not in by_name:
            return set()
        seen.add(dep)
        g = by_name[dep]
        if getattr(g, "isbios", False):
            return {r.name for r in g.roms}


def effective_roms(entry, game) -> List:
    """ROM-y, które POWINIEN zawierać własny zip gry wg `entry.arcade_format`
    (WSPÓLNE dla matchera i rebuildera — muszą liczyć TO SAMO, inaczej pętla
    „przepakuj").

    - set BIOS / gra bez zależności: pełna lista;
    - split: gra z RODZICEM lub BIOS-em obecnym w DAT-cie = tylko ROM-y
      unikalne (bez `merge=`) — współdzielone emulator bierze z rodzica/BIOS-u.
      Dotyczy KLONÓW i gier na BIOS-ie (np. ddp2 → pgm); dawniej tylko klonów,
      przez co ddp2.zip „potrzebował" ROM-ów pgm, a dedup kopiował całe zipy;
    - non-merged / merged: pełna lista, ale BEZ ROM-ów BIOS-u (BIOS zawsze
      osobnym zipem — decyzja usera, żaden format nie wtapia BIOS-u w gry).
    Klon-sierota / zależność spoza DAT-u: pełna lista (nie gubimy danych)."""
    roms = list(game.roms)
    if getattr(game, "isbios", False):
        return roms
    cloneof = getattr(game, "cloneof", "") or ""
    romof = getattr(game, "romof", "") or ""
    if not (cloneof or romof):
        return roms
    by_name = _by_name(entry)
    fmt = normalize_format(getattr(entry, "arcade_format", "") or "")
    if fmt == "split":
        dep_present = (cloneof in by_name) if cloneof else (romof in by_name)
        if not dep_present:
            return roms                   # sierota — nie gubimy współdzielonych
        uniq = [r for r in roms if not getattr(r, "merge", "")]
        return uniq if uniq else roms
    bios = bios_rom_names(game, by_name)
    if not bios:
        return roms
    out = [r for r in roms
           if not (getattr(r, "merge", "") and r.merge in bios)]
    return out if out else roms


def is_arcade(entry) -> bool:
    """DAT z logiką parent/clone/BIOS (cache na entry)."""
    v = getattr(entry, "_is_arcade", None)
    if v is None:
        v = has_parent_clone(getattr(entry, "games", None) or [])
        try:
            entry._is_arcade = v
        except Exception:
            pass
    return bool(v)


def family_of(game) -> str:
    """Nazwa RODZINY parent/clone: rodzic dla klona, własna nazwa dla rodzica/BIOS.
    BIOS jest ZAWSZE własną rodziną (nie łączymy gier z BIOS-em)."""
    if getattr(game, "isbios", False):
        return game.name
    return game.cloneof or game.name


def families(games: Sequence) -> Dict[str, List]:
    """{rodzina: [gry rodziny]} — rodzic + jego klony razem; BIOS osobno. Do zasady
    „przy 'tylko pełne' wystarczy JEDNA grywalna wersja na rodzinę parent/clone":
    rodzina jest zaspokojona, gdy ≥1 jej gra jest kompletna (availability liczy
    matcher; tu tylko struktura)."""
    by_name = {g.name: g for g in games}
    fam: Dict[str, List] = {}
    for g in games:
        # klon-sierota (rodzic spoza DAT-u) = własna rodzina (nie zgubimy go)
        root = g.name if getattr(g, "isbios", False) else (
            g.cloneof if g.cloneof in by_name else g.name)
        fam.setdefault(root, []).append(g)
    return fam
