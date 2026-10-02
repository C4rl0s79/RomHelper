"""Hierarchia DAT-ów — JEDNO źródło prawdy dla dedupu (kopia fizyczna vs link).

Reguła (user): o tym, gdzie leży kopia fizyczna, a gdzie link, decydują
WYŁĄCZNIE katalog docelowy DAT-u i hierarchia DAT-ów (``DatStore.sort_entries``:
kolejność folderów (_kolejnosc.json) → ``_priorytet.txt`` → większy DAT). Nie
kolejność operacji w przebiegu i nie rezerwacje.

- Plik leży w katalogu docelowym DAT-u → należy do tego DAT-u.
- DAT niżej w hierarchii, który ma TĘ SAMĄ TREŚĆ (sumy / odcisk gry), robi
  do niego HARDLINK, nigdy go nie przenosi. Nazwa platformy NIE gra roli
  (0.6.93: „xbox360" z dir2dat vs „Microsoft - Xbox 360 (Digital)" — te same
  dane w dwóch miejscach = hardlink, user 01.10).
- Nie ma jednego katalogu głównego: punkt startowy pliku = NAJWYŻSZY DAT,
  który go ma; reszta to hardlinki (równorzędne z plikiem), także w ROMS.
- DAT z JAWNYM wymuszeniem „zawsze kopie fizyczne" (dedup_copies=false)
  trzyma wszystko fizycznie — nie linkuje.
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
    dir: str                # dir_key(target_dir)
    physical_only: bool     # dedup_copies=false (wymuszenie kopii fizycznych)


# Pliki NADPISYWANE przez programy (frontend, emulator, edytor) — nigdy nie
# łączymy ich hardlinkiem: zapis w miejscu przez jedną nazwę zmieniłby
# wszystkie (0.6.93: gamelist.xml ↔ gamelist.xml.backup1 w dir2dat RetroBata).
_MUTABLE_EXT = {".xml", ".json", ".cfg", ".ini", ".txt", ".log", ".bak",
                ".tmp", ".old", ".m3u", ".lst", ".db", ".srm", ".sav",
                ".nvram", ".eep", ".rtc"}
_MUTABLE_PARTS = (".backup", ".bak", ".tmp", ".state")


def linkable(path) -> bool:
    """Czy plik wolno łączyć hardlinkiem z innym (dane tylko do odczytu:
    ROM-y, obrazy płyt, archiwa, grafiki, wideo, czcionki)."""
    name = Path(str(path)).name.lower()
    if Path(name).suffix in _MUTABLE_EXT:
        return False
    return not any(p in name for p in _MUTABLE_PARTS)


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
        try:
            d = dir_key(entry.target_dir)
        except Exception:
            return None
        node = DatNode(entry=entry, rank=len(self._by_id), dir=d,
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
            from .datfile import game_profile
            for g in games:
                for r in list(g.roms) + list(getattr(g, "disks", None) or ()):
                    if r.sha1:
                        shas.add(r.sha1.lower())
                    if r.crc and r.size:
                        crcs.add((r.crc.lower().zfill(8), int(r.size)))
                # ODCISK gry (data_sha1 pliku CHD całej gry): DAT płytowy zna
                # sumy torów, a CHD w jego katalogu to JEGO kopia — dysk DAT-u
                # niżej (Arcade1TB psx) rozpoznaje rodzica po tym odcisku
                try:
                    prof = game_profile(g.data_roms)
                except Exception:
                    prof = ""
                if prof:
                    shas.add(prof.lower())
            c = self._content[id(entry)] = (shas, crcs)
        # SHA-1 ALBO CRC+rozmiar: DAT-y bez SHA-1 (FinalBurn Neo, MAME — same
        # CRC) też „mają" treść. Dawniej przy znanym SHA-1 sprawdzaliśmy TYLKO
        # SHA-1 → DAT z samymi CRC nigdy nie był właścicielem i naprawa kasowała
        # jego pliki (przepakowanie FBNeo → No-intro/T-En, 29.09).
        if sha1 and sha1.lower() in c[0]:
            return True
        return bool(crc and size) and (crc.lower().zfill(8), int(size)) in c[1]

    @staticmethod
    def _ids(rom) -> list:
        """Sumy, po których pytamy „czy DAT ma tę treść": `rom.ids` (lista
        (sha1, crc, size) — wszystko, co indeks wie o PLIKU: suma całego
        pliku, członkowie archiwum, odcisk gry, nagłówek CHD) albo sam ROM.
        Ten sam plik bywa opisany różnie (zip jako gra-archiwum w FBNeo vs
        zip jako plik w dir2dat) — 01.10 ping-pong TMNT III."""
        ids = getattr(rom, "ids", None)
        if ids:
            return list(ids)
        return [((getattr(rom, "sha1", "") or ""), (getattr(rom, "crc", "") or ""),
                 getattr(rom, "size", 0) or 0)]

    def _has_any(self, entry, ids) -> bool:
        return any(self._has_content(entry, sha1, crc, size)
                   for sha1, crc, size in ids if sha1 or (crc and size))

    def must_keep_source(self, entry, src, dest, rom,
                         same_bytes: bool = True) -> bool:
        """Czy plik `src` NALEŻY do innego DAT-u, który po zabraniu go NIE
        dostanie linku — wtedy `entry` ma zrobić własną KOPIĘ, a nie przenieść
        (albo przepakować i skasować) źródło.

        Przykład: te same ROM-y MSX w „Microsoft - MSX" (ROMS\\msx, nazwa
        „10-Yard Fight (Japan)") i „FinalBurn Neo - MSX 1 Games" (nazwa
        „10yard" — inne nazwy wewn. = inna treść). Dawniej każda
        naprawa ZABIERAŁA zip drugiemu DAT-owi (przepakowanie + skasowanie
        źródła) i następna oddawała go z powrotem — tysiące przepakowań w kółko.
        Źródło w katalogu DAT-u NIŻEJ (np. 1G1R → ROMS) wolno przenieść:
        tamten DAT zlinkuje do nowej kopii — ale TYLKO gdy nowy plik ma TE SAME
        BAJTY (`same_bytes`). Przepakowanie z innymi nazwami wewn. (FBNeo
        „2010p.col" → No-intro „2010 (USA).col") to inny plik: hardlink
        niemożliwy, więc źródło zostaje u właściciela."""
        me = self.node(entry)
        owner = self.dat_at(src)
        if me is None or owner is None:
            return False
        ids = [i for i in self._ids(rom) if i[0] or (i[1] and i[2])]
        # WSZYSTKIE DAT-y katalogu źródła poza pytającym — także gdy katalog
        # jest WSPÓLNY (dir2dat „mame" + DAT MAME z dyskami, 0.6.93)
        owners = [n for n in self._all_by_dir.get(owner.dir, [owner])
                  if n is not me
                  and (not ids or self._has_any(n.entry, ids))]
        if not owners:
            return False            # żaden DAT tamtego katalogu tej gry nie ma
        if not same_bytes:
            return True             # inny plik — właściciel nie zlinkuje
        return not all(self.should_link(n.entry, dest, at=src)
                       for n in owners)

    def owned_above(self, entry, path, rom) -> bool:
        """`path` leży w katalogu DAT-u WYŻEJ I któryś DAT
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
        ids = [i for i in self._ids(rom) if i[0] or (i[1] and i[2])]
        if not ids:
            return True            # bez sum nie rozstrzygniemy — jak dotąd
        me = self.node(entry)
        for n in self._all_by_dir.get(owner.dir, [owner]):
            if me is not None and n.rank >= me.rank:
                continue
            if self._has_any(n.entry, ids):
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
        """`path` leży w katalogu DAT-u WYŻEJ w hierarchii niż `entry` — także
        w katalogu WSPÓLNYM z DAT-em wyżej (0.6.93: dir2dat „mame" + DAT MAME:
        te same dane = hardlink, nie kopia). Nazwa platformy nie gra roli."""
        me = self.node(entry)
        owner = self.dat_at(path)
        return bool(me and owner and owner.rank < me.rank)

    def should_link(self, entry, physical, at=None) -> bool:
        """Czy `entry` ma zrobić LINK (hardlink) do pliku fizycznego `physical`
        zamiast własnej kopii: plik w katalogu DAT-u wyżej, ALBO duplikat
        treści we WŁASNYM katalogu (ten sam DAT / DAT-y dzielące katalog —
        0.6.93: te same dane = hardlink). Nie dla DAT-u z wymuszeniem kopii
        fizycznych i nie do LUŹNEGO pliku DAT-u konwertowanego do CHD/RVZ
        (konwersja kasuje luźne źródła — link by wisiał, katastrofa D2).
        `at` — miejsce, które stanie się linkiem: OBA końce muszą być danymi
        tylko do odczytu (`linkable`), np. nie `x.png.tmp` → `x.png`."""
        me = self.node(entry)
        if me is None or me.physical_only or not linkable(physical):
            return False
        if at is not None and not linkable(at):
            return False
        if self.above(entry, physical):
            return True
        owner = self.dat_at(physical)
        if owner is None or owner.dir != me.dir:
            return False
        fmt = str(getattr(entry, "store_format", "keep") or "keep").lower()
        if (fmt in ("chd", "rvz")
                and Path(str(physical)).suffix.lower() not in (".chd", ".rvz")):
            return False
        return True
