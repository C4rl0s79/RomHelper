"""Matcher: indeks plików × DAT-y => stan kolekcji (jak drzewo RomVaulta).

Dla każdego ROM-a z każdego DAT-a ustala status na podstawie indeksu
(bez czytania plików — wszystko z bazy):

- HAVE          — plik leży pod kanoniczną ścieżką (target_dir/nazwa z DAT-a);
- HAVE_CHD      — pod kanoniczną ścieżką (z rozszerzeniem .chd) leży CHD,
                  którego SHA-1 ZAWARTOŚCI zgadza się z DAT-em;
- WRONG_NAME    — właściwe dane są w katalogu DAT-a, ale pod złą nazwą;
- ELSEWHERE     — właściwe dane istnieją, ale w innym katalogu (źródło/ToSort
                  /inny DAT) — rebuilder przeniesie albo podlinkuje;
- MISSING       — brak trafienia w indeksie;
- NO_HASH       — wpis DAT-a nie ma żadnego hasha (nie da się dopasować).

Dopasowanie: SHA-1 -> MD5 -> (CRC32 + rozmiar). Trafienie może też paść
WEWNĄTRZ archiwum ZIP (member != "") — rebuilder wtedy wypakowuje
z weryfikacją SHA-1. Luźne pliki mają pierwszeństwo przed archiwami.
Dla plików .chd liczy się także data_sha1 (zawartość) — tak CHD DVD/HD
trafia w Redump bez ekstrakcji.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence

from .datfile import DatRom
from .datstore import DatEntry
from .fileindex import FileIndex
from .models import MediaType


class RomState(Enum):
    HAVE = "have"
    HAVE_CHD = "have_chd"
    WRONG_NAME = "wrong_name"
    ELSEWHERE = "elsewhere"
    CREATABLE = "creatable"     # pusty plik-znacznik (size=0, np. .msu) — nie ma
                                # go na miejscu, ale rebuilder go trywialnie
                                # tworzy: liczymy jak „do naprawy", nie „brak"
    MISSING = "missing"
    NO_HASH = "no_hash"


@dataclass
class RomStatus:
    entry: DatEntry
    game: str
    rom: DatRom
    state: RomState
    source_path: str = ""       # skąd można wziąć dane (dla wrong_name/elsewhere)
    via_chd: bool = False       # gra zaspokojona przez plik .chd (cała gra!)
    via_archive: bool = False   # cała gra w jednym archiwum <gra>.zip/7z (kartridż)
    member: str = ""            # nazwa pliku WEWNĄTRZ archiwum source_path
    canonical_override: str = ""  # via_chd/archiwum: wspólna ścieżka gry
    game_multi: bool = False    # gra wieloplikowa (CD bin/cue) => podkatalog
    archive_names_ok: bool = True  # via_archive: nazwy WEWN. zgodne z DAT-em
                                   # (False => przepakuj z poprawnymi nazwami)
    archive_superset: bool = False  # źródłowe archiwum ma WIĘCEJ plików niż gra
                                    # (np. MAME merged set: parent+klony) =>
                                    # NIE przenosić całości, tylko WYPAKOWAĆ
                                    # potrzebne ROM-y; źródła NIE kasować
    is_translation: bool = False    # slot SPEŁNIONY świadomą podmianą na
                                    # tłumaczenie (translations.json) — GUI 🌐
    bad_container: bool = False     # CHD ma ZŁY kontener vs medium DAT (np. gra
                                    # DVD zrobiona jako CD) — „do naprawy",
                                    # naprawia „Odbuduj CHD wg cue"
    bad_zip_method: bool = False    # ZIP użył metody != store/deflate (zstd/lzma)
                                    # — niezgodne z emulatorami → „do naprawy"
                                    # (naprawa przepakuje na deflate)

    @property
    def canonical_path(self) -> Path:
        """Docelowa ścieżka pliku wg DAT-a.

        Układ jak w praktyce kolekcjonerskiej: gra WIELOPLIKOWA (CD: biny+cue)
        dostaje własny podkatalog <gra>/, jednoplikowa (kartridż, iso) i CHD
        leżą płasko w katalogu DAT-a.
        """
        if self.canonical_override:
            return Path(self.canonical_override)
        if self.game_multi:
            return self.entry.target_dir / self.game / self.rom.name
        return self.entry.target_dir / self.rom.name


@dataclass
class DatReport:
    entry: DatEntry
    statuses: list[RomStatus] = field(default_factory=list)

    def count(self, *states: RomState) -> int:
        return sum(1 for s in self.statuses if s.state in states)

    @property
    def total(self) -> int:
        return len(self.statuses)

    def game_stats(self) -> tuple[int, int, int, int]:
        """Statystyki na poziomie GRY (spójne z listą gier w GUI):
        (wszystkie, komplet, do_naprawy, brak).

        Stan gry = najgorszy stan jej ROM-ów: komplet gdy wszystkie na
        miejscu; do naprawy gdy wszystkie obecne, ale któryś nie na miejscu;
        brak gdy choć jednego brakuje. To eliminuje mylące liczenie
        pojedynczych współdzielonych ścieżek (audio/cisza) gier, których i
        tak nie da się skompletować."""
        rank = {RomState.MISSING: 3, RomState.NO_HASH: 3,
                RomState.WRONG_NAME: 2, RomState.ELSEWHERE: 2,
                RomState.CREATABLE: 2,
                RomState.HAVE: 1, RomState.HAVE_CHD: 1}
        worst: dict[str, RomState] = {}
        for s in self.statuses:
            cur = worst.get(s.game)
            if cur is None or rank[s.state] > rank[cur]:
                worst[s.game] = s.state
        complete = fix = miss = 0
        for st in worst.values():
            if st in (RomState.HAVE, RomState.HAVE_CHD):
                complete += 1
            elif st in (RomState.WRONG_NAME, RomState.ELSEWHERE,
                        RomState.CREATABLE):
                fix += 1
            else:
                miss += 1
        return len(worst), complete, fix, miss

    def summary(self) -> str:
        total, complete, fix, miss = self.game_stats()
        pct = (complete / total * 100) if total else 0.0
        return (f"gry: {complete}/{total} ({pct:.1f}%), do naprawy {fix}, "
                f"brak {miss}")


def game_stats_from_states(game_states: dict) -> tuple[int, int, int, int]:
    """(wszystkie, komplet, do_naprawy, brak) z mapy {gra: {rom: RomState}}.
    Wspólne dla żywego raportu i wczytanego cache."""
    rank = {RomState.MISSING: 3, RomState.NO_HASH: 3,
            RomState.WRONG_NAME: 2, RomState.ELSEWHERE: 2,
            RomState.CREATABLE: 2,
            RomState.HAVE: 1, RomState.HAVE_CHD: 1}
    complete = fix = miss = 0
    for roms in game_states.values():
        worst = max(roms.values(), key=lambda st: rank[st])
        if worst in (RomState.HAVE, RomState.HAVE_CHD):
            complete += 1
        elif worst in (RomState.WRONG_NAME, RomState.ELSEWHERE,
                       RomState.CREATABLE):
            fix += 1
        else:
            miss += 1
    return len(game_states), complete, fix, miss


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(a) == os.path.normcase(b)


def _link_satisfies(canonical, src: str, index: "FileIndex | None" = None) -> bool:
    """Czy ścieżka kanoniczna to POPRAWNY symlink na znalezioną kopię
    fizyczną `src`? Wtedy gra DZIECKA jest na miejscu (HAVE), a nie „do
    naprawy" — dokładnie tak dzieci mają wyglądać po naprawie.

    `index` (świeżo po skanie) pozwala UNIKNĄĆ rundy SMB: jeśli indeks nie zna
    ścieżki kanonicznej jako ISTNIEJĄCEGO LINKU, nie może ona być spełniającym
    linkiem → False bez dotykania dysku. Przy przenoszeniu z ToSort kanoniczny
    plik zwykle jeszcze nie istnieje, więc tu kończymy — to zdejmuje ~jedną
    rundę SMB z KAŻDEJ gry w podglądzie naprawy (na NAS = z minut na sekundy)."""
    c = str(canonical)
    if index is not None:
        row = index.lookup(c)
        if row is None or row["missing"] or not row["is_link"]:
            return False
    try:
        if not os.path.islink(c):
            return False
        target = os.readlink(c)
    except OSError:
        return False
    if not os.path.isabs(target):
        target = os.path.join(os.path.dirname(c), target)
    # \\?\ prefix z mklink — znormalizuj przed porównaniem
    target = target.replace("\\\\?\\", "")
    src = str(src).replace("\\\\?\\", "")
    return _same_path(os.path.abspath(target), os.path.abspath(src)) \
        and os.path.exists(src)


def _row_full_match(row, rom) -> bool:
    """WSZYSTKIE sumy podane w DAT-cie muszą się zgadzać z wpisem indeksu
    (rozmiar, CRC32, MD5, SHA-1) — nie tylko najsilniejsza. Pola puste po
    którejkolwiek stronie nie blokują (np. członek archiwum przy szybkim
    skanie nie ma jeszcze MD5)."""
    try:
        if rom.size and row["size"] and row["size"] != rom.size:
            return False
        if rom.crc and row["crc32"] and \
                row["crc32"] != rom.crc.lower().zfill(8):
            return False
        if rom.md5 and row["md5"] and row["md5"] != rom.md5.lower():
            return False
        if rom.sha1 and row["sha1"] and row["sha1"] != rom.sha1.lower():
            return False
    except (KeyError, IndexError):
        return True
    return True


def _pick(rows: Sequence, canonical: Path, target_dir: Path):
    """Wybiera najlepszego kandydata: kanoniczny > w katalogu DAT-a > inny."""
    canon = str(canonical)
    tprefix = os.path.normcase(str(target_dir)).rstrip("\\/") + os.sep
    in_dir = None
    other = None
    for r in rows:
        if r["is_link"]:
            continue  # link nie jest kopią fizyczną
        if _same_path(r["path"], canon):
            return r, "canonical"
        if os.path.normcase(r["path"]).startswith(tprefix):
            in_dir = in_dir or r
        else:
            other = other or r
    if in_dir is not None:
        return in_dir, "in_dir"
    if other is not None:
        return other, "other"
    return None, ""


def match_rom(entry: DatEntry, game: str, rom: DatRom, index: FileIndex,
              game_multi: bool = False, game_single: bool = False) -> RomStatus:
    """Status pojedynczego ROM-a z DAT-a względem indeksu (bez CHD —
    dopasowanie CHD jest na poziomie GRY, patrz match_game).

    game_multi — gra wieloplikowa luzem => podkatalog per gra.
    game_single — gra ma DOKŁADNIE jeden ROM (akceptujemy jej plik także w
    podfolderze <target>/<gra>/<rom>, nie tylko płasko)."""
    # PUSTY plik-znacznik (np. .msu w MSU-1: size=0, crc="-"): brak sum, ale
    # trywialnie odtwarzalny — 0 bajtów ma zawsze tę samą treść. HAVE, gdy leży
    # na miejscu; inaczej CREATABLE (rebuilder utworzy pusty plik). CREATABLE
    # liczy się jak „do naprawy", nie „brak" — bez tego gry MSU-1 (każda ma .msu)
    # miały wieczne „brak", choć wszystkie realne pliki są.
    if (rom.size or 0) == 0 and not rom.sha1 and not rom.md5:
        status = RomStatus(entry, game, rom, RomState.CREATABLE,
                           game_multi=game_multi)
        try:
            canon = status.canonical_path
            if os.path.isfile(canon) and os.path.getsize(canon) == 0:
                status.state = RomState.HAVE
                status.source_path = str(canon)
        except OSError:
            pass
        return status
    rows: list = []
    if rom.sha1:
        rows = index.find_sha1(rom.sha1, include_chd_content=False)
    if not rows and rom.md5:
        rows = index.find_md5(rom.md5)
    if not rows and rom.crc and rom.size:
        rows = index.find_crc(rom.crc, rom.size)
    if not rows and not (rom.sha1 or rom.md5 or rom.crc):
        return RomStatus(entry, game, rom, RomState.NO_HASH,
                         game_multi=game_multi)

    direct = [r for r in rows if (rom.sha1 and r["sha1"] == rom.sha1.lower())
              or (not rom.sha1 and r["sha1"])]
    if not direct and not (rom.sha1 or rom.md5):
        direct = list(rows)   # dopasowanie tylko po CRC+rozmiar
    if not direct and rom.md5:
        direct = [r for r in rows if r["md5"] == rom.md5.lower()]
    # WSZYSTKIE sumy z DAT-a muszą się zgadzać, nie tylko ta, po której
    # szukaliśmy — plik z poprawnym SHA-1 ale złym rozmiarem/CRC odpada
    direct = [r for r in direct if _row_full_match(r, rom)]

    status = RomStatus(entry, game, rom, RomState.MISSING,
                       game_multi=game_multi)
    if direct:
        row, kind = _pick(direct, status.canonical_path, entry.target_dir)
        if row is not None:
            status.source_path = row["path"]
            status.state = {"canonical": RomState.HAVE,
                            "in_dir": RomState.WRONG_NAME,
                            "other": RomState.ELSEWHERE}[kind]
            # PODFOLDER PER GRA (gra JEDNOPLIKOWA): plik w katalogu nazwanym
            # DOKŁADNIE jak gra (<target>/<gra>/<rom>) to POPRAWNY układ (jak w
            # RomVaulcie) — nie „zła nazwa". Bez tego całe kolekcje trzymane w
            # podfolderach (np. 610 RVZ GameCube w <gra>/<gra>.rvz) świeciły na
            # WRONG_NAME i szły do konwersji, choć pliki są poprawne. Treść
            # ważna, nie ścieżka. Gry WIELOPLIKOWE mają układ sterowany regułą
            # subdir_per_game (płaski vs podfolder) — ich tu nie ruszamy.
            if status.state == RomState.WRONG_NAME and game_single:
                sub = entry.target_dir / game / rom.name
                if _same_path(row["path"], str(sub)):
                    status.state = RomState.HAVE
            # kanoniczna ścieżka jest już POPRAWNYM linkiem na tę kopię
            # (typowy stan DZIECKA po naprawie) => na miejscu, nie „napraw"
            if (status.state != RomState.HAVE
                    and _link_satisfies(status.canonical_path, row["path"], index)):
                status.state = RomState.HAVE
            return status

    # trafienie wewnątrz archiwum (SHA-1, potem CRC32+rozmiar z ZIP-a) —
    # też z wymogiem zgodności WSZYSTKICH dostępnych sum
    mrows: list = []
    if rom.sha1:
        mrows = [r for r in index.find_member_sha1(rom.sha1)
                 if _row_full_match(r, rom)]
    if not mrows and rom.crc and rom.size:
        mrows = [r for r in index.find_member_crc(rom.crc, rom.size)
                 if _row_full_match(r, rom)]
    if mrows:
        status.source_path = mrows[0]["archive"]
        status.member = mrows[0]["name"]
        status.state = RomState.ELSEWHERE
    return status


def _under(path: str, target_dir) -> bool:
    """Czy `path` leży w katalogu docelowym (bezpośrednio lub w podkatalogu)."""
    return os.path.normcase(path).startswith(
        os.path.normcase(str(target_dir)).rstrip("\\/") + os.sep)


def _archives_with_game(game, index: FileIndex) -> dict:
    """{ścieżka_archiwum: {rom_idx: nazwa_członka}} — archiwa (zip/7z) zawierające
    ROM-y gry (trafienie SHA-1, potem CRC32+rozmiar). Do formatu kartridżowego,
    gdzie CAŁA gra siedzi w jednym pliku <gra>.zip."""
    per: dict[str, dict[int, str]] = {}
    for i, rom in enumerate(game.roms):
        rows: list = []
        if rom.sha1:
            rows = index.find_member_sha1(rom.sha1)
        if not rows and rom.crc and rom.size:
            rows = index.find_member_crc(rom.crc, rom.size)
        for r in rows:
            if _row_full_match(r, rom):     # KOMPLET sum, nie jedna
                per.setdefault(r["archive"], {})[i] = r["name"]
    return per


def _match_game_archive(entry, game, index: FileIndex, want_ext, allow_move):
    """Format kartridżowy: cała gra przechowywana jako jedno archiwum
    ``<gra>.zip`` (albo .7z). Zwraca statusy albo None (matcher spróbuje wtedy
    luźnych plików / wypakowania / CHD).

    - archiwum w KATALOGU DOCELOWYM => HAVE (zielone; NIE wypakowujemy —
      to JEST docelowy format, wbrew nazwie .iso/.n64 z DAT-a);
    - archiwum gdzie indziej (ToSort/inny DAT), gdy `allow_move` (format
      jawnie zip/7z) => ELSEWHERE: przenieś CAŁE archiwum, nie wypakowuj.
      Dla „keep" zwracamy None — niech zadziała stara ścieżka wypakowania.
    """
    need = set(range(len(game.roms)))
    per = _archives_with_game(game, index)          # {archiwum: {rom_idx: nazwa}}
    full = [(a, m) for a, m in per.items() if need <= set(m)]
    if not full:
        return None

    def _names_ok(members: dict) -> bool:
        # nazwa WEWNĄTRZ archiwum musi zgadzać się z nazwą ROM-a z DAT-a
        return all(members.get(i, "") == game.roms[i].name for i in need)

    def _superset(archive: str) -> bool:
        # archiwum ma WIĘCEJ plików niż gra potrzebuje (np. MAME merged set:
        # parent + klony w podfolderach). Wtedy NIE wolno przenieść/skasować
        # całości — trzeba WYPAKOWAĆ tylko ROM-y gry, źródło zostawić.
        try:
            n = index._db.execute(
                "SELECT COUNT(*) FROM members WHERE archive=?",
                (archive,)).fetchone()[0]
        except Exception:
            return False
        return n > len(game.roms)

    def _mk(archive, members, state, canonical, names_ok, superset=False,
            bad_zip=False):
        return [RomStatus(entry, game.name, rom, state, source_path=archive,
                          member=members.get(i, ""), via_archive=True,
                          canonical_override=canonical, archive_names_ok=names_ok,
                          archive_superset=superset, bad_zip_method=bad_zip)
                for i, rom in enumerate(game.roms)]

    def _bad_zip(archive: str) -> bool:
        # ZŁA metoda kompresji ZIP (zstd/lzma) — skan zapisał to w indeksie
        # (tanio, z centralnego katalogu). Emulatory takich nie czytają → repack.
        if not archive.lower().endswith(".zip"):
            return False
        try:
            r = index.lookup(archive)
            return bool(r is not None and "bad_zip_method" in r.keys()
                        and r["bad_zip_method"] == 1)
        except Exception:
            return False

    in_dir = [(a, m) for a, m in full if _under(a, entry.target_dir)]
    if in_dir:
        in_dir.sort(key=lambda am: (0 if _names_ok(am[1]) else 1, am[0].lower()))
        archive, members = in_dir[0]
        sup = _superset(archive)
        if _names_ok(members) and not sup:
            # w katalogu docelowym + poprawne nazwy + DOKŁADNY zestaw => zielone,
            # CHYBA że ZIP ma złą metodę kompresji (zstd/lzma) → „do naprawy"
            # (repack na deflate w miejscu; treść OK, tylko kontener niezgodny).
            if _bad_zip(archive):
                return _mk(archive, members, RomState.WRONG_NAME, archive,
                           True, bad_zip=True)
            return _mk(archive, members, RomState.HAVE, archive, True)
        # złe nazwy ALBO nadzbiór (merged) => PRZEPAKUJ tylko ROM-y gry (naprawa)
        ext = want_ext or (Path(archive).suffix.lstrip(".").lower() or "zip")
        canonical = str(entry.target_dir / f"{game.name}.{ext}")
        return _mk(archive, members, RomState.WRONG_NAME, canonical, False,
                   superset=sup)
    if not allow_move:
        return None
    full.sort(key=lambda am: (0 if _names_ok(am[1]) else 1, am[0].lower()))
    archive, members = full[0]
    sup = _superset(archive)
    ext = want_ext or (Path(archive).suffix.lstrip(".").lower() or "zip")
    canonical = str(entry.target_dir / f"{game.name}.{ext}")
    # kanoniczny zip DZIECKA jest już poprawnym linkiem na archiwum rodzica
    if _link_satisfies(canonical, archive, index):
        return _mk(archive, members, RomState.HAVE, canonical,
                   _names_ok(members), superset=sup)
    return _mk(archive, members, RomState.ELSEWHERE, canonical,
               _names_ok(members), superset=sup)


def _find_game_chd(game, index: FileIndex):
    """Szuka pliku .chd, którego zawartość odpowiada CAŁEJ grze.

    Porównanie po ODCISKU KOMPLETU ścieżek (game_profile): gra DVD = SHA-1
    obrazu iso; gra CD wielościeżkowa = syntetyczny hash WSZYSTKICH sum.
    Pojedyncza ścieżka NIE wystarcza — wydania (1S/5S) dzielą ścieżkę danych
    i różnią się tylko audio; dopasowanie po jednej sumie robiło fałszywe
    linki między różnymi zrzutami."""
    from .datfile import game_profile
    profile = game_profile(game.data_roms)
    if not profile:
        return None
    for r in index.find_sha1(profile, include_chd_content=True):
        if (not r["is_link"] and r["path"].lower().endswith(".chd")
                and r["data_sha1"] == profile.lower()):
            return r
    return None


def match_game(entry: DatEntry, game, index: FileIndex,
               subs: Optional[dict] = None) -> list[RomStatus]:
    """Statusy wszystkich ROM-ów gry, ŚWIADOME formatu przechowywania.

    Kluczowe: format docelowy (``entry.store_format``) NADPISuje rozszerzenia
    z DAT-a. Gra kartridżowa trzymana jako ``<gra>.zip`` jest POPRAWNA (zielona),
    a nie „do wypakowania"; gra płytowa jako ``<gra>.chd`` jest poprawna wbrew
    temu, że DAT wymienia .iso/.bin. Kolejność rozpoznania:

    1. luźne pliki pod kanoniczną nazwą (HAVE) — najszybsze;
    2. format kartridżowy: cała gra w jednym archiwum <gra>.zip/7z;
    3. format płytowy: cała gra w jednym .chd (data_sha1);
    4. w ostateczności luźne/członkowie archiwum (przenieś/wypakuj).

    Układ: gra WIELOPLIKOWA luzem (bin/cue, gdi+tracki) dostaje podkatalog
    per gra (gdy entry.subdir_per_game); CHD i archiwa są płasko.
    """
    multi = len(game.roms) > 1 and getattr(entry, "subdir_per_game", True)
    single = len(game.roms) == 1
    statuses = [match_rom(entry, game.name, rom, index, game_multi=multi,
                          game_single=single)
                for rom in game.roms]

    # PODMIANA na TŁUMACZENIE (translations.json = źródło prawdy): gra ma
    # zapisany wybór → slot pod NAZWĄ KANONICZNĄ jest SPEŁNIONY przez wariant,
    # mimo że jego treść ≠ sumy z podstawowego DAT-u. Bez tego skan cofałby
    # świadomą podmianę. V1: gry jednoplikowe (jeden ROM danych).
    if subs:
        from .translations import (sub_key, game_forms, link_form_mismatch,
                                   slot_path)
        rec = subs.get(sub_key(entry.name, game.name))
        if rec:
            data_sts = [s for s in statuses
                        if not s.rom.name.lower().endswith((".cue", ".gdi"))]
            if len(data_sts) == 1:
                base = data_sts[0].canonical_path
                fmt_t = getattr(entry, "store_format", "keep") or "keep"
                if fmt_t != "keep":
                    # Twardo wg ustawienia katalogu: katalog `zip` = `<gra>.zip`.
                    canonical = slot_path(base, base, game.name, fmt_t)
                else:
                    forms = game_forms(base, game.name)
                    canonical = next((f for f in forms if os.path.islink(f)),
                                     next((f for f in forms if os.path.exists(f)), base))
                # Stara podmiana: link `.rom` → archiwum `.zip`. Emulator tego
                # nie otworzy, a oryginał w innej formie zostaje obok — to NIE
                # jest spełniona podmiana (GUI pokaże grę bez 🌐, do ponowienia).
                form_ok = not (os.path.islink(canonical) and link_form_mismatch(canonical))
                # NIE ufaj samemu istnieniu wpisu: WISZĄCY symlink (skasowany
                # cel tłumaczenia) albo OBCY plik pod kanoniczną nazwą dawałyby
                # fałszywe „komplet". Wymagamy, by CEL istniał (os.path.exists
                # podąża za linkiem → False dla wiszącego), a gdy indeks zna
                # treść — by zgadzała się z zapisanym wyborem (rec["sha1"]).
                want = (rec.get("sha1") or "").lower()
                have = set()             # znane sumy slotu (plik + członek archiwum)
                if index is not None:
                    try:
                        orow = index.lookup(canonical)
                    except Exception:
                        orow = None
                    if orow is not None and not orow["missing"]:
                        have.add((orow["sha1"] or "").lower())
                        if not orow["sha1"] and orow["is_link"]:
                            try:
                                trow = index.lookup(
                                    Path(os.path.realpath(canonical)))
                                have.add((trow["sha1"] or "").lower()
                                         if trow else "")
                            except Exception:
                                pass
                    # Slot-archiwum: wybór zapisany jest sumą ROM-u W ŚRODKU, a
                    # suma całego pliku to suma kontenera — porównujemy obie.
                    if canonical.suffix.lower() in (".zip", ".7z"):
                        try:
                            mem = index.members_of(Path(os.path.realpath(canonical)))
                        except Exception:
                            mem = []
                        if len(mem) == 1:
                            have.add((mem[0]["sha1"] or "").lower())
                have.discard("")
                if (form_ok and os.path.exists(canonical)
                        and not (want and have and want not in have)):
                    for s in statuses:
                        s.state = RomState.HAVE
                        s.is_translation = True
                    return statuses

    if all(s.state == RomState.HAVE for s in statuses):
        return statuses                       # luźne pliki już na miejscu

    fmt = getattr(entry, "store_format", "keep")
    # (2) kartridż: cała gra jako jedno archiwum. Dla „keep" też akceptujemy
    # archiwum w katalogu docelowym (nie wymuszamy wypakowania).
    if fmt in ("zip", "7z", "keep"):
        want = fmt if fmt in ("zip", "7z") else None
        arc = _match_game_archive(entry, game, index, want,
                                  allow_move=fmt in ("zip", "7z"))
        if arc is not None:
            return arc

    # (3) format PŁYTOWY (chd/rvz): CHD ma PIERWSZEŃSTWO nad luźnymi ścieżkami.
    # Bez tego DZIECKO (np. 1G1R), znajdując komplet luźnych ścieżek w ToSort
    # ZIP-ie, wypakowywałoby je FIZYCZNIE do swojego katalogu — zamiast zrobić
    # LINK do CHD rodzica. Gdy CHD (rodzica albo własny) istnieje → via_chd.
    chd_row = _find_game_chd(game, index) if fmt in ("chd", "rvz") else None

    complete = all(s.state not in (RomState.MISSING, RomState.NO_HASH)
                   for s in statuses)
    if chd_row is None:
        if complete:
            return statuses                 # luźne/member: przenieś/wypakuj/konwertuj
        chd_row = _find_game_chd(game, index)   # ostatnia szansa (niekompletne)
        if chd_row is None:
            return statuses
    canonical = entry.target_dir / f"{game.name}.chd"
    src = chd_row["path"]
    if _same_path(src, str(canonical)) or _link_satisfies(canonical, src, index):
        state = RomState.HAVE_CHD
    elif os.path.normcase(src).startswith(
            os.path.normcase(str(entry.target_dir)).rstrip("\\/") + os.sep):
        state = RomState.WRONG_NAME
    else:
        state = RomState.ELSEWHERE
    # ZŁY KONTENER (np. gra DVD spakowana jako CD): treść się zgadza, więc bez
    # tego byłby „komplet" — ale w emulatorze nie ruszy. Degradujemy do „do
    # naprawy"; naprawia „Odbuduj CHD wg cue" (rebuild_bad_chds, CD→DVD).
    bad_cont = False
    try:
        bad_cont = ("bad_container" in chd_row.keys()
                    and chd_row["bad_container"] == 1)
    except Exception:
        bad_cont = False
    if bad_cont and state == RomState.HAVE_CHD:
        state = RomState.WRONG_NAME
    for s in statuses:
        s.state = state
        s.via_chd = True
        s.member = ""
        s.source_path = src
        s.canonical_override = str(canonical)
        s.bad_container = bad_cont
    return statuses


def match_entry(entry: DatEntry, index: FileIndex,
                subs: Optional[dict] = None) -> DatReport:
    entry.load()
    report = DatReport(entry)
    for game in entry.games:
        report.statuses.extend(match_game(entry, game, index, subs))
    return report


def match_store(entries: Sequence[DatEntry], index: FileIndex,
                log: Optional[callable] = None,
                subs: Optional[dict] = None) -> list[DatReport]:
    """`subs` — mapa podmian na tłumaczenia (klucz `sub_key(dat,gra)` → wpis);
    zwykle `TranslationStore._subs`. Gry z wpisem są SPEŁNIONE tłumaczeniem."""
    reports = []
    for e in entries:
        if log:
            log(f"DAT: {e.name}")
        reports.append(match_entry(e, index, subs))
    return reports


def deep_probe_chds(
    index: FileIndex,
    entries: Sequence[DatEntry],
    chd,                        # CHDMan
    *,
    roots: Sequence[str | Path],
    work_dir: Optional[Path] = None,
    log: Optional[callable] = None,
    cancel_event=None,
    on_progress: Optional[callable] = None,   # (done, total, tekst) — OGÓLNY
    detail: Optional[callable] = None,        # (done, total, tekst) — SZCZEGÓŁ
    slot_progress: Optional[callable] = None,  # (slot, done, total, tekst) — RÓWNOLEGŁY
    scratch_fallback: Optional[str] = None,   # dedykowany temp z ustawień
    workers: int = 1,                         # równoległość TANIEGO nagłówka (chd.info)
    deep_workers: int = 1,                     # GÓRNY limit równoległych ekstrakcji
    deep_budget: int = 0,                      # budżet RAM (B) na scratch — 0=bez
) -> int:
    """Identyfikuje pliki .chd względem DAT-ów i zapisuje wynik do indeksu.

    Dwustopniowo, per plik bez trafienia:
    1. TANIO — SHA-1 zawartości z nagłówka CHD (chdman info): trafia DVD
       (createdvd: data_sha1 == SHA-1 obrazu .iso).
    2. DROGO — deep_identify z chd_buddy: ekstrakcja kolejnymi metodami
       (extractdvd / extractcd+deframe dla DVD-spakowanych-jako-CD /
       surowe ścieżki CD / hd / raw / ld), aż wynik trafi w DAT.
       Obsługuje więc gry CD (bin/cue) i błędnie spakowane CHD.

    Wynik ląduje w files.data_sha1 — kosztowna ekstrakcja liczy się RAZ,
    a matcher widzi CHD jak zwykłe trafienie (cała gra).
    """
    from .datfile import DatIndex
    from .deepcheck import deep_identify

    def _log(m: str) -> None:
        if log:
            log(m)

    merged = DatIndex()
    for e in entries:
        for g in e.load().games:
            merged.add_game(g)
    # UZNAJEMY tylko ODCISK CAŁEJ GRY (komplet ścieżek). Stare wpisy z sumą
    # pojedynczej ścieżki wypadają z „known" i zostaną zidentyfikowane od
    # nowa — konieczne, bo jedna ścieżka nie odróżnia wydań (1S vs 5S).
    known = merged.by_profile

    identified = 0
    seen: set[str] = set()

    def _flag_container(pth, chd_info, media) -> None:
        """Zapisz, czy KONTENER CHD zgadza się z medium gry w DAT (createcd vs
        createdvd). Tani — z nagłówka (bez ekstrakcji). Niepewne → 0 (nie strasz)."""
        try:
            if chd_info is None or media is None:
                index.set_bad_container(pth, 0)
                return
            dm = chd_info.detected_media
            if dm == MediaType.UNKNOWN or media == MediaType.UNKNOWN:
                index.set_bad_container(pth, 0)
                return
            index.set_bad_container(pth, 1 if dm != media else 0)
        except Exception:
            pass

    # 1. PASS: zbierz kandydatów (CHD bez identyfikacji, nie deep_fail-stale) —
    #    żeby pasek OGÓLNY pokazał realny licznik „X/Y", a nie stał na 0/0.
    candidates: list = []
    for root in roots:
        if not root or not Path(root).is_dir():
            continue
        for row in index.all_under(root):
            p = row["path"]
            key = os.path.normcase(p)
            if key in seen or not p.lower().endswith(".chd"):
                continue
            seen.add(key)
            if row["data_sha1"] and row["data_sha1"] in known:
                # zidentyfikowany po TREŚCI; ale jeśli KONTENER jeszcze
                # niesprawdzony (bad_container=-1) — dołóż na TANI check
                # (bez ekstrakcji), żeby wykryć np. DVD zrobione jako CD.
                bc = row["bad_container"] if "bad_container" in row.keys() else 0
                if bc != -1:
                    continue
            # PORAŻKA TEŻ JEST WYNIKIEM: plik już przeszedł głęboką
            # identyfikację bez dopasowania i się NIE ZMIENIŁ => nie mielimy
            # go ponownie co skan. Ponowną próbę wymusza pełny skan katalogu.
            try:
                deep_fail = row["deep_fail"]
            except (KeyError, IndexError):
                deep_fail = 0
            if deep_fail and deep_fail == row["mtime_ns"]:
                continue
            if Path(p).is_file():
                candidates.append(row)
    total_cand = len(candidates) or 1
    if candidates:
        # SKĄD są pliki: bez tego log podawał same nazwy i nie było wiadomo,
        # który katalog jest przemiatany.
        per_dir: dict = {}
        for row in candidates:
            d = str(Path(row["path"]).parent)
            per_dir[d] = per_dir.get(d, 0) + 1
        _log(f"CHD do sprawdzenia: {len(candidates)} w {len(per_dir)} katalogach "
             f"(DAT-y: {', '.join(e.name for e in entries[:5])}"
             f"{' …' if len(entries) > 5 else ''})")
        for d, n in sorted(per_dir.items(), key=lambda kv: -kv[1])[:15]:
            _log(f"  {n:5}  {d}")
        if len(per_dir) > 15:
            _log(f"  … i {len(per_dir) - 15} innych katalogów")

    # 2. PASS: identyfikacja RÓWNOLEGŁA. Odczyt/ekstrakcja CHD to I/O na NAS +
    #    dekompresja (chdman) — POJEDYNCZY strumień nie wysyca ani łącza (SMB
    #    latencja round-tripów), ani CPU (dekompresja czeka na I/O). Pula wątków
    #    czyta/wypakowuje kilka CHD naraz → kilka strumieni wypełnia łącze, a
    #    dekompresja nakłada się na I/O. ZAPISY DO INDEKSU (SQLite jednowątkowy)
    #    idą WYŁĄCZNIE w wątku wołającym — wątki tylko liczą i zwracają wynik.
    #    Dwustopniowo: (A) TANI nagłówek (chd.info) mocno równolegle (RAM≈0),
    #    (B) GŁĘBOKA ekstrakcja mniej równolegle (każda wypakowuje pełny obraz
    #    na scratch/RAM-dysk → limit `deep_workers` chroni przed zapchaniem).
    import queue as _queue
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from .scratch import pick_scratch_root

    n_head = max(1, int(workers))
    n_deep = max(1, int(deep_workers))
    done = 0
    need_deep: list = []                       # [(row, info)] — nagłówek nie trafił
    scratch_lock = threading.Lock()            # serializuje wybór/remount scratchu
    # BUDŻET RAM na scratch: zamiast sztywnej liczby wątków rezerwujemy tyle, ile
    # ekstrakcja REALNIE potrzebuje (~2 GB gra CD, ~9 GB DVD). Dla małych gier
    # zmieści się ich WIĘCEJ naraz (więcej strumieni z NAS = wyżej LAN), dla
    # dużych zejdzie samo — bez przekraczania fizycznego RAM-u. 0 = bez budżetu
    # (tylko limit `deep_workers`).
    budget_total = int(deep_budget) if deep_budget and deep_budget > 0 else 0
    budget = {"free": budget_total}
    budget_cond = threading.Condition()

    head_done = 0
    deep_total = 0

    def _head_tick(name: str) -> None:
        # postęp FAZY NAGŁÓWKÓW (chd.info na każdym kandydacie) — bez tego przy
        # dużej kolekcji CHD, gdy nic nie trafia nagłówkiem (np. PS2-jako-CD nie
        # pasuje do DVD-DAT → wszystko idzie w deep), GUI „stało" minutami z
        # dyskami NAS na maxa, choć realnie trwał odczyt nagłówków.
        nonlocal head_done
        head_done += 1
        if on_progress is not None:
            on_progress(head_done, total_cand,
                        f"nagłówki CHD ({head_done}/{total_cand}): {name}")

    def _deep_tick(name: str) -> None:
        nonlocal done
        done += 1
        if on_progress is not None:
            on_progress(done, deep_total or 1,
                        f"głęboka identyfikacja CHD ({done}/{deep_total}): {name}")

    def _aborted() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    # ---- (A) TANI nagłówek: chd.info + dopasowanie, równolegle -------------
    def _head_job(row):
        """W wątku roboczym: chd.info + dopasowanie nagłówka. BEZ dostępu do
        indeksu (SQLite tylko w wątku głównym). Zwraca krotkę do zastosowania."""
        path = Path(row["path"])
        dsha_known = bool(row["data_sha1"]) and row["data_sha1"] in known
        info = None
        try:
            info = chd.info(path)
        except OSError as e:
            if dsha_known:
                return ("known", row, None)
            return ("head", row, None, "", str(e))
        if dsha_known:
            # zidentyfikowany po TREŚCI — tu tylko dokładamy tani check KONTENERA
            return ("known", row, info)
        hit = ""
        for cand in (info.data_sha1, info.sha1):
            if cand and cand.lower() in known:
                hit = cand.lower()
                break
        return ("head", row, info, hit, "")

    if candidates:
        if on_progress is not None:
            on_progress(0, total_cand,
                        f"sprawdzam nagłówki {total_cand} CHD…")
        ex = ThreadPoolExecutor(max_workers=n_head)
        try:
            futs = {ex.submit(_head_job, r): r for r in candidates}
            for fut in as_completed(futs):
                if _aborted():
                    break
                res = fut.result()
                tag, row, info = res[0], res[1], res[2]
                path = Path(row["path"])
                if tag == "known":
                    _flag_container(path, info,
                                    known[row["data_sha1"]].media)
                    _head_tick(path.name)
                    continue
                hit, err = res[3], res[4]
                if err:
                    _log(f"CHD info: {path}: {err}")
                if hit:
                    index.set_data_sha1(path, hit)
                    _flag_container(path, info, known[hit].media)
                    identified += 1
                    _log(f"CHD OK (nagłówek): {path} -> {known[hit].game}")
                else:
                    need_deep.append((row, info))   # policzony w fazie głębokiej
                _head_tick(path.name)
        finally:
            # NA PRZERWANIU też CZEKAMY (wait=True): wątki w locie widzą
            # cancel_event, chdman jest zabijany od razu (_stream sprawdza cancel
            # co linię), a deep_identify przerywa pętlę metod — więc kończą się w
            # sekundy. Bez czekania `deep_probe` wracał NATYCHMIAST i pozostałe
            # ekstrakcje jechały dalej w tle (dopasowanie startowało nad żywymi
            # ekstrakcjami, a przy zamknięciu ramdysk był zajęty). cancel_futures
            # porzuca tylko to, co jeszcze NIE ruszyło.
            ex.shutdown(wait=True, cancel_futures=_aborted())
    deep_total = len(need_deep)

    # ---- (B) GŁĘBOKA ekstrakcja: równolegle wg deep_workers, pasek per slot -
    def _acquire_budget(need: int) -> int:
        """Rezerwuje `need` bajtów z budżetu RAM (albo cały, gdy gra > budżet →
        idzie sama, bez zakleszczenia). Czeka, aż się zmieści. Zwraca ile
        zarezerwowano (0 gdy budżet wyłączony)."""
        if budget_total <= 0:
            return 0
        reserve = min(need, budget_total)
        with budget_cond:
            while budget["free"] < reserve and budget["free"] < budget_total:
                if _aborted():
                    return -1                      # sygnał przerwania
                budget_cond.wait(timeout=0.5)
            budget["free"] -= reserve
        return reserve

    def _release_budget(reserve: int) -> None:
        if reserve and reserve > 0:
            with budget_cond:
                budget["free"] += reserve
                budget_cond.notify_all()

    def _deep_job(row, info):
        """W wątku: rezerwacja budżetu RAM + pick_scratch_root + deep_identify
        (ekstrakcja pełnego obrazu → hash). Wynik tylko zwracamy; index zapisuje
        wątek główny."""
        path = Path(row["path"])
        if _aborted():
            return ("cancel", row, info, None)
        try:
            need = max(int(path.stat().st_size * 2.2), 2 << 30)
        except OSError:
            need = 2 << 30
        # BRAMKA BUDŻETU RAM: czeka aż zmieści się `need` (małe gry → więcej
        # naraz). Zwolnienie w finally na KAŻDEJ ścieżce.
        reserve = _acquire_budget(need)
        if reserve < 0:
            return ("cancel", row, info, None)
        try:
            # RAM dysk MA PIERWSZEŃSTWO; wybór/remount pod lockiem — unika
            # wyścigu o odmontowany RAM-dysk między wątkami.
            with scratch_lock:
                wd = pick_scratch_root(
                    need, prefer=(str(work_dir) if work_dir else str(path.parent)),
                    log=_log, fallback=scratch_fallback)
            if wd is None:
                return ("noscratch", row, info, need)
            slot = slot_q.get()
            _log(f"CHD głęboko: {path}… (scratch: {wd})")

            def _dp(pct: float, msg: str = "", _name=path.name, _slot=slot) -> None:
                # postęp ekstrakcji chdman → OSOBNY pasek slotu (kilka naraz);
                # gdy brak slot_progress → wspólny pasek szczegółowy (1 wątek).
                if slot_progress is not None:
                    if pct is not None and pct >= 0:
                        slot_progress(_slot, int(pct), 100,
                                      f"{_name}: {msg or f'{int(pct)}%'}")
                    else:
                        slot_progress(_slot, 0, 0, f"{_name}: {msg}".rstrip(": "))
                elif detail is not None:
                    if pct is not None and pct >= 0:
                        detail(int(pct), 100,
                               f"CHD {_name}: {msg or f'{int(pct)}%'}")
                    else:
                        detail(0, 0, f"CHD {_name}: {msg}".rstrip(": "))

            try:
                if slot_progress is not None:
                    slot_progress(slot, 0, 0, f"wypakowuję: {path.name}…")
                elif detail is not None:
                    detail(0, 0, f"wypakowuję CHD: {path.name}…")
                # PREFIKS z nazwą pliku: w trybie równoległym logi z
                # deep_identify (Próba/✔/✗) się PRZEPLATAJĄ — bez nazwy „✔ ==
                # DAT 'X'" wyglądałaby, jakby należała do sąsiedniego „CHD
                # głęboko: Y". Prefiks czyni log jednoznacznym i weryfikowalnym.
                _pfx = f"[{path.name}] " if n_deep > 1 else ""
                r = deep_identify(chd, path, merged, wd,
                                  log=lambda m, _p=_pfx: _log(f"  {_p}{m}"),
                                  on_progress=_dp,
                                  cancel_event=cancel_event, chd_info=info)
                return ("deep", row, info, r)
            finally:
                if slot_progress is not None:
                    slot_progress(slot, -1, 0, "")  # zwolnij/ukryj pasek slotu
                slot_q.put(slot)
        finally:
            _release_budget(reserve)

    if need_deep and not _aborted():
        slot_q: _queue.Queue = _queue.Queue()
        for i in range(n_deep):
            slot_q.put(i)
        ex = ThreadPoolExecutor(max_workers=n_deep)
        try:
            futs = {ex.submit(_deep_job, row, info): row
                    for (row, info) in need_deep}
            for fut in as_completed(futs):
                if _aborted():
                    break
                tag, row, info, r = fut.result()
                path = Path(row["path"])
                if tag == "cancel":
                    continue
                if tag == "noscratch":
                    _log(f"CHD POMIJAM (za mało miejsca na ŻADNYM dysku): "
                         f"{path} — potrzeba ~{r/1024**3:.1f} GB")
                    _deep_tick(path.name)
                    continue
                # tag == "deep"
                if r.ok and r.sha1:
                    index.set_data_sha1(path, r.sha1)
                    _media = r.media if r.media is not None else (
                        known[r.sha1].media if r.sha1 in known else None)
                    _flag_container(path, info, _media)
                    identified += 1
                    _log(f"CHD OK ({r.method}): {path} -> {r.game}")
                elif _aborted():
                    pass                    # przerwane ręcznie — NIE zapisuj porażki
                else:
                    index.set_deep_fail(path)   # zapamiętaj: nie próbuj ponownie
                    _log(f"CHD BRAK: {path} — bez dopasowania "
                         f"(prób: {len(r.tried)}; zapamiętane — nie będzie "
                         f"mielony przy kolejnych skanach)")
                _deep_tick(path.name)
        finally:
            # NA PRZERWANIU też CZEKAMY (wait=True): wątki w locie widzą
            # cancel_event, chdman jest zabijany od razu (_stream sprawdza cancel
            # co linię), a deep_identify przerywa pętlę metod — więc kończą się w
            # sekundy. Bez czekania `deep_probe` wracał NATYCHMIAST i pozostałe
            # ekstrakcje jechały dalej w tle (dopasowanie startowało nad żywymi
            # ekstrakcjami, a przy zamknięciu ramdysk był zajęty). cancel_futures
            # porzuca tylko to, co jeszcze NIE ruszyło.
            ex.shutdown(wait=True, cancel_futures=_aborted())
    return identified
