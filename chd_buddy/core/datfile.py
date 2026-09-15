"""Parser plików DAT (Logiqx XML, format Redump/No-Intro) + indeks po hashu.

Do walidacji naprawionych obrazów: po wypakowaniu obrazu z CHD liczymy jego
SHA-1 i sprawdzamy, czy odpowiada znanemu, poprawnemu zrzutowi w DAT. Trafienie
= dane są kanonicznie poprawne (nie tylko „kontener się rozpakowuje").

Klasyfikacja nośnika wg rozszerzeń ROM-ów w grze:
  * .iso                -> DVD
  * .bin / .cue / .gdi  -> CD
Reguła kciuka Redump PS2: gra z plikami bin/cue to obraz CD, z .iso to DVD.

DAT-y bywają duże (dziesiątki tysięcy wpisów), więc używamy iterparse i
czyścimy elementy w locie, żeby nie trzymać całego drzewa w pamięci.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .models import MediaType


@dataclass
class DatRom:
    name: str
    size: int = 0
    crc: str = ""
    md5: str = ""
    sha1: str = ""
    merge: str = ""      # MAME: ten ROM jest WSPÓŁDZIELONY z rodzicem pod nazwą
                         # `merge` (w secie split/merged bierze się go z parenta)


@dataclass
class DatGame:
    name: str
    roms: List[DatRom] = field(default_factory=list)
    cloneof: str = ""    # MAME: nazwa gry-RODZICA (klon), np. darkseal1→darkseal
    romof: str = ""      # MAME: skąd dziedziczy ROM-y (zwykle == cloneof)

    @property
    def media(self) -> MediaType:
        exts = {Path(r.name).suffix.lower().lstrip(".") for r in self.roms}
        if "iso" in exts:
            return MediaType.DVD
        if exts & {"bin", "cue", "gdi"}:
            return MediaType.CD
        return MediaType.UNKNOWN

    @property
    def data_roms(self) -> List[DatRom]:
        """ROM-y niosące dane (bez samego .cue/.gdi)."""
        return [r for r in self.roms
                if Path(r.name).suffix.lower() not in (".cue", ".gdi")]


@dataclass
class DatMatch:
    game: str
    media: MediaType
    rom_name: str


def game_profile(roms) -> str:
    """ODCISK CAŁEJ GRY: sha1 z połączonych sum wszystkich ścieżek danych.

    Jedna ścieżka => jej własny sha1 (kompatybilne z nagłówkiem DVD-CHD).
    Wiele ścieżek => syntetyczny hash listy sum W KOLEJNOŚCI. Dwa wydania
    tej samej gry (np. Panzer Dragoon 1S vs 5S) potrafią dzielić ścieżkę
    DANYCH i różnić się tylko audio — pojedyncza suma NIE identyfikuje gry,
    komplet ścieżek tak."""
    import hashlib as _h
    sums = [r.sha1.lower() for r in roms if r.sha1]
    if not sums:
        return ""
    if len(sums) == 1:
        return sums[0]
    return _h.sha1(",".join(sums).encode("ascii")).hexdigest()


class DatIndex:
    """Indeks wielu DAT-ów po SHA-1 (a także MD5/CRC) danych ROM-ów."""

    def __init__(self) -> None:
        self.by_sha1: Dict[str, DatMatch] = {}
        self.by_md5: Dict[str, DatMatch] = {}
        self.by_crc: Dict[str, DatMatch] = {}
        self.games: int = 0
        self.roms: int = 0
        # suma rozmiarów ścieżek gry -> [(nazwa, [(rozmiar, sha1), …])].
        # Do identyfikacji SKLEJONYCH obrazów multi-track (CHD zrobione ze
        # złym/bez cue — układ ścieżek przepadł): tniemy obraz wg rozmiarów
        # z DAT-a i weryfikujemy sha1 każdej ścieżki.
        self.size_profiles: Dict[int, list] = {}
        # ODCISK CAŁEJ GRY (game_profile) -> DatMatch. Identyfikacja CHD musi
        # trafiać w KOMPLET ścieżek, nie pojedynczą sumę (1S vs 5S!).
        self.by_profile: Dict[str, DatMatch] = {}

    def add_game(self, game: DatGame) -> None:
        self.games += 1
        media = game.media
        for r in game.roms:
            self.roms += 1
            m = DatMatch(game.name, media, r.name)
            if r.sha1:
                self.by_sha1[r.sha1.lower()] = m
            if r.md5:
                self.by_md5[r.md5.lower()] = m
            if r.crc:
                self.by_crc[r.crc.lower().zfill(8)] = m
        data = game.data_roms
        if len(data) > 1 and all(r.size > 0 and r.sha1 for r in data):
            total = sum(r.size for r in data)
            self.size_profiles.setdefault(total, []).append(
                (game.name, [(r.size, r.sha1.lower()) for r in data]))
        prof = game_profile(data)
        if prof:
            self.by_profile[prof] = DatMatch(
                game.name, media, data[0].name if data else "")

    def match_profile(self, profile: str) -> Optional[DatMatch]:
        """Trafienie po ODCISKU CAŁEJ GRY (komplet ścieżek)."""
        return self.by_profile.get((profile or "").lower())

    def match_sha1(self, sha1: str) -> Optional[DatMatch]:
        return self.by_sha1.get(sha1.lower())

    def match_md5(self, md5: str) -> Optional[DatMatch]:
        return self.by_md5.get(md5.lower())

    def load(self, path: Path) -> "DatIndex":
        for game in parse_dat(path):
            self.add_game(game)
        return self

    def load_many(self, paths: List[Path]) -> "DatIndex":
        for p in paths:
            self.load(p)
        return self

    @classmethod
    def from_paths(cls, paths: List[Path]) -> "DatIndex":
        idx = cls()
        expanded: List[Path] = []
        for p in paths:
            if p.is_dir():
                expanded.extend(sorted(p.glob("*.dat")))
            elif p.is_file():
                expanded.append(p)
        return idx.load_many(expanded)


def _looks_xml(path: Path) -> bool:
    """Czy plik zaczyna się jak XML (`<`) — inaczej traktujemy jak ClrMamePro."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(512)
    except OSError:
        return True                              # niech XML-owa ścieżka zgłosi błąd
    # pomiń BOM i białe znaki
    chunk = chunk.lstrip(b"\xef\xbb\xbf").lstrip()
    return chunk[:1] == b"<"


def parse_dat_header(path: Path) -> dict:
    """Czyta nagłówek DAT-a: name, description, version. Obsługuje Logiqx XML
    (`<header>`) oraz ClrMamePro (`clrmamepro ( … )`). Nie czyta całego pliku."""
    if not _looks_xml(path):
        return _cmpro_header(path)
    out = {"name": "", "description": "", "version": ""}
    try:
        for _event, elem in ET.iterparse(str(path), events=("end",)):
            if elem.tag == "header":
                for key in out:
                    node = elem.find(key)
                    if node is not None and node.text:
                        out[key] = node.text.strip()
                break
            if elem.tag in ("game", "machine"):
                break  # brak nagłówka — nie czytaj dalej
    except ET.ParseError:
        pass
    return out


def parse_dat(path: Path):
    """Generator gier z pliku DAT. Logiqx XML albo ClrMamePro (auto-wykrycie)."""
    if not _looks_xml(path):
        yield from _parse_cmpro(path)
        return
    context = ET.iterparse(str(path), events=("end",))
    for _event, elem in context:
        if elem.tag != "game" and elem.tag != "machine":
            continue
        name = elem.get("name", "")
        roms: List[DatRom] = []
        for r in elem.findall("rom"):
            try:
                size = int(r.get("size", "0") or 0)
            except ValueError:
                size = 0
            roms.append(DatRom(
                name=r.get("name", ""),
                size=size,
                crc=(r.get("crc") or "").strip(),
                md5=(r.get("md5") or "").strip(),
                sha1=(r.get("sha1") or "").strip(),
                merge=(r.get("merge") or "").strip(),
            ))
        if roms:
            # MAME: relacje rodzic/klon (świadomość merged/split/non-merged)
            yield DatGame(name=name, roms=roms,
                          cloneof=(elem.get("cloneof") or "").strip(),
                          romof=(elem.get("romof") or "").strip())
        elem.clear()  # zwolnij pamięć


# --- ClrMamePro (format tekstowy, np. libretro BIOS/System.dat) --------------
import re as _re

# token: "łańcuch w cudzysłowie" | ( | ) | goły-wyraz
_CMPRO_TOK = _re.compile(r'"([^"]*)"|(\()|(\))|([^\s()]+)')
_CMPRO_GAME_KW = {"game", "machine", "set", "resource"}
# bloki wewnątrz gry, które POMIJAMY (nie niosą ROM-ów potrzebnych do matchu)
_CMPRO_SKIP_BLOCK = {"disk", "release", "biosset", "sample", "archive", "chip",
                     "video", "sound", "input", "dipswitch", "driver", "device"}
_CMPRO_ROM_KEYS = {"name", "size", "crc", "md5", "sha1", "merge", "flags",
                   "date", "status", "serial"}


def _cmpro_tokens(text: str) -> list:
    out = []
    for m in _CMPRO_TOK.finditer(text):
        if m.group(1) is not None:
            out.append(("str", m.group(1)))
        elif m.group(2):
            out.append(("(", "("))
        elif m.group(3):
            out.append((")", ")"))
        else:
            out.append(("word", m.group(4)))
    return out


def _cmpro_skip(toks: list, i: int, n: int) -> int:
    """Pomija zawartość bloku `( … )` (z zagnieżdżeniem). `i` wskazuje ZA `(`."""
    depth = 1
    while i < n and depth > 0:
        k = toks[i][0]
        if k == "(":
            depth += 1
        elif k == ")":
            depth -= 1
        i += 1
    return i


def _cmpro_read_rom(toks: list, i: int, n: int):
    """Czyta `rom ( name … size … crc … )`. `i` wskazuje ZA `(`."""
    attrs: Dict[str, str] = {}
    while i < n and toks[i][0] != ")":
        t, v = toks[i]
        if t == "word" and v.lower() in _CMPRO_ROM_KEYS and i + 1 < n \
                and toks[i + 1][0] in ("str", "word"):
            attrs[v.lower()] = toks[i + 1][1]
            i += 2
            continue
        i += 1
    if i < n and toks[i][0] == ")":
        i += 1
    try:
        size = int(attrs.get("size", "0") or 0)
    except ValueError:
        size = 0
    rom = DatRom(name=attrs.get("name", ""), size=size,
                 crc=(attrs.get("crc") or "").strip(),
                 md5=(attrs.get("md5") or "").strip(),
                 sha1=(attrs.get("sha1") or "").strip(),
                 merge=(attrs.get("merge") or "").strip())
    return (rom if rom.name else None), i


def _cmpro_read_game(toks: list, i: int, n: int):
    """Czyta blok `game ( … )`. `i` wskazuje ZA `(`. Zwraca (DatGame|None, i)."""
    name = cloneof = romof = ""
    roms: List[DatRom] = []
    while i < n and toks[i][0] != ")":
        t, v = toks[i]
        if t == "word":
            key = v.lower()
            if key == "rom" and i + 1 < n and toks[i + 1][0] == "(":
                rom, i = _cmpro_read_rom(toks, i + 2, n)
                if rom:
                    roms.append(rom)
                continue
            if key in _CMPRO_SKIP_BLOCK and i + 1 < n and toks[i + 1][0] == "(":
                i = _cmpro_skip(toks, i + 2, n)
                continue
            if key in ("name", "cloneof", "romof") and i + 1 < n \
                    and toks[i + 1][0] in ("str", "word"):
                val = toks[i + 1][1]
                if key == "name":
                    name = val
                elif key == "cloneof":
                    cloneof = val
                else:
                    romof = val
                i += 2
                continue
            if key in ("description", "year", "manufacturer", "comment",
                       "category") and i + 1 < n \
                    and toks[i + 1][0] in ("str", "word"):
                i += 2
                continue
        i += 1
    if i < n and toks[i][0] == ")":
        i += 1
    game = DatGame(name=name, roms=roms, cloneof=cloneof, romof=romof)
    return (game if roms else None), i


def _parse_cmpro(path: Path):
    """Generator gier z DAT-a w formacie ClrMamePro (`game ( … rom ( … ) )`)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    toks = _cmpro_tokens(text)
    i, n = 0, len(toks)
    while i < n:
        t, v = toks[i]
        if t == "word" and v.lower() in _CMPRO_GAME_KW and i + 1 < n \
                and toks[i + 1][0] == "(":
            game, i = _cmpro_read_game(toks, i + 2, n)
            if game:
                yield game
        elif t == "word" and v.lower() == "clrmamepro" and i + 1 < n \
                and toks[i + 1][0] == "(":
            i = _cmpro_skip(toks, i + 2, n)       # nagłówek — pomiń tutaj
        else:
            i += 1


def _cmpro_header(path: Path) -> dict:
    """Nagłówek DAT-a ClrMamePro: `clrmamepro ( name … description … version … )`."""
    out = {"name": "", "description": "", "version": ""}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(8192)                    # nagłówek jest na górze
    except OSError:
        return out
    toks = _cmpro_tokens(text)
    n = len(toks)
    for i in range(n):
        if toks[i][0] == "word" and toks[i][1].lower() == "clrmamepro" \
                and i + 1 < n and toks[i + 1][0] == "(":
            j = i + 2
            while j < n and toks[j][0] != ")":
                t, v = toks[j]
                if t == "word" and v.lower() in out and j + 1 < n \
                        and toks[j + 1][0] in ("str", "word"):
                    out[v.lower()] = toks[j + 1][1].strip()
                    j += 2
                    continue
                j += 1
            break
    return out
