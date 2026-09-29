"""Hierarchia DAT-ów — JEDNO źródło prawdy dla dedupu (kopia fizyczna vs link).

Reguła (user): o tym, gdzie leży kopia fizyczna, a gdzie link, decydują
WYŁĄCZNIE katalog docelowy DAT-u i hierarchia DAT-ów (``DatStore.sort_entries``:
kolejność folderów (_kolejnosc.json) → ``_priorytet.txt`` → większy DAT). Nie
kolejność operacji w przebiegu i nie rezerwacje.

- Plik leży w katalogu docelowym DAT-u → należy do tego DAT-u.
- DAT niżej w hierarchii TEJ SAMEJ platformy robi do niego LINK, nigdy go nie
  przenosi.
- DAT-y różnych platform nigdy się nie linkują (ten sam dump na MSX i SMS =
  dwa pliki fizyczne).
- DAT z wymuszeniem „zawsze kopie fizyczne" (dedup_copies=false) trzyma
  WSZYSTKO fizycznie — nie linkuje.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from .paths import dir_key, is_under  # noqa: F401  (is_under — API modułu)


@dataclass(frozen=True)
class DatNode:
    entry: object
    rank: int               # pozycja w hierarchii (0 = najwyżej)
    platform: str           # efektywny klucz platformy (z aliasem z reguł)
    dir: str                # dir_key(target_dir)
    physical_only: bool     # dedup_copies=false (wymuszenie kopii fizycznych)


def _eff_fn(rules) -> Optional[Callable[[object], dict]]:
    if rules is None:
        return None
    return rules.for_entry if hasattr(rules, "for_entry") else rules


class Hierarchy:
    """Hierarchia DAT-ów zbudowana z posortowanych wpisów (rodzice pierwsi)."""

    def __init__(self, entries: Iterable = (), rules=None):
        self._by_id: dict[int, DatNode] = {}
        self._by_dir: dict[str, DatNode] = {}
        self._all_by_dir: dict[str, list] = {}   # wszystkie DAT-y katalogu
        self._content: dict[int, tuple] = {}     # id(entry) → (sha1, crc+size)
        self._eff = _eff_fn(rules)
        for e in entries or ():
            self.add(e)

    def __len__(self) -> int:
        return len(self._by_id)

    def add(self, entry, rules=None) -> Optional[DatNode]:
        """Dopisuje DAT na KOŃCU hierarchii (gdy jeszcze go nie ma)."""
        node = self._by_id.get(id(entry))
        if node is not None:
            return node
        eff_fn = _eff_fn(rules) or self._eff
        try:
            eff = (eff_fn(entry) if eff_fn else None) or {}
        except Exception:
            eff = {}
        from .datstore import platform_key
        alias = eff.get("platform", "")
        try:
            plat = platform_key(str(alias) if alias else entry.name)
            d = dir_key(entry.target_dir)
        except Exception:
            return None
        node = DatNode(entry=entry, rank=len(self._by_id), platform=plat, dir=d,
                       physical_only=not eff.get("dedup_copies", True))
        self._by_id[id(entry)] = node
        self._by_dir.setdefault(d, node)   # wspólny katalog → pierwszy (wyższy)
        self._all_by_dir.setdefault(d, []).append(node)
        return node

    def _has_content(self, entry, sha1: str, crc: str, size: int) -> bool:
        c = self._content.get(id(entry))
        if c is None:
            shas, crcs = set(), set()
            try:
                games = entry.load().games
            except Exception:
                games = []
            for g in games:
                for r in g.roms:
                    if r.sha1:
                        shas.add(r.sha1.lower())
                    if r.crc and r.size:
                        crcs.add((r.crc.lower().zfill(8), int(r.size)))
            c = self._content[id(entry)] = (shas, crcs)
        # SHA-1 ALBO CRC+rozmiar: DAT-y bez SHA-1 (FinalBurn Neo, MAME — same
        # CRC) też „mają" treść. Dawniej przy znanym SHA-1 sprawdzaliśmy TYLKO
        # SHA-1 → DAT z samymi CRC nigdy nie był właścicielem i naprawa kasowała
        # jego pliki (przepakowanie FBNeo → No-intro/T-En, 29.09).
        if sha1 and sha1.lower() in c[0]:
            return True
        return bool(crc and size) and (crc.lower().zfill(8), int(size)) in c[1]

    def must_keep_source(self, entry, src, dest, rom) -> bool:
        """Czy plik `src` NALEŻY do innego DAT-u, który po zabraniu go NIE
        dostanie linku — wtedy `entry` ma zrobić własną KOPIĘ, a nie przenieść
        (albo przepakować i skasować) źródło.

        Przykład: te same ROM-y MSX w „Microsoft - MSX" (ROMS\\msx, nazwa
        „10-Yard Fight (Japan)") i „FinalBurn Neo - MSX 1 Games" (nazwa
        „10yard"). Różne platformy = osobne pliki fizyczne; dawniej każda
        naprawa ZABIERAŁA zip drugiemu DAT-owi (przepakowanie + skasowanie
        źródła) i następna oddawała go z powrotem — tysiące przepakowań w kółko.
        Źródło w katalogu DAT-u tej samej platformy NIŻEJ (np. 1G1R → ROMS)
        wolno przenieść: tamten DAT zlinkuje do nowej kopii."""
        me = self.node(entry)
        owner = self.dat_at(src)
        if me is None or owner is None or owner.dir == me.dir:
            return False
        sha1 = (getattr(rom, "sha1", "") or "")
        crc = (getattr(rom, "crc", "") or "")
        size = getattr(rom, "size", 0) or 0
        owners = [n for n in self._all_by_dir.get(owner.dir, [owner])
                  if not (sha1 or (crc and size))
                  or self._has_content(n.entry, sha1, crc, size)]
        if not owners:
            return False            # żaden DAT tamtego katalogu tej gry nie ma
        return not all(self.should_link(n.entry, dest) for n in owners)

    def owned_above(self, entry, path, rom) -> bool:
        """`path` leży w katalogu DAT-u WYŻEJ (ta sama platforma) I któryś DAT
        tego katalogu MA tę treść (ROM `rom`) — dopiero wtedy to jego kopia
        fizyczna, do której `entry` robi link. Plik, którego żaden DAT tamtego
        katalogu nie zna, NIE jest kopią rodzica: fizyczna kopia powstaje w
        najwyższym DAT-cie, który tę grę ma (user: „jeśli nie ma w hierarchii
        wyżej, fizyczny plik powstaje niżej, a linki dopiero pod nim").
        Katalog bywa wspólny dla kilku DAT-ów (ROMS\\pc98: „NEC - PC-98" i
        „NEC - PC-98 (HardDisk)") — liczy się każdy z nich."""
        if not self.above(entry, path):
            return False
        owner = self.dat_at(path)
        if owner is None:
            return False
        sha1 = (getattr(rom, "sha1", "") or "")
        crc = (getattr(rom, "crc", "") or "")
        size = getattr(rom, "size", 0) or 0
        if not (sha1 or (crc and size)):
            return True            # bez sum nie rozstrzygniemy — jak dotąd
        me = self.node(entry)
        for n in self._all_by_dir.get(owner.dir, [owner]):
            if me is not None and (n.platform != me.platform or n.rank >= me.rank):
                continue
            if self._has_content(n.entry, sha1, crc, size):
                return True
        return False

    def node(self, entry) -> Optional[DatNode]:
        return self._by_id.get(id(entry))

    def dat_at(self, path) -> Optional[DatNode]:
        """DAT, w którego katalogu docelowym leży `path` (najbliższy przodek)."""
        if not self._by_dir or not path:
            return None
        p = Path(os.path.abspath(str(path)))
        for d in (p, *p.parents):
            node = self._by_dir.get(dir_key(d))
            if node is not None:
                return node
        return None

    def above(self, entry, path) -> bool:
        """`path` leży w katalogu DAT-u WYŻEJ w hierarchii tej samej platformy
        co `entry` (w innym katalogu niż własny)."""
        me = self.node(entry)
        owner = self.dat_at(path)
        return bool(me and owner and owner.dir != me.dir
                    and owner.platform == me.platform and owner.rank < me.rank)

    def should_link(self, entry, physical) -> bool:
        """Czy `entry` ma zrobić LINK do pliku fizycznego `physical` (zamiast
        własnej kopii). Tylko do DAT-u wyżej, ta sama platforma, i tylko gdy
        `entry` nie trzyma wszystkiego fizycznie."""
        me = self.node(entry)
        if me is None or me.physical_only:
            return False
        return self.above(entry, physical)
