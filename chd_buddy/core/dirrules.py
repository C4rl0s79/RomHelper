"""Kaskadowe reguły per katalog — odpowiednik „DAT rules" z RomVaulta.

Plik ``_reguly.json`` w katalogu DAT-ów (obok ``_priorytet.txt``):

    {
      "*":                      {"only_complete": true},
      "PS2":                    {"only_complete": false},
      "Sony - PlayStation 2":   {"skip": true},
      "stary_zestaw.dat":       {"skip": true}
    }

Klucz to (od najogólniejszego): "*", ścieżka katalogu DAT-a względem
dat_root (np. "PS2" albo "konsole/PS2"), nazwa DAT-a z nagłówka, nazwa
pliku .dat. Reguły nakładają się kaskadowo — bardziej szczegółowy klucz
NADPISUJE ogólniejszy (jak w RomVaulcie: „descendant wins").

Obsługiwane reguły:
  only_complete  (bool) — buduj tylko kompletne gry (domyślnie true),
  skip           (bool) — pomiń DAT całkowicie (nie raportuj, nie buduj),
  dedup_copies   (bool) — linki do DAT-ów wyżej w hierarchii (domyślnie true);
                          false = ZAWSZE kopie fizyczne (wymuszenie),
  target         (str)  — katalog docelowy DAT-a względem rom_root (zamiast
                          nazwy z nagłówka), np. "ps2" dla układu
                          EmulationStation/RetroBat.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

RULES_FILENAME = "_reguly.json"

# Docelowy format przechowywania plików gry (dotyczy DAT-a RODZICA — dzieci
# dostają symlinki). "keep" = nie konwertuj; "auto" = wg typu systemu
# (płyta→CHD, GameCube/Wii→RVZ, kartridż→zostaw/ZIP).
FORMATS = ("keep", "auto", "extract", "zip", "7z", "chd", "rvz")

# Konwencja nazw katalogów per system:
#   "dat" — z pola <header><name> DAT-a (np. "Sony - PlayStation 2")
#   "es"  — EmulationStation/Batocera (np. "ps2", "psx", "dreamcast")
NAMINGS = ("dat", "es")

DEFAULT_RULES: dict[str, Any] = {
    "only_complete": True,
    "skip": False,
    "dedup_copies": True,
    "target": "",
    # Gry wieloplikowe luzem w podkatalogu per gra (CHD/zipy zawsze płasko).
    "subdir_per_game": True,
    # Podmieniaj wersje (Japan) na fanowskie tłumaczenia (T-En) z innych DAT-ów.
    "prefer_translations": False,
    # ROLA DAT-u: "collection" (zwykły cel: parent/child) albo "translations"
    # (pula fanowskich tłumaczeń — nie cel podstawowy, dostarcza wariantów do
    # podmiany innych DAT-ów; patrz core/translations.py).
    "role": "collection",
    # Format przechowywania (patrz FORMATS).
    "format": "keep",
    # FORMAT ZESTAWÓW ARCADE (tylko DAT-y z logiką parent/clone — cloneof/merge):
    # "split" (domyślny; klon = tylko ROM-y unikalne), "merged" (klon w rodzicu),
    # "non-merged" (każdy set kompletny). Ignorowany dla DAT-ów bez parent/clone.
    "arcade_format": "split",
    # Konwencja nazw katalogów per system (patrz NAMINGS).
    "naming": "dat",
    # Nadpisanie bazowego katalogu ROM-ów (pusty = główny rom_root). Pozwala
    # np. dzieciom platformy lądować na innym dysku/roocie niż rodzic.
    "rom_root": "",
    # RĘCZNE przypięcie DAT-a do innej platformy (klucz platform_key albo
    # nazwa DAT-a rodzica). Np. "FinalBurn Neo - SNES Games" →
    # "nintendo super nintendo entertainment system": DAT staje się DZIECKIEM
    # tej platformy (hierarchia, dziedziczenie formatu), mimo innej nazwy.
    "platform": "",
}

# Skrót platformy → katalog EmulationStation/Batocera.
ES_FOLDER: dict[str, str] = {
    "PS1": "psx", "PS2": "ps2", "PS3": "ps3", "PSP": "psp", "PSVITA": "psvita",
    "DC": "dreamcast", "SATURN": "saturn", "MD": "megadrive",
    "SMS": "mastersystem", "GG": "gamegear", "NAOMI": "naomi",
    "GCN": "gamecube", "WII": "wii", "WIIU": "wiiu", "NSW": "switch",
    "N64": "n64", "SNES": "snes", "NES": "nes", "GB": "gb", "GBC": "gbc",
    "GBA": "gba", "NDS": "nds", "3DS": "3ds", "ARCADE": "arcade",
    "MAME": "mame", "NEOGEO": "neogeo", "XBOX": "xbox", "X360": "xbox360",
    "ATARI2600": "atari2600", "ATARI7800": "atari7800", "3DO": "3do",
    "PCENGINE": "pcengine",
    "NAOMI2": "naomi2", "SEGACD": "segacd", "JAGUAR": "atarijaguar",
    "ATARI5200": "atari5200", "LYNX": "lynx", "MSX": "msx", "MSX2": "msx2",
    "FBNEO": "fbneo", "AMIGA": "amiga", "C64": "c64", "PC98": "pc98",
    "SG1000": "sg1000", "SUPERGRAFX": "supergrafx", "PC88": "pc88",
    "PCFX": "pcfx", "FDS": "fds", "GAMEANDWATCH": "gameandwatch",
    "SATELLAVIEW": "satellaview", "SUFAMI": "sufami", "SEGA32X": "sega32x",
    "JAGUARCD": "atarijaguarcd", "AMIGACD32": "amigacd32",
    "ODYSSEY2": "odyssey2", "INTELLIVISION": "intellivision",
    "NEOGEOCD": "neogeocd",
    # 0.6.94 — nazwy jak w RetroBacie usera
    "WSWAN": "wswan", "WSWANC": "wswanc", "NGP": "ngp", "NGPC": "ngpc",
    "ZXSPECTRUM": "zxspectrum", "X68000": "x68000", "N64DD": "n64dd",
    "GAMEPOCK": "gamepock", "ARCHIMEDES": "archimedes", "AMIGACDTV": "amigacdtv",
    "FMTOWNS": "fmtowns", "PCENGINECD": "pcenginecd", "CDI": "cdi",
    "PS4": "ps4", "PS5": "ps5", "XBOXONE": "xboxone",
    "XBOXSERIESX": "xboxseriesx",
}

# Systemy PŁYTOWE (format auto → CHD, poza GameCube/Wii → RVZ).
# Płytowe systemy, których emulatory NIE czytają CHD (RPCS3, Xemu, Xenia) —
# „auto" zostawia obraz jak jest (ISO); zip tylko z jawnej reguły „archiwum".
NO_CHD_DISC_SYSTEMS = {"PS3", "XBOX", "X360", "PS4", "PS5", "XBOXONE",
                       "XBOXSERIESX"}

DISC_SYSTEMS = {"PS1", "PS2", "PS3", "PSP", "SATURN", "DC", "NAOMI", "3DO",
                "PCENGINE", "NEOGEOCD", "SEGACD", "MEGACD", "GCN", "WII",
                "PCENGINECD", "CDI"}


def save_rule(dat_root: Path, key: str, updates: dict, *,
              strip_defaults: bool = True) -> Path:
    """Zapisuje/aktualizuje regułę dla `key` (nazwa DAT-a/platforma/katalog)
    w _reguly.json, zachowując pozostałe wpisy.

    strip_defaults=True (domyślnie): wartości równe globalnym domyślnym są
    usuwane (plik czytelny) — dla reguł BAZOWYCH (folder/globalne).
    strip_defaults=False: zapisujemy PODANE wartości nawet gdy równe domyślnym
    (poza pustym target/rom_root = brak nadpisania) — POJEDYNCZE/zbiorcze
    nadpisania muszą przetrwać, bo reguła katalogu może ustawić wartość
    inną niż domyślna (np. folder=auto, a pojedynczy DAT ma być „keep")."""
    p = Path(dat_root) / RULES_FILENAME
    data: dict = {}
    if p.is_file():
        # NIECZYTELNY plik reguł NIE jest „pusty": dawniej zapis jednej reguły
        # nadpisywał WSZYSTKIE pozostałe (dane usera) — teraz odmowa
        loaded = _read_rules(p)
        if loaded is None:
            raise OSError(f"{RULES_FILENAME} nieczytelny — nie nadpisuję (napraw "
                          f"plik albo przywróć {RULES_FILENAME}.bak)")
        data = loaded
    rule = dict(data.get(key, {}))
    for name, val in updates.items():
        if strip_defaults:
            drop = val == DEFAULT_RULES.get(name)
        else:                             # zostaw jawne; usuń tylko puste ścieżki
            drop = name in _STR_RULES and name in ("target", "rom_root") and not val
        if drop:
            rule.pop(name, None)
        else:
            rule[name] = val
    if rule:
        data[key] = rule
    else:
        data.pop(key, None)
    from .fileops import atomic_write_text
    atomic_write_text(p, json.dumps(data, indent=2, ensure_ascii=False),
                      backup=True)
    return p


def _read_rules(p: Path):
    """Treść pliku reguł (dict) albo None, gdy nieczytelny/pusty/nie-JSON."""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# Sugerowany format przechowywania wg skrótu platformy (płytowe → CHD;
# GameCube/Wii → RVZ; reszta → keep/zip).
def suggest_format(system_short: str) -> str:
    s = (system_short or "").upper()
    if s in ("GCN", "WII"):
        return "rvz"
    if s in NO_CHD_DISC_SYSTEMS:
        return "keep"                # ISO — emulator nie czyta CHD ani zipa
    disc = {"PS1", "PS2", "PSP", "SATURN", "DC", "NAOMI", "MEGACD",
            "SEGACD", "PCECD", "3DO", "NEOGEOCD"}
    if s in disc:
        return "chd"
    return "keep"


# Reguły tekstowe (reszta jest boolowska).
_STR_RULES = {"target", "format", "naming", "rom_root", "platform", "role",
              "arcade_format"}


def _coerce(name: str, value):
    return str(value) if name in _STR_RULES else bool(value)


def _system_short(entry) -> str:
    """Skrót platformy (PS2/DC/…) z nazwy DAT-a — do ES/format."""
    from .icons import clean_system_name
    from .shortcuts import detect_system
    clean = clean_system_name(entry.name)
    return detect_system(clean) or detect_system(entry.name) or ""


def folder_name(entry, naming: str) -> str:
    """Nazwa katalogu docelowego per system wg konwencji."""
    if naming == "es":
        short = _system_short(entry)
        es = ES_FOLDER.get(short)
        if es:
            return es
    return entry.name          # domyślnie nazwa z <header><name>


# Jednoznaczne markery PŁYTY w nazwach ROM-ów DAT-a (obraz/opis ścieżek).
# `.bin`/`.img` celowo POMINIĘTE — bywają i w kartridżach, i w torach CD.
_DISC_MARKERS = {"iso", "cue", "gdi", "toc", "chd"}


def _dat_is_cartridge(entry) -> bool:
    """True, gdy DAT NIE zawiera plików PŁYTOWYCH (cue/iso/gdi/toc/chd) — czyli
    to kartridż/HuCard (np. PC Engine `.pce`), mimo że system bywa sklasyfikowany
    jako „płytowy". PC Engine ma OBA media (HuCard i CD) pod tym samym skrótem,
    więc o formacie musi decydować TREŚĆ DAT-u, nie sam system. Wtedy CHD nie ma
    sensu (goły ROM bez cue → i tak pomijany) → ZIP."""
    try:
        games = entry.load().games
    except Exception:
        return False
    checked = 0
    for g in games:
        for r in g.roms:
            name = getattr(r, "name", "") or ""
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in _DISC_MARKERS:
                return False          # jest płyta → nie kartridż
        checked += 1
        if checked >= 30:             # próbka wystarczy (spójny DAT)
            break
    return checked > 0


def _dat_group(entry) -> str:
    """Grupa DAT-u z JSON-a RomVaulta (`group`: ReDump/NoIntro/…) —
    znormalizowana („redump", „nointro"); "" gdy brak JSON-a."""
    meta = getattr(entry, "meta", None) or {}
    g = str(meta.get("group", "") or "").lower()
    return "".join(ch for ch in g if ch.isalnum())


def resolve_format(fmt: str, entry) -> str:
    """Rozwiązuje format 'auto' na konkret wg typu systemu (i TREŚCI DAT-u dla
    systemów dwumedialnych jak PC Engine)."""
    if fmt != "auto":
        return fmt
    short = _system_short(entry)
    if short in ("GCN", "WII"):
        return "rvz"
    if short in NO_CHD_DISC_SYSTEMS:
        return "keep"          # ISO jak jest (RPCS3/Xemu/Xenia bez CHD i zipa)
    # GRUPA z JSON-a RomVaulta przy DAT-cie (user 01.10): Redump = płyty →
    # CHD (system z obsługą CHD) albo obraz jak jest (ISO); No-Intro = zip.
    # Pewniejsze niż zgadywanie z nazwy („3DO Interactive Multiplayer" → zip).
    group = _dat_group(entry)          # „redump", „nointro", „propernointro"…
    if "redump" in group:
        return "chd" if short in DISC_SYSTEMS else "keep"
    if "nointro" in group:
        return "zip"
    if short in DISC_SYSTEMS:
        # system „płytowy", ale DAT może być kartridżowy (PC Engine HuCard) —
        # sprawdź treść: brak plików płytowych → ZIP, nie CHD.
        return "zip" if _dat_is_cartridge(entry) else "chd"
    return "zip"               # kartridż → ZIP


# komunikaty jednorazowych migracji (GUI wypisuje je do logu po wczytaniu DAT-ów)
_NOTICES: list[str] = []


def pop_notices() -> list[str]:
    out = list(_NOTICES)
    _NOTICES.clear()
    return out


def migrate_parent_priority(dat_root: Path) -> str:
    """JEDNORAZOWA migracja wycofanej reguły `parent_priority` („wszystkie DAT-y
    katalogu = rodzice"). Hierarchię wyznacza kolejność katalogów
    (_kolejnosc.json), a wymuszenie kopii fizycznych — `dedup_copies=false`:
    - parent_priority=true → dedup_copies=false (dalej zawsze fizycznie),
    - katalog-rodzic spoza zapisanej kolejności → dopisany za wymienionymi
      (tam stał dotąd: po wymienionych, przed resztą),
    - klucz parent_priority usuwany. Zwraca opis zmian ("" = nic)."""
    p = Path(dat_root) / RULES_FILENAME
    data = _read_rules(p) if p.is_file() else None
    if data is None:
        return ""
    keys = sorted((k for k, v in data.items()
                   if isinstance(v, dict) and "parent_priority" in v),
                  key=str.lower)
    if not keys:
        return ""
    from .folder_order import _load_raw, _norm, save_order
    order = _load_raw(dat_root)
    order_changed = False
    parents: list[str] = []
    for k in keys:
        rule = data[k]
        if bool(rule.pop("parent_priority")):
            rule["dedup_copies"] = False
            parents.append(k)
            if k != "*" and (Path(dat_root) / k).is_dir():
                parts = [x for x in str(k).replace("\\", "/").split("/") if x]
                parent = "/".join(parts[:-1])
                okey = next((x for x in order if _norm(x) == _norm(parent)),
                            parent)
                lst = list(order.get(okey, []))
                if _norm(parts[-1]) not in [_norm(x) for x in lst]:
                    lst.append(parts[-1])
                    order[okey] = lst
                    order_changed = True
        if not rule:
            data.pop(k)
    from .fileops import atomic_write_text
    atomic_write_text(p, json.dumps(data, indent=2, ensure_ascii=False),
                      backup=True)
    if order_changed:
        save_order(dat_root, order)
    msg = (f"Migracja reguł: „rodzic” wycofany — {', '.join(parents) or '—'} "
            f"→ „zawsze kopie fizyczne”"
            + (" + dopisane do kolejności katalogów" if order_changed else "")
            + ".")
    _NOTICES.append(msg)
    return msg


class DirRules:
    def __init__(self, dat_root: Path):
        self.dat_root = Path(os.path.abspath(dat_root))
        self.raw: dict[str, dict] = {}
        self.error = ""
        self.notice = ""
        # plik reguł ISTNIEJE, ale ani on, ani .bak nie dają się odczytać →
        # żadna operacja na plikach nie może ruszyć (domyślne reguły = inne
        # katalogi docelowe = masowe przenosiny do ToSort)
        self.fatal = False
        try:
            self.notice = migrate_parent_priority(self.dat_root)
        except OSError as e:
            self.error = f"{RULES_FILENAME}: migracja: {e}"
        p = self.dat_root / RULES_FILENAME
        if p.is_file():
            data = _read_rules(p)
            if data is None:
                bak = p.with_name(p.name + ".bak")
                data = _read_rules(bak) if bak.is_file() else None
                if data is None:
                    self.fatal = True
                    self.error = (f"{RULES_FILENAME} jest nieczytelny (pusty albo "
                                  f"uszkodzony) i brak dobrej kopii .bak — "
                                  f"STOP: bez reguł nie ruszam plików")
                    return
                self.notice = (f"{RULES_FILENAME} nieczytelny — użyto kopii "
                               f"{bak.name}")
                _NOTICES.append(self.notice)
            self.raw = {str(k).lower(): v for k, v in data.items()
                        if isinstance(v, dict)}

    def _entry_keys(self, entry) -> list[str]:
        """Klucze kaskady dla DAT-a, od najogólniejszego do najszczegółowszego
        (global „*" → katalogi → nazwa z nagłówka → plik .dat)."""
        keys: list[str] = ["*"]
        try:
            rel = entry.dat_path.parent.relative_to(self.dat_root)
        except ValueError:
            rel = Path()
        # kolejne poziomy katalogów: "konsole", "konsole/PS2", …
        parts = [p for p in rel.parts]
        for i in range(1, len(parts) + 1):
            keys.append("/".join(parts[:i]).lower())
        keys.append(entry.name.lower())
        keys.append(entry.dat_path.name.lower())
        keys.append(entry.dat_path.stem.lower())
        return keys

    def for_entry(self, entry) -> dict[str, Any]:
        """Efektywne reguły dla DAT-a (DatEntry) — kaskada ogólne→szczegółowe."""
        eff = dict(DEFAULT_RULES)
        for k in self._entry_keys(entry):
            rule = self.raw.get(k)
            if rule:
                for name in DEFAULT_RULES:
                    if name in rule:
                        eff[name] = _coerce(name, rule[name])
        return eff

    def for_key(self, folder_path: str) -> dict[str, Any]:
        """Efektywne reguły KATALOGU („ROMS", „ROMS/Sony") — kaskada global →
        kolejne poziomy katalogów (bez reguł pojedynczych DAT-ów)."""
        eff = dict(DEFAULT_RULES)
        parts = [x for x in str(folder_path).replace("\\", "/").split("/") if x]
        keys = ["*"] + ["/".join(parts[:i]).lower() for i in range(1, len(parts) + 1)]
        for k in keys:
            rule = self.raw.get(k)
            if rule:
                for name in DEFAULT_RULES:
                    if name in rule:
                        eff[name] = _coerce(name, rule[name])
        return eff

    def explicit_rule(self, entry, name: str):
        """Surowa wartość reguły `name` z kaskady (szczegółowy klucz wygrywa)
        albo None, gdy ŻADEN klucz jej nie ustawia. Odróżnia „nie ustawiono"
        od wartości domyślnej — do decyzji formatu per platforma."""
        val = None
        for k in self._entry_keys(entry):
            rule = self.raw.get(k)
            if rule and name in rule:
                val = _coerce(name, rule[name])
        return val


def missing_roots(entries, rules: DirRules, rom_root) -> list[tuple[str, str]]:
    """Katalogi bazowe (rom_root z reguł + główny), które NIE ISTNIEJĄ.

    Zabezpieczenie przed katastrofą: literówka w rom_root (np. „rom1" zamiast
    „roms") sprawia, że KAŻDY plik wygląda na „w złym miejscu" i naprawa
    zaczyna masowo przenosić całą kolekcję w nowe miejsce. Lepiej przerwać
    i zapytać, niż przenieść setki GB.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for e in entries:
        base = rules.for_entry(e).get("rom_root") or str(rom_root)
        key = os.path.normcase(base)
        if key in seen:
            continue
        seen.add(key)
        if not Path(base).is_dir():
            out.append((e.name, base))
    return out


def scan_roots(entries, rules: DirRules, rom_root, tosort=None) -> list[str]:
    """Katalogi, które MUSZĄ być przeskanowane: główny rom_root + KAŻDY
    katalog bazowy z reguły `rom_root` (bo tam realnie lądują pliki) + ToSort.

    Bez tego indeks nie widzi plików w katalogach wyprowadzonych regułą poza
    główny rom_root, a wpisy po plikach tam usuniętych zostają w bazie jako
    „obecne" (duchy) — matcher planuje wtedy przenosiny z nieistniejących
    ścieżek i naprawa nic nie robi.
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(p) -> None:
        if not p:
            return
        path = Path(p)
        key = os.path.normcase(str(path))
        if key in seen or not path.is_dir():
            return
        seen.add(key)
        out.append(str(path))

    add(rom_root)
    for e in entries:
        add(rules.for_entry(e).get("rom_root"))
    # ToSort: pojedyncza ścieżka albo LISTA katalogów (RomVault pozwala na wiele)
    if isinstance(tosort, (list, tuple, set)):
        for t in tosort:
            add(t)
    else:
        add(tosort)
    return out


class DirExists:
    """Istnienie katalogów z LISTINGU rodzica: jeden `scandir` na katalog
    nadrzędny (cache na czas zadania) zamiast `is_dir` per kandydat. Kandydatów
    jest ~3 na DAT (target, Redump, ES) × 600 DAT-ów, a rodziców kilka — na NAS
    to różnica minut ciszy („Analizuję rozmiary…", „Ustalam katalogi…")."""

    def __init__(self) -> None:
        self._kids: dict = {}

    def children(self, parent) -> Optional[dict]:
        """{normcase(nazwa): (nazwa, pełna ścieżka)} podkatalogów; None gdy
        rodzica nie ma / nieczytelny."""
        k = os.path.normcase(os.path.abspath(str(parent)))
        if k not in self._kids:
            try:
                with os.scandir(parent) as it:
                    self._kids[k] = {os.path.normcase(e.name): (e.name, e.path)
                                     for e in it if e.is_dir()}
            except OSError:
                self._kids[k] = None
        return self._kids[k]

    def is_dir(self, path) -> bool:
        p = Path(os.path.abspath(str(path)))
        if p.parent == p:                      # korzeń woluminu
            return p.is_dir()
        kids = self.children(p.parent)
        return kids is not None and os.path.normcase(p.name) in kids


def platform_scan_dirs(entries, rules: DirRules, rom_root,
                       dirs: Optional[DirExists] = None) -> list[str]:
    """Istniejące katalogi-kandydaci dla platform danych `entries`, w OBU
    znanych konwencjach nazw, cel SKONFIGUROWANY pierwszy:

      1) `entry.target_dir` — realny cel z reguł (naming/target),
      2) Redump: ``<rom_root>/<nazwa z nagłówka DAT-a>`` (płasko),
      3) EmulationStation: ``<rom_root>/<es-folder>`` (np. ps2, psx).

    Do PRIORYTETOWEGO skanu wybranej platformy: skanujemy te katalogi jako
    pierwsze, żeby wszystko lądowało w wybranym katalogu i — gdy platforma
    wyjdzie kompletna — nie trzeba szukać jej gdzie indziej. Kolejność =
    preferencja: gdy nie ma katalogu wybranej konwencji (np. „PS2"), ale jest
    drugiej („Sony - PlayStation 2"), użyty zostanie ten istniejący.
    """
    dirs = dirs or DirExists()
    out: list[str] = []
    seen: set[str] = set()

    def add(p) -> None:
        if not p:
            return
        path = Path(p)
        key = os.path.normcase(str(path))
        if key in seen or not dirs.is_dir(path):
            return
        seen.add(key)
        out.append(str(path))

    for e in entries:
        eff = rules.for_entry(e)
        base = Path(eff["rom_root"]) if eff.get("rom_root") else Path(rom_root)
        add(getattr(e, "target_dir", None))       # skonfigurowany cel (priorytet)
        add(base / folder_name(e, "dat"))          # Redump: <nazwa DAT-a> płasko
        add(base / folder_name(e, "es"))           # EmulationStation: es-folder
    return out


def platform_scan_roots(entries, rules: DirRules, rom_root, tosort=None,
                        dirs: Optional[DirExists] = None) -> list[str]:
    """Katalogi do skanu = katalogi WŁĄCZONYCH platform (obie konwencje,
    istniejące) + ToSort + nadpisania rom_root. NIE cały rom_root.

    Skanujemy tylko platformy, które użytkownik WŁĄCZYŁ (checkbox), więc pliki
    innych platform (np. RVZ GameCube/Wii przy wybranym PS1/PS2) nie są ruszane.
    Katalogi platform rozwiązuje `platform_scan_dirs` (target z reguł + Redump +
    EmulationStation) — dawny „skan całego rom_root" był potrzebny tylko dlatego,
    że skan używał wyłącznie nieistniejącego target=<nazwa DAT-a>; teraz realne
    katalogi (ps2/psx itd.) są znajdowane wprost, bez przemiatania obcych.
    """
    dirs = dirs or DirExists()
    out: list[str] = list(platform_scan_dirs(entries, rules, rom_root, dirs))
    seen: set[str] = {os.path.normcase(p) for p in out}

    def add(p) -> None:
        if not p:
            return
        path = Path(p)
        key = os.path.normcase(str(path))
        if key in seen or not dirs.is_dir(path):
            return
        seen.add(key)
        out.append(str(path))

    for e in entries:                       # własne rom_root-y dzieci (inny dysk)
        add(rules.for_entry(e).get("rom_root"))
    if isinstance(tosort, (list, tuple, set)):
        for t in tosort:
            add(t)
    else:
        add(tosort)
    return out


def stray_dirs(entries, rules: DirRules, rom_root,
               dirs: Optional[DirExists] = None) -> list[str]:
    """Foldery-SIEROTY pod rom_root: rodzeństwo zarządzanych platform, które NIE
    jest targetem/kandydatem (ES/Redump) ani przodkiem żadnego DAT-u.

    Folder OUTPUT DAT-u jest EDYTOWALNY i często różni się od nazwy z DAT-u — a to
    dalej ten sam DAT (np. Commodore 64 z output `c64`, a pliki leżą w starym
    `commodore64`). Takie foldery trzeba SKANOWAĆ, żeby DAT dopasował ich treść po
    sumach; naprawa przeniesie pliki do skonfigurowanego targetu (zwykły move), a
    to, co nie pasuje do ŻADNEGO DAT-u, dopiero wtedy trafia do ToSort.

    `entries` powinny być WSZYSTKIE odkryte (także wyłączone) — inaczej folder
    platformy tylko odznaczonej na ten przebieg zostałby uznany za sierotę.
    NIE schodzimy w target/kandydata ani w tier-przodka; katalogi pomocnicze i
    systemowe pomijamy."""
    ncase = os.path.normcase
    base = Path(os.path.abspath(str(rom_root)))
    base_n = ncase(str(base))
    managed: set[str] = set()
    anc_norm: set[str] = set()
    anc_paths: dict[str, Path] = {}
    for e in entries:
        eff = rules.for_entry(e)
        rbase = Path(eff["rom_root"]) if eff.get("rom_root") else base
        cands = []
        t = getattr(e, "target_dir", None)
        if t:
            cands.append(Path(os.path.abspath(str(t))))
        cands.append(rbase / folder_name(e, "dat"))
        cands.append(rbase / folder_name(e, "es"))
        for pp in cands:
            pp = Path(os.path.abspath(str(pp)))
            managed.add(ncase(str(pp)))
            for a in pp.parents:
                an = ncase(str(a))
                anc_norm.add(an)
                anc_paths.setdefault(an, a)
    SKIP = {"cues", "support files", "system", "$recycle.bin",
            "system volume information", "found.000"}
    parents = [p for an, p in anc_paths.items()
               if an == base_n or an.startswith(base_n.rstrip("\\/") + os.sep)]
    out: list[str] = []
    seen: set[str] = set()
    dirs = dirs or DirExists()
    for d in sorted(parents, key=lambda p: len(str(p))):
        kids = dirs.children(d)             # listing z cache (1 scandir)
        if kids is None:
            continue
        for _nk, (name, kpath) in kids.items():
            cn = ncase(os.path.abspath(kpath))
            if cn in managed or cn in anc_norm or cn == base_n or cn in seen:
                continue
            if name.lower() in SKIP:
                continue
            seen.add(cn)
            out.append(str(Path(os.path.abspath(kpath))))
    return out


def apply_rule_targets(entries, rules: DirRules, rom_root, log=None) -> None:
    """Wylicza katalog docelowy każdego DAT-a z reguł (kaskada global→
    katalog→DAT):

    - `rom_root` (rule) nadpisuje bazę (np. inny dysk dla dzieci);
    - `target` (rule) = pełne przekierowanie względem bazy;
    - inaczej: baza / <katalog DAT-a względem dat_root> / <nazwa systemu>,
      gdzie nazwa wg `naming` (dat/es). Struktura DatRoot ODZWIERCIEDLA się
      w rom_root dla OBU konwencji: `DatRoot/ROMS/x.dat` z naming=es →
      `<rom_root>/ROMS/<es-folder>` (np. Z:/ROMS/ROMS/atari2600),
      `DatRoot/1G1R/x.dat` → `<rom_root>/1G1R/<nazwa>`;
    - RĘCZNIE wybrany `rom_root` (reguła) = płasko: `<rom_root>/<nazwa>`.
    Ustawia też e.subdir_per_game.
    """
    from pathlib import Path

    from .datstore import effective_platform_key
    dat_root = rules.dat_root
    for e in entries:
        eff = rules.for_entry(e)
        base = Path(eff["rom_root"]) if eff.get("rom_root") else Path(rom_root)
        naming = eff.get("naming", "dat")
        if eff.get("target"):
            e.target_dir = base / eff["target"]
        elif eff.get("rom_root"):
            # RĘCZNIE wybrany rom_root (reguła) — ten katalog JEST już
            # rozdzieleniem, więc płasko: <rom_root>/<system>.
            e.target_dir = base / folder_name(e, naming)
        else:
            # Struktura katalogów DatRoot (ROMS/1G1R/[T-En]…) ODZWIERCIEDLA SIĘ
            # w rom_root — dla naming=dat i naming=es. Konwencja decyduje tylko
            # o nazwie LIŚCIA (ps2 vs „Sony - PlayStation 2"). Dawniej naming=es
            # układało płasko (<rom_root>/<system>), gubiąc katalog-grupę DAT-a:
            # DatRoot/ROMS lądował w Z:/ROMS/atari2600 zamiast Z:/ROMS/ROMS/atari2600.
            leaf = folder_name(e, naming)
            if log and naming == "es" and leaf == e.name:
                # brak mapowania ES => nazwa z DAT-a — GŁOŚNO, żeby mieszanina
                # konwencji nie była niespodzianką (dodaj alias w shortcuts.py)
                log(f"UWAGA naming=es: brak mapowania ES dla '{e.name}' — "
                    f"katalog dostanie nazwę z DAT-a")
            try:
                rel = e.dat_path.parent.relative_to(dat_root)
            except ValueError:
                rel = Path()
            e.target_dir = base / rel / leaf
        e.subdir_per_game = bool(eff.get("subdir_per_game", True))
        e.store_format = resolve_format(eff.get("format", "keep"), e)
        # FORMAT ZESTAWÓW ARCADE (split/merged/non-merged) — używany przez matcher
        # i rebuilder TYLKO dla DAT-ów z logiką parent/clone (sprawdzane tam po
        # entry.games). Cache nazw gier zerujemy — mógł być z innego formatu.
        e.arcade_format = str(eff.get("arcade_format", "split") or "split")
        for _attr in ("_game_names", "_game_by_name", "_is_arcade", "_arc_sig"):
            if hasattr(e, _attr):
                try:
                    delattr(e, _attr)
                except Exception:
                    pass

    # Format PER PLATFORMA: bierzemy JAWNĄ regułę formatu (folder/DAT)
    # KTÓREGOKOLWIEK DAT-a platformy — rodzic ma pierwszeństwo (entries są
    # parent-first). Dzięki temu ustawienie formatu na DOWOLNYM katalogu
    # platformy działa, a wszystkie DAT-y (rodzic+dzieci) dostają JEDEN, spójny
    # format (dzieci to symlinki do plików rodzica — ten sam kontener).
    platform_fmt: dict[str, str] = {}
    for e in entries:
        key = effective_platform_key(e, rules)        # z ręcznymi przypięciami
        exp = rules.explicit_rule(e, "format")        # None = brak reguły
        if key not in platform_fmt:
            platform_fmt[key] = resolve_format(exp, e) if exp else ""
        elif not platform_fmt[key] and exp:
            platform_fmt[key] = resolve_format(exp, e)  # format podaje dziecko
    for e in entries:
        fmt = platform_fmt.get(effective_platform_key(e, rules))
        if fmt:                                        # jawny format platformy
            e.store_format = fmt
        # inaczej zostaje wynik pierwszej pętli (brak reguły => keep)
        e._fmt_applied = True       # store_format = JEDYNE źródło formatu


def effective_format(entry, eff: dict) -> str:
    """Format DAT-u — TEN SAM dla matchera, rebuildera i konwersji.

    Po `apply_rule_targets` to `entry.store_format` (z formatem PER PLATFORMA:
    dziecko dziedziczy jawny format rodzica). Wyliczanie od nowa z reguły
    SAMEGO DAT-u (`resolve_format(eff["format"])`) dawało dzieciom INNY format:
    np. PSP PSN (Decrypted) z regułą „auto" → zip, a platforma PSP (ROMS\\psp)
    ma CHD → matcher szukał CHD i planował wypakowanie, a konwersja przepakowanie
    do zipa (130 gier: pobranie + kompresja + wysyłka zamiast przeniesienia).
    Bez `apply_rule_targets` (np. testy z samym rules_fn) — z reguły."""
    if getattr(entry, "_fmt_applied", False):
        return getattr(entry, "store_format", "keep") or "keep"
    return resolve_format((eff or {}).get("format", "keep"), entry)
