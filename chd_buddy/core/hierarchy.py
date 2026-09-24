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
        return node

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
