"""Tłumaczenia fanowskie jako osobny TYP źródła (rola DAT-u „translations").

Dostarcza:
- parsowanie języka i etykiety z nazwy gry (`[T-En]`, `(En,Fr,De)`, `[T+Eng]`…),
- indeks WARIANTÓW tłumaczeń (tytuł bazowy → lista wariantów) z DAT-ów o roli
  `translations`,
- trwały wybór podmian (`translations.json`) — gra → tożsamość wariantu po SHA-1,
  będący ŹRÓDŁEM PRAWDY dla matchera (skan nie cofa świadomego wyboru),
- przepływ PODMIANY: oryginał kolekcji → `to sort\\translated\\<system>\\`,
  a pod NAZWĄ KANONICZNĄ gry powstaje symlink do pliku tłumaczenia; oraz
  ODTWORZENIE (restore) z powrotem.

V1: gry JEDNOPLIKOWE (kartridż / 1 CHD). Wieloplikowe (MSU-1, płyty) — później.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

LogCB = Callable[[str], None]


# --- parsowanie tytułu / języka ----------------------------------------------

def base_title(name: str) -> str:
    """Tytuł bez wszystkich tagów () i [] — do parowania gry z tłumaczeniem."""
    out = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", name)
    return re.sub(r"\s+", " ", out).strip().lower()


# normalizacja nazw języków → kod ISO-639-1 (na tyle, na ile potrzeba w nazwach)
_LANG_ALIASES = {
    "en": "en", "eng": "en", "english": "en",
    "fr": "fr", "fre": "fr", "french": "fr", "français": "fr", "francais": "fr",
    "de": "de", "ger": "de", "german": "de", "deutsch": "de",
    "es": "es", "spa": "es", "spanish": "es", "español": "es", "espanol": "es",
    "it": "it", "ita": "it", "italian": "it", "italiano": "it",
    "pt": "pt", "por": "pt", "portuguese": "pt", "português": "pt",
    "ja": "ja", "jp": "ja", "jpn": "ja", "japanese": "ja",
    "nl": "nl", "dutch": "nl",
    "sv": "sv", "swedish": "sv",
    "pl": "pl", "pol": "pl", "polish": "pl", "polski": "pl",
    "ru": "ru", "rus": "ru", "russian": "ru",
    "ko": "ko", "kor": "ko", "korean": "ko",
    "zh": "zh", "chi": "zh", "chinese": "zh",
    "ca": "ca", "catalan": "ca",
    "da": "da", "danish": "da",
    "no": "no", "norwegian": "no",
    "fi": "fi", "finnish": "fi",
}

# region → domyślny język (fallback, gdy w nazwie nie ma jawnego tagu języka).
# Japan/USA/Europe są jednoznaczne; wyjątki jawne ((En)/English/[T-Fr]) wygrywają.
_REGION_LANG = {
    "japan": "ja", "usa": "en", "europe": "en", "world": "en", "asia": "en",
    "australia": "en", "canada": "en", "uk": "en",
    "united kingdom": "en", "ireland": "en", "new zealand": "en",
    "korea": "ko", "china": "zh", "taiwan": "zh", "hong kong": "zh",
    "germany": "de", "france": "fr", "spain": "es", "italy": "it",
    "netherlands": "nl", "sweden": "sv", "norway": "no", "denmark": "da",
    "finland": "fi", "poland": "pl", "russia": "ru", "brazil": "pt",
    "portugal": "pt", "greece": "el", "scandinavia": "sv",
}

# tag tłumaczenia w [] LUB (): [T-En], [T+Eng], (T-En), [T-En by Foo], [T+Fr1.2]
_T_TAG_RE = re.compile(r"[\[\(]\s*T[-+]\s*([A-Za-z]+)", re.I)
# ogólny tag tłumaczenia (do etykiety) — [...]/(...) zaczynające się od T-/T+
_T_LABEL_RE = re.compile(r"[\[\(]\s*T[-+][^\]\)]*[\]\)]", re.I)


def _lang_from_token(tok: str) -> str:
    """Kod języka z tokenu: dokładnie (en/eng/english) albo po 3-/2-literowym
    prefiksie (np. „EnglishByFoo"→en). Nieznane → "" (NIE śmiecimy)."""
    t = tok.strip().lower()
    for cand in (t, t[:3], t[:2]):
        c = _LANG_ALIASES.get(cand)
        if c:
            return c
    return ""


def parse_langs(name: str, region_fallback: bool = True) -> List[str]:
    """Języki wykryte w nazwie. Rozpoznaje:
      - tag tłumaczenia `[T-En]/[T+Eng]/(T-Eng)` → PIERWSZY token po T-/+,
      - listy językowe w () lub [] gdzie WSZYSTKIE tokeny to znane języki
        (`(En,Fr,De)`, `(English)`, `[En]`),
      - (gdy `region_fallback` i nic jawnego) REGION → język ((Japan)→ja,
        (USA)/(Europe)→en …).
    NIE-języki (grupy, wersje) są ODRZUCANE — żadnych śmieciowych kodów.
    Zwraca kody ISO bez duplikatów, w kolejności wystąpienia."""
    out: List[str] = []

    def _add(c: str) -> None:
        if c and c not in out:
            out.append(c)

    # 1) tag tłumaczenia — pierwszy token po T-/T+ (język; reszta to grupa/wersja)
    for m in _T_TAG_RE.finditer(name):
        _add(_lang_from_token(m.group(1)))
    # 2) grupy () i [] będące CZYSTĄ listą języków (wszystkie tokeny znane)
    for grp in re.findall(r"[\(\[]([^)\]]*)[\)\]]", name):
        toks = [t for t in re.split(r"[,\s/+]+", grp) if t]
        if toks and all(t.lower() in _LANG_ALIASES for t in toks):
            for t in toks:
                _add(_LANG_ALIASES[t.lower()])
    # 3) FALLBACK po REGIONIE — tylko gdy nie było JAWNEGO tagu/listy języka.
    #    Jawne „(En)"/„English"/[T-*] wygrało wyżej.
    if region_fallback and not out:
        for grp in re.findall(r"[\(\[]([^)\]]*)[\)\]]", name):
            for part in grp.split(","):
                c = _REGION_LANG.get(part.strip().lower())
                if c:
                    _add(c)
    return out


def is_translation(name: str) -> bool:
    """Czy nazwa niesie tag fanowskiego tłumaczenia `[T-…]`/`(T-…)`."""
    return bool(_T_TAG_RE.search(name))


def translation_label(name: str) -> str:
    """Etykieta wariantu do GUI: treść tagu `[T-…]` (autor/wersja), np.
    „[T-En by Foo v1.1]". Gdy brak — pusty string."""
    m = _T_LABEL_RE.search(name)
    return m.group(0) if m else ""


def is_translation_collection(entry) -> bool:
    """Czy DAT jest pulą tłumaczeń — wg nazwy LUB metadanych sidecar-JSON
    (`group`/`system` z tagiem `[T-…]`, np. „[T-En]Collection"). Dzięki temu
    kolekcje RomVaulta są wykrywane automatycznie, bez ręcznego ustawiania roli."""
    name = getattr(entry, "name", "") or ""
    meta = getattr(entry, "meta", {}) or {}
    return (is_translation(name) or is_translation(meta.get("group", ""))
            or is_translation(meta.get("system", "")))


# --- indeks wariantów --------------------------------------------------------

@dataclass
class TransVariant:
    """Jeden dostępny wariant tłumaczenia (gra jednoplikowa)."""
    base: str                 # tytuł bazowy (do parowania)
    game: str                 # pełna nazwa gry w DAT-cie tłumaczeń
    langs: tuple              # wykryte języki (kody)
    label: str               # etykieta [T-…] do GUI
    canonical: str           # ścieżka pliku tłumaczenia (kanoniczna w jego DAT)
    sha1: str                # SHA-1 zawartości (stabilna tożsamość wyboru)
    size: int                # rozmiar (do identyfikacji)
    dat_name: str            # nazwa DAT-u tłumaczeń
    dat_id: int              # id(entry) — do odróżnienia źródła

    @property
    def lang_str(self) -> str:
        return ",".join(self.langs) if self.langs else "?"


def build_variant_index(
        reports: Sequence, rules_fn: Optional[Callable[[object], dict]],
) -> Dict[str, List[TransVariant]]:
    """Mapa `tytuł_bazowy → [warianty]` z DAT-ów o roli `translations`.
    Tylko gry JEDNOPLIKOWE (jeden ROM danych) — dopasowanie po zawartości.
    `rules_fn(entry)` musi zwracać dict z ewentualnym kluczem `role`.
    """
    idx: Dict[str, List[TransVariant]] = {}
    for rep in reports:
        eff = rules_fn(rep.entry) if rules_fn else {}
        # Pula tłumaczeń, gdy: JAWNA rola „translations" ALBO auto-wykrycie po
        # nazwie/sidecar-JSON (np. grupa „[T-En]Collection"). Dzięki temu nie
        # trzeba ręcznie oznaczać każdego DAT-u kolekcji tłumaczeń.
        if ((eff or {}).get("role") != "translations"
                and not is_translation_collection(rep.entry)):
            continue
        # Język bywa TYLKO w nazwie DAT-u/grupie (np. „… [T-En] Collection"), a
        # gry w środku mają czyste nazwy → dziedziczymy język/etykietę stąd, gdy
        # nazwa gry nic nie ma. To naprawia „puste" wykrywanie języka.
        _meta = getattr(rep.entry, "meta", {}) or {}
        dat_langs = (parse_langs(rep.entry.name)
                     or parse_langs(_meta.get("group", ""))
                     or parse_langs(_meta.get("system", "")))
        dat_label = (translation_label(rep.entry.name)
                     or translation_label(_meta.get("group", "")))
        by_game: Dict[str, list] = {}
        for s in rep.statuses:
            by_game.setdefault(s.game, []).append(s)
        for gname, sts in by_game.items():
            data = [s for s in sts
                    if not s.rom.name.lower().endswith((".cue", ".gdi"))]
            if len(data) != 1:
                continue                      # v1: tylko jednoplikowe
            s = data[0]
            # Priorytet języka wariantu: JAWNY tag/lista w nazwie gry → język
            # TŁUMACZENIA z nazwy DAT-u → region gry (fallback). Dzięki temu
            # „Cool Game (Japan)" w „[T-En] Collection" = en (nie ja).
            langs = tuple(parse_langs(gname, region_fallback=False)
                          or dat_langs or parse_langs(gname))
            label = (translation_label(gname)
                     or (f"{gname} {dat_label}".strip() if dat_label else gname))
            v = TransVariant(
                base=base_title(gname), game=gname, langs=langs, label=label,
                canonical=str(s.canonical_path),
                sha1=(s.rom.sha1 or "").lower(), size=s.rom.size or 0,
                dat_name=rep.entry.name, dat_id=id(rep.entry))
            idx.setdefault(v.base, []).append(v)
    return idx


def variants_for(index: Dict[str, List[TransVariant]], game_name: str,
                 lang: str = "") -> List[TransVariant]:
    """Warianty pasujące do gry (po tytule bazowym), opcjonalnie filtrowane
    językiem (kod ISO). Posortowane: język pasujący pierwszy, potem nazwa."""
    hits = list(index.get(base_title(game_name), []))
    if lang:
        hits = [v for v in hits if lang in v.langs]
    hits.sort(key=lambda v: (v.lang_str, v.game.lower()))
    return hits


def all_languages(index: Dict[str, List[TransVariant]]) -> List[str]:
    """Wszystkie języki obecne w indeksie wariantów (posortowane)."""
    out: set = set()
    for vs in index.values():
        for v in vs:
            out.update(v.langs)
    return sorted(out)


# --- trwały wybór podmian (translations.json) --------------------------------

def sub_key(dat_name: str, game: str) -> str:
    """Klucz podmiany: nazwa DAT-u + nazwa gry (stabilny między przebiegami)."""
    return f"{dat_name}\t{game}"


class TranslationStore:
    """Trwały wybór podmian per gra. Plik JSON w katalogu kolekcji.
    Wpis: klucz sub_key(dat, gra) → {sha1, name, lang, src}. ŹRÓDŁO PRAWDY dla
    matchera (gra z wpisem = spełniona przez wybrane tłumaczenie)."""

    FILENAME = "translations.json"

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._subs: Dict[str, dict] = {}
        self.load()

    def load(self) -> "TranslationStore":
        self._subs = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._subs = dict(data.get("subs", {}))
        except (OSError, ValueError):
            self._subs = {}
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "subs": self._subs},
                                  ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    # -- API per gra --
    def get(self, dat_name: str, game: str) -> Optional[dict]:
        return self._subs.get(sub_key(dat_name, game))

    def set(self, dat_name: str, game: str, variant: "TransVariant") -> None:
        self._subs[sub_key(dat_name, game)] = {
            "sha1": variant.sha1, "name": variant.game,
            "lang": variant.lang_str, "src": variant.canonical,
            "dat": variant.dat_name}

    def set_manual(self, dat_name: str, game: str, *, sha1: str, name: str,
                   src: str, lang: str = "") -> None:
        self._subs[sub_key(dat_name, game)] = {
            "sha1": (sha1 or "").lower(), "name": name, "lang": lang,
            "src": src, "dat": ""}

    def remove(self, dat_name: str, game: str) -> bool:
        return self._subs.pop(sub_key(dat_name, game), None) is not None

    def has(self, dat_name: str, game: str) -> bool:
        return sub_key(dat_name, game) in self._subs

    @property
    def subs(self) -> Dict[str, dict]:
        """Surowa mapa (klucz sub_key → wpis) — dla matchera."""
        return self._subs


# --- przepływ podmiany / odtworzenia -----------------------------------------

def preserve_dir_for(tosort_root: str | os.PathLike, system: str) -> Path:
    """Katalog na oryginały: `<to sort>\\translated\\<system>`."""
    safe = re.sub(r'[<>:"/\\|?*]+', "_", system).strip() or "misc"
    return Path(tosort_root) / "translated" / safe


ARCHIVE_EXTS = (".zip", ".7z")


def _is_archive(p: Path) -> bool:
    return p.suffix.lower() in ARCHIVE_EXTS


def game_forms(canonical: Path, game_name: str = "") -> List[Path]:
    """Wszystkie miejsca, w których kolekcja może trzymać grę jednoplikową:
    luźny ROM pod nazwą z DAT-u oraz archiwum `<gra>.zip` / `<gra>.7z`."""
    stem = game_name or canonical.stem
    out = [canonical]
    for ext in ARCHIVE_EXTS:
        p = canonical.with_name(stem + ext)
        if p not in out:
            out.append(p)
    return out


_CONTAINER_EXT = {"zip": ".zip", "7z": ".7z", "chd": ".chd", "rvz": ".rvz"}


def slot_path(canonical: Path, variant_file: Path, game_name: str = "",
              store_format: str = "keep") -> Path:
    """Ścieżka slotu wg USTAWIENIA KATALOGU (format zapisu DAT-u) — twardo.

    Nazwa z DAT-u to nazwa ROM-u („… (Japan).rom"), ale katalog z formatem
    `zip` trzyma grę jako `<gra>.zip` i slot NIE może być `.rom`. Dawniej link
    dostawał nazwę ROM-u i wskazywał archiwum tłumaczenia: emulatory wybierające
    sposób otwarcia po rozszerzeniu (blueMSX) go nie czytały, a oryginalny
    `<gra>.zip` zostawał obok i to on się uruchamiał.

    * `zip` / `7z` / `chd` / `rvz` → `<gra>.<ext>`,
    * `extract` → luźny ROM pod nazwą z DAT-u,
    * `keep` → forma wariantu (archiwum → `<gra>.<ext>`, luźny → nazwa z DAT-u).
    """
    stem = game_name or canonical.stem
    fmt = (store_format or "keep").lower()
    if fmt in _CONTAINER_EXT:
        return canonical.with_name(stem + _CONTAINER_EXT[fmt])
    if fmt == "extract":
        return canonical
    if variant_file.suffix.lower() == canonical.suffix.lower():
        return canonical
    if _is_archive(variant_file):
        return canonical.with_name(stem + variant_file.suffix)
    return canonical


def _slot_action(slot: Path, variant_file: Path) -> str:
    """Jak wypełnić slot wariantem: "link" (ta sama forma), "pack" (luźny →
    ZIP), "extract" (ZIP → luźny) albo "" gdy nie da się bez utraty zgodności."""
    s, v = slot.suffix.lower(), variant_file.suffix.lower()
    if s == v or not (_is_archive(slot) or _is_archive(variant_file)
                      or s in (".chd", ".rvz") or v in (".chd", ".rvz")):
        return "link"
    if s == ".zip" and not _is_archive(variant_file) and v not in (".chd", ".rvz"):
        return "pack"
    if v == ".zip" and not _is_archive(slot) and s not in (".chd", ".rvz"):
        return "extract"
    return ""


def link_form_mismatch(link: Path) -> bool:
    """True, gdy link i jego cel różnią się formą (luźny plik ↔ archiwum) —
    ślad po starej podmianie (`… .rom` → `… .zip`)."""
    try:
        target = Path(os.path.realpath(link))
    except OSError:
        return False
    return _is_archive(link) != _is_archive(target)


def apply_substitution(
        canonical: Path, variant_file: Path, preserve_dir: Path, *,
        game_name: str = "", store_format: str = "keep",
        zip_method: str = "deflate", index=None,
        make_links: bool = True, dry_run: bool = False,
        log: LogCB = lambda m: None) -> bool:
    """Podmiana slotu kolekcji na tłumaczenie:
      1) gra w KAŻDEJ formie (luźny ROM, `<gra>.zip`, `<gra>.7z`): fizyczny
         plik → `preserve_dir` (zachowanie do odtworzenia i walidacji setu),
         istniejący symlink po prostu usuwamy — inaczej oryginał w innej
         formie zostawałby obok tłumaczenia,
      2) SLOT (forma wg formatu katalogu, patrz `slot_path`) ← wariant:
         symlink, gdy forma się zgadza; luźny wariant w katalogu `zip` jest
         pakowany do `<gra>.zip`, wariant `.zip` w katalogu `extract` —
         wypakowany. Innych przejść nie robimy (odmowa, nic nie ruszone).
         Zip wariantu w INNEJ metodzie niż `zip_method` (np. ZSTD przy deflate)
         nie jest linkowany, tylko kopiowany do slotu i przepakowany: link
         przeniósłby ZSTD do kolekcji („Failed to inflate" w emulatorach), a
         normalizacja kompresji w naprawie linków nie rusza.
    Nie kasuje żadnego pliku bezpowrotnie. Zwraca True gdy podmiana zrobiona
    (albo w dry-run zapowiedziana)."""
    from .linker import create_link, is_link, remove_link, LinkPrivilegeError
    if not variant_file.exists():
        log(f"TŁUMACZENIE: brak pliku wariantu {variant_file} — pomijam")
        return False
    # make_links=False → NIE ruszaj oryginału. Dawniej sprawdzaliśmy to DOPIERO
    # po przeniesieniu oryginału do preserve → kanoniczna ścieżka zostawała
    # PUSTA (link i tak nie powstawał). Fail-fast, zanim cokolwiek ruszymy.
    if not make_links and not dry_run:
        log("  linki wyłączone — podmiana pominięta (oryginał nietknięty)")
        return False
    slot = slot_path(canonical, variant_file, game_name, store_format)
    action = _slot_action(slot, variant_file)
    if not action:
        log(f"TŁUMACZENIE: format katalogu „{store_format}” wymaga {slot.name}, "
            f"a wariant to {variant_file.suffix} — tej konwersji nie robię "
            f"(oryginał nietknięty)")
        return False
    if action == "extract":
        try:
            import zipfile
            with zipfile.ZipFile(variant_file) as z:
                members = [i for i in z.infolist() if not i.is_dir()]
        except (OSError, zipfile.BadZipFile) as e:
            log(f"TŁUMACZENIE: nie da się odczytać {variant_file.name}: {e}")
            return False
        if len(members) != 1:
            log(f"TŁUMACZENIE: {variant_file.name} ma {len(members)} plików — "
                f"wypakowuję tylko gry jednoplikowe (oryginał nietknięty)")
            return False
    if action == "link" and slot.suffix.lower() == ".zip":
        from .convert import zip_needs_repack
        if zip_needs_repack(variant_file, zip_method):
            action = "repack"
            log(f"  {variant_file.name}: inna metoda kompresji niż {zip_method} — "
                f"slot będzie przepakowaną kopią, nie linkiem")
    if slot != canonical:
        log(f"  slot wg formatu katalogu ({store_format}): {slot.name} (DAT: {canonical.name})")
    # 1) zabezpiecz oryginał / usuń stare linki (z możliwością COFNIĘCIA)
    rollback: list = []              # (kind "move"|"copy", zachowany, ścieżka)
    for form in [slot] + [p for p in game_forms(canonical, game_name) if p != slot]:
        if not os.path.lexists(form):
            continue
        if is_link(form):
            log(f"  usuwam poprzedni link: {form.name}")
            if not dry_run:
                remove_link(form)
            continue
        dest = preserve_dir / form.name
        log(f"  oryginał → {dest}")
        if dry_run:
            continue
        preserve_dir.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            form.unlink()                   # już zachowany — usuń bieżący
            if index is not None:
                try:
                    index.remove_path(form)
                except Exception:
                    pass
            rollback.append(("copy", dest, form))   # odtwórz z zachowanej kopii
        else:
            os.replace(form, dest)
            if index is not None:
                try:
                    index.rename(form, dest)
                except Exception:
                    pass
            rollback.append(("move", dest, form))
    # 2) slot ← wariant
    verb = {"link": "->", "pack": "<= spakowany", "extract": "<= wypakowany z",
            "repack": f"<= przepakowany ({zip_method})"}[action]
    log(f"TŁUMACZENIE: {slot.name} {verb} {variant_file}")
    if dry_run:
        return True
    try:
        if action == "link":
            create_link(slot, variant_file, is_dir=False)
        elif action == "pack":
            from .convert import pack_zip
            res = pack_zip([variant_file], slot, arcnames=[canonical.name],
                           method=zip_method, log=log)
            if not res.ok:
                raise OSError(res.message)
        elif action == "repack":
            import shutil as _sh
            from .convert import repack_zip
            tmp = slot.with_name(slot.name + ".chdbuddy_tmp")
            _sh.copyfile(variant_file, tmp)
            res = repack_zip(tmp, method=zip_method, log=log)
            if not res.ok:
                raise OSError(res.message)
            os.replace(tmp, slot)
        else:
            import zipfile
            tmp = slot.with_name(slot.name + ".chdbuddy_tmp")
            with zipfile.ZipFile(variant_file) as z, open(tmp, "wb") as out:
                member = next(i for i in z.infolist() if not i.is_dir())
                with z.open(member) as src:
                    import shutil as _sh
                    _sh.copyfileobj(src, out)
            os.replace(tmp, slot)
    except (LinkPrivilegeError, OSError) as e:
        slot.with_name(slot.name + ".chdbuddy_tmp").unlink(missing_ok=True)
        if isinstance(e, LinkPrivilegeError):
            log(f"  UWAGA: {e} — uruchom jako administrator.")
        else:
            log(f"  BŁĄD zapisu slotu: {e}")
        # ROLLBACK: nie zostawiaj slotu PUSTEGO — przywróć oryginały.
        for kind, dsrc, form in rollback:
            try:
                if kind == "move":
                    os.replace(dsrc, form)
                    if index is not None:
                        try:
                            index.rename(dsrc, form)
                        except Exception:
                            pass
                else:                            # "copy" — oryginał był duplikatem
                    import shutil as _sh
                    _sh.copy2(dsrc, form)
                log(f"  przywrócono oryginał: {form.name}")
            except OSError as re_:
                log(f"  NIE udało się przywrócić oryginału {form}: {re_}")
        return False
    if index is not None and action == "link":
        try:
            index.mark_link(slot)
        except Exception:
            pass
    return True


def restore_original(canonical: Path, preserve_dir: Path, *, game_name: str = "",
                     index=None, dry_run: bool = False,
                     log: LogCB = lambda m: None) -> bool:
    """Cofa podmianę: usuwa linki gry (w każdej formie) i przywraca zachowane
    oryginały z `preserve_dir`. Zwraca True, gdy przywrócono.

    Po starej podmianie (link `.rom` → `.zip`, oryginał `<gra>.zip` nietknięty)
    nie ma nic do przywrócenia — wtedy samo usunięcie linku jest odtworzeniem."""
    from .linker import is_link, remove_link
    forms = game_forms(canonical, game_name)
    saved = [(f, preserve_dir / f.name) for f in forms
             if (preserve_dir / f.name).exists()]
    links = [f for f in forms if os.path.lexists(f) and is_link(f)]
    if not saved:
        physical = [f for f in forms if os.path.lexists(f) and not is_link(f)]
        if links and physical:
            for f in links:
                log(f"ODTWORZENIE: usuwam link {f.name} (oryginał {physical[0].name} na miejscu)")
                if not dry_run:
                    remove_link(f)
            return True
        log(f"ODTWORZENIE: brak zachowanego oryginału {preserve_dir / canonical.name}")
        return False
    for f in links:
        if not dry_run:
            remove_link(f)
    # Slot zbudowany z wariantu (spakowany/wypakowany), a nie link: podmiana
    # przeniosła do `preserve_dir` WSZYSTKIE fizyczne formy gry, więc fizyczna
    # forma bez zachowanego odpowiednika to nasz wytwór — odtwarzalny z wariantu.
    saved_forms = {f for f, _ in saved}
    for f in forms:
        if f not in saved_forms and os.path.lexists(f) and not is_link(f):
            log(f"ODTWORZENIE: usuwam slot zbudowany z tłumaczenia: {f.name}")
            if not dry_run:
                f.unlink()
    for form, src in saved:
        log(f"ODTWORZENIE: {form.name} <- {src}")
        if dry_run:
            continue
        if os.path.lexists(form):
            if is_link(form):
                remove_link(form)
            else:
                form.unlink()
        os.replace(src, form)
        if index is not None:
            try:
                index.rename(src, form)
            except Exception:
                pass
    return True
