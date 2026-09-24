"""Magazyn DAT-ów — odpowiednik DatRoot/RomRoot z RomVaulta.

Drzewo katalogu z DAT-ami (dat_root) odwzorowuje się na drzewo katalogów
ROM-ów (rom_root): DAT leżący w ``dat_root/PS2/foo.dat`` dostaje katalog
docelowy ``rom_root/PS2/<nazwa>`` , gdzie <nazwa> to pole Name z nagłówka
DAT-a (fallback: nazwa pliku bez rozszerzenia). To wariant „automatycznie
wg tagu Name" z RomVaulta — najpopularniejszy.

Kolejność DAT-ów wyznacza hierarchię rodzic→dzieci przy plikach wspólnych:
pierwszy DAT z trafieniem trzyma plik fizycznie, kolejne dostają symlinki.

Priorytet parent→child dotyczy TYLKO DAT-ów tej samej PLATFORMY (te same
pliki mogą być w wielu DAT-ach jednej platformy — pełny Redump, 1G1R,
tłumaczenia). DAT-y różnych platform (PS2 vs Saturn vs N64) nigdy nie
kolidują, więc ich wzajemna kolejność jest bez znaczenia.

Priorytet w obrębie platformy (od najważniejszego):
1. Ręczny — plik ``_priorytet.txt`` w katalogu DAT-ów: jedna nazwa DAT-a
   (pliku albo z nagłówka) na linię, kolejność = hierarchia; ``#`` komentarz.
2. Domyślny — DAT tej platformy z WIĘKSZĄ liczbą ROM-ów jest nadrzędny
   (główna biblioteka, np. pełny Redump), mniejsze zestawy (1G1R/Retool/
   tłumaczenia) linkują z niego.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List

from .datfile import DatGame, parse_dat, parse_dat_header


def platform_key(name: str) -> str:
    """Nazwa DAT-a → klucz PLATFORMY (bez wariantów), np.
    'Sony - PlayStation 2 - Datfile (11719)' i
    'Sony - PlayStation 2 (Redump - Fresh1G1R - PropeR)' → 'sony playstation 2'.
    Grupuje pełny Redump, 1G1R, Retool i tłumaczenia tej samej platformy."""
    s = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", name)         # usuń (…) i […]
    s = re.sub(r"\b(?:Datfile|Collection|Retool)\b", " ", s, flags=re.I)
    s = re.sub(r"[-_]+", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


@dataclass
class DatEntry:
    """Jeden DAT + jego katalog docelowy w drzewie ROM-ów."""
    dat_path: Path
    name: str
    target_dir: Path
    # Gry wieloplikowe (bin/cue, gdi+tracki) luzem => podkatalog per gra.
    # CHD i archiwa są zawsze płasko. Wybór regułą `subdir_per_game`.
    subdir_per_game: bool = True
    # Rozwiązany format przechowywania (keep/extract/zip/7z/chd/rvz). Ustala
    # apply_rule_targets — dzieci dziedziczą format RODZICA (są symlinkami do
    # jego plików, więc muszą mieć ten sam kontener).
    store_format: str = "keep"
    games: List[DatGame] = field(default_factory=list, repr=False)
    # Metadane z sidecar-JSON RomVaulta (opcjonalne — nie każdy DAT je ma):
    # group / system / version / datName / datROMsSize. Puste, gdy brak.
    meta: dict = field(default_factory=dict, repr=False)

    @property
    def rom_count(self) -> int:
        return sum(len(g.roms) for g in self.games)

    def load(self) -> "DatEntry":
        if not self.games:
            self.games = list(parse_dat(self.dat_path))
        return self


def _safe_dirname(name: str) -> str:
    """Nazwa z nagłówka DAT-a jako poprawna nazwa katalogu Windows."""
    bad = '<>:"/\\|?*'
    out = "".join((c if c not in bad else "-") for c in name).strip(" .")
    return out or "unnamed"


def _sidecar_meta(dat: Path, cache: dict) -> dict:
    """Metadane z sidecar-JSON RomVaulta dla danego `.dat` (dopasowanie po polu
    `datName`). NIE każdy DAT ma JSON — wtedy zwraca {}. JSON-y z katalogu są
    czytane RAZ (cache per katalog)."""
    d = dat.parent
    key = str(d)
    if key not in cache:
        by_name: dict = {}
        try:
            for j in d.glob("*.json"):
                try:
                    data = json.loads(j.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(data, dict) and data.get("datName"):
                    by_name[data["datName"]] = data
        except OSError:
            pass
        cache[key] = by_name
    return cache[key].get(dat.name, {})


PRIORITY_FILENAME = "_priorytet.txt"


def save_priority(dat_root: Path, names: list[str]) -> Path:
    """Zapisuje _priorytet.txt (nazwy DAT-ów w kolejności = hierarchia).
    Ważna jest tylko kolejność W OBRĘBIE platformy."""
    p = Path(dat_root) / PRIORITY_FILENAME
    body = ("# Hierarchia DAT-ów per platforma (góra = rodzic, trzyma pliki\n"
            "# fizycznie; niżej = dzieci, dostają symlinki). Kolejność między\n"
            "# platformami bez znaczenia. Plik generowany z GUI.\n"
            + "\n".join(names) + "\n")
    p.write_text(body, encoding="utf-8")
    return p


# Tokeny w nawiasach oznaczające TIER/kolekcję (NIE wariant zrzutu) — pomijane
# przy wyznaczaniu wariantu. Wariant zrzutu (A2R/Waveform/WOZ/Flux/J64…) zostaje.
_TIER_TOKENS = {
    "datfile", "collection", "retool", "1g1r", "redump", "fresh1g1r", "proper",
    "fresh", "no-intro", "nointro", "standard", "parent-clone", "merged",
    "split", "non-merged", "nonmerged", "beta", "wip",
}


def variant_key(name: str) -> str:
    """Wariant ZRZUTU z nazwy DAT-a (część w nawiasach, która NIE jest tierem/
    kolekcją/datą/ID): 'Apple - II (A2R) (Retool)' → 'a2r', 'Apple - II (Waveform)'
    → 'waveform', 'Atari - Atari Jaguar (J64)' → 'j64', 'Sony - PlayStation 2 -
    Datfile (11719)' → '' (brak wariantu). Do rozróżnienia wariantów tej samej
    platformy, gdy nie ma nad nimi tieru-rodzica (ROMS)."""
    import re as _re
    out = []
    for m in _re.finditer(r"\(([^)]*)\)", name):
        inner = m.group(1).strip()
        toks = [t for t in _re.split(r"[\s,\-_]+", inner.lower()) if t]
        if not toks:
            continue
        # pomiń grupy złożone WYŁĄCZNIE z tierów/dat/ID (np. „11719", „2026-03-15")
        if all(t in _TIER_TOKENS or t.isdigit()
               or _re.fullmatch(r"\d{4,}", t) or _re.fullmatch(r"v?\d[\d.]*", t)
               for t in toks):
            continue
        out.append(inner.lower())
    return " ".join(out).strip()


def effective_platform_key(entry, rules=None) -> str:
    """Klucz platformy DAT-a z uwzględnieniem RĘCZNEGO przypięcia (reguła
    `platform` w _reguly.json). Alias może być kluczem platformy albo nazwą
    DAT-a rodzica — normalizujemy przez platform_key. Tak „FinalBurn Neo -
    SNES Games" może być dzieckiem platformy Nintendo SNES mimo innej nazwy."""
    if rules is not None:
        alias = rules.for_entry(entry).get("platform", "")
        if alias:
            return platform_key(str(alias))
    return platform_key(entry.name)


def _dat_tier(entry, dat_root) -> str:
    """Tier = pierwszy segment ścieżki DAT-a względem dat_root (ROMS / No-Intro /
    1G1R …), małymi literami. Puste, gdy nie da się ustalić."""
    if dat_root is None:
        return ""
    try:
        rel = Path(entry.dat_path).parent.relative_to(dat_root)
    except (ValueError, TypeError):
        return ""
    parts = rel.parts
    return parts[0].lower() if parts else ""


def group_by_platform(entries: list, rules=None, dat_root=None) -> "dict[str, list]":
    """Grupuje wpisy po platformie (z aliasami z reguł), zachowując w każdej
    grupie kolejność priorytetu (rodzic pierwszy) z discover().

    HIERARCHIA po TIERZE katalogu (odporna): w obrębie platformy najwyższy tier
    (np. ROMS) wyznacza rodzica. Gdy najwyższy tier ma JEDEN DAT → on rodzic,
    reszta (No-Intro/1G1R, dowolny wariant) = dzieci (np. Atari Jaguar: ROMS J64
    rodzic, No-Intro JAG + 1G1R dzieci). Gdy najwyższy tier ma WIELE DAT-ów =
    różne WARIANTY zrzutu i NIE ma nad nimi ROMS (np. Apple II: No-Intro A2R/
    Waveform/WOZ) → rozbijamy platformę PO WARIANCIE, żeby każdy wariant był
    OSOBNYM rodzicem swojego 1G1R (Retool), a nie dzieckiem sąsiada."""
    coarse: dict[str, list] = {}
    for e in entries:
        coarse.setdefault(effective_platform_key(e, rules), []).append(e)
    if dat_root is None:
        return coarse
    out: dict[str, list] = {}
    for key, ents in coarse.items():
        if len(ents) <= 1:
            out[key] = ents
            continue
        top_tier = _dat_tier(ents[0], dat_root)     # ents[0] = najwyższy priorytet
        top_count = sum(1 for e in ents if _dat_tier(e, dat_root) == top_tier)
        if top_count <= 1:
            out[key] = ents                         # jeden rodzic-tier → bez zmian
            continue
        # najwyższy tier ma WIELE wariantów → rozbij po wariancie
        by_var: dict[str, list] = {}
        for e in ents:
            by_var.setdefault(variant_key(e.name), []).append(e)
        if len(by_var) <= 1:
            out[key] = ents                         # jeden wariant → bez zmian
            continue
        for vk, ve in by_var.items():
            out[f"{key} ({vk})" if vk else key] = ve
    return out


class DatStore:
    """Odkrywa DAT-y w dat_root i mapuje je na katalogi w rom_root."""

    def __init__(self, dat_root: Path, rom_root: Path, use_cache: bool = True):
        self.dat_root = Path(os.path.abspath(dat_root))
        self.rom_root = Path(os.path.abspath(rom_root))
        self.use_cache = use_cache

    def _manual_priority(self) -> list[str]:
        p = self.dat_root / PRIORITY_FILENAME
        if not p.is_file():
            return []
        out = []
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append(line.lower())
        except OSError:
            pass
        return out

    def _top_tier(self, p: Path) -> str:
        """Pierwszy segment ścieżki DAT-a względem dat_root (ROMS / No-Intro /
        1G1R …). '' = plik bezpośrednio w dat_root."""
        try:
            rel = p.relative_to(self.dat_root)
        except ValueError:
            return ""
        return rel.parts[0].lower() if len(rel.parts) > 1 else ""

    def _stat_sigs(self, files: list[Path], log=None) -> dict[Path, tuple]:
        """(mtime_ns, size) dla każdego DAT-a — jednym RÓWNOLEGŁYM przebiegiem
        stat. Na NAS/SMB sekwencyjny stat 600+ plików to dziesiątki sekund
        (runda SMB na plik); pula wątków ukrywa latencję. Liczbę wątków dobiera
        nośnik dat_root (NAS dużo, HDD 1)."""
        from concurrent.futures import ThreadPoolExecutor

        from .storage import storage_kind, workers_for_kind
        try:
            kind = storage_kind(self.dat_root)
        except Exception:                            # noqa: BLE001
            kind = "nas"
        nw = workers_for_kind(kind, nas=16, ssd=8, hdd=1)

        def _one(f: Path):
            try:
                st = f.stat()
                return f, (st.st_mtime_ns, st.st_size)
            except OSError:
                return f, None

        sigs: dict[Path, tuple] = {}
        if nw > 1 and len(files) > 1:
            with ThreadPoolExecutor(max_workers=nw) as ex:
                for f, s in ex.map(_one, files):
                    if s is not None:
                        sigs[f] = s
        else:
            for f in files:
                _, s = _one(f)
                if s is not None:
                    sigs[f] = s
        return sigs

    def _sidecar_index(self, sigs: dict[Path, tuple] | None = None,
                       log=None) -> dict[str, dict]:
        """{katalog: {datName: meta}} z sidecar-JSON RomVaulta — JEDEN przebieg
        rglob + RÓWNOLEGŁY odczyt/parse. Dawniej `glob("*.json")` per katalog na
        NAS (kilka sekund na katalog przez listing SMB). Nie każdy DAT ma JSON."""
        import json
        from concurrent.futures import ThreadPoolExecutor

        try:
            jsons = [f for f in self.dat_root.rglob("*.json") if f.is_file()]
        except OSError:
            return {}
        if not jsons:
            return {}

        def _one(j: Path):
            try:
                data = json.loads(j.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            if isinstance(data, dict) and data.get("datName"):
                return str(j.parent), data["datName"], data
            return None

        from .storage import storage_kind, workers_for_kind
        try:
            nw = workers_for_kind(storage_kind(self.dat_root), 16, 8, 1)
        except Exception:                            # noqa: BLE001
            nw = 8
        out: dict[str, dict] = {}
        if nw > 1 and len(jsons) > 1:
            with ThreadPoolExecutor(max_workers=nw) as ex:
                results = list(ex.map(_one, jsons))
        else:
            results = [_one(j) for j in jsons]
        for r in results:
            if r is not None:
                out.setdefault(r[0], {})[r[1]] = r[2]
        return out

    def _sha1_cache_path(self) -> Path:
        from .datcache import cache_dir
        return cache_dir() / "dat_sha1_cache.pkl"

    def _load_sha1_cache(self) -> dict:
        import pickle
        try:
            with open(self._sha1_cache_path(), "rb") as f:
                blob = pickle.load(f)
            if isinstance(blob, dict) and blob.get("version") == 1:
                return blob.get("hashes", {})
        except (OSError, pickle.PickleError, EOFError, AttributeError):
            pass
        return {}

    def _save_sha1_cache(self, hashes: dict, present: set[str]) -> None:
        import pickle
        hashes = {k: v for k, v in hashes.items() if k in present}   # prune
        p = self._sha1_cache_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".pkl.tmp")
            with open(tmp, "wb") as f:
                pickle.dump({"version": 1, "hashes": hashes}, f,
                            protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, p)
        except (OSError, pickle.PickleError):
            pass

    def _dedupe_collisions(self, files: list[Path], log,
                           sizes: dict[Path, int] | None = None,
                           sigs: dict[Path, tuple] | None = None,
                           sha1_cache: dict | None = None) -> list[Path]:
        """Identyczna treść DAT-a W TYM SAMYM TIERZE (katalogu ROMS/No-Intro/1G1R)
        => używamy JEDNEJ kopii (przypadkowy duplikat). Identyczny DAT w RÓŻNYCH
        tierach to NIE kolizja — to CELOWY układ (np. ROMS = rodzic z nazwami
        EmulationStation, No-Intro = dziecko z nazwami Redump); zostają OBA, a
        duplikaty plików ROM linkuje dedup (dziecko→rodzic), bez zajmowania miejsca.

        Optymalizacja: identyczne tylko przy tym samym rozmiarze — hashujemy
        WYŁĄCZNIE pliki o kolidującym rozmiarze. Pliki nietknięte. Rozmiary
        `sizes` (jeśli podane) pochodzą z jednego RÓWNOLEGŁEGO przebiegu stat
        w discover — bez nich robimy stat tutaj (fallback).
        """
        import hashlib
        by_size: dict[int, list[Path]] = {}
        for f in files:
            sz = sizes.get(f) if sizes is not None else None
            if sz is None:
                try:
                    sz = f.stat().st_size
                except OSError:
                    continue
            by_size.setdefault(sz, []).append(f)

        def _sha1(p: Path) -> str:
            key = str(Path(os.path.abspath(p)))
            sig = sigs.get(p) if sigs is not None else None
            if sha1_cache is not None and sig is not None:
                rec = sha1_cache.get(key)
                if rec and tuple(rec[:2]) == tuple(sig):
                    return rec[2]               # trafienie — bez odczytu z NAS
            h = hashlib.sha1()
            with open(p, "rb") as fh:
                while True:
                    b = fh.read(1 << 20)
                    if not b:
                        break
                    h.update(b)
            digest = h.hexdigest()
            if sha1_cache is not None and sig is not None:
                sha1_cache[key] = (sig[0], sig[1], digest)
            return digest

        chosen: list[Path] = []
        for size, group in by_size.items():
            if len(group) == 1:
                chosen.append(group[0])          # unikalny rozmiar — nie hashuj
                continue
            by_hash: dict[str, list[Path]] = {}
            for f in group:
                try:
                    by_hash.setdefault(_sha1(f), []).append(f)
                except OSError:
                    continue
            for paths in by_hash.values():
                # dedup TYLKO w obrębie tego samego tieru; różne tiery = zostają
                by_tier: dict[str, list[Path]] = {}
                for p in paths:
                    by_tier.setdefault(self._top_tier(p), []).append(p)
                for tier, tpaths in by_tier.items():
                    win = min(tpaths,
                              key=lambda p: (-len(p.parts), str(p).lower()))
                    chosen.append(win)
                    if log:
                        for p in tpaths:
                            if p != win:
                                log(f"KOLIZJA DAT (identyczna treść, ten sam "
                                    f"katalog „{tier or '.'}”): "
                                    f"{p.relative_to(self.dat_root)} — używam "
                                    f"{win.relative_to(self.dat_root)}")
        return sorted(chosen)

    def discover(self, log=None, on_progress=None, cancel=None) -> list[DatEntry]:
        """Znajduje wszystkie *.dat (rekurencyjnie) i buduje hierarchię.

        Kolizje (identyczna treść w różnych katalogach) są scalane do jednej
        kopii. Kolejność wyniku wyznacza priorytet parent→child W OBRĘBIE
        PLATFORMY: DAT-y są grupowane po platformie (platform_key), a wewnątrz
        grupy większy (pełny Redump) jest przed mniejszymi (1G1R/tłumaczenia),
        chyba że ``_priorytet.txt`` mówi inaczej. Platformy nie kolidują między
        sobą, więc ich wzajemna kolejność jest bez znaczenia (tu: po nazwie
        platformy). Wczytuje DAT-y w całości (liczba ROM-ów).

        `cancel` (threading.Event) — przerywa fazy (m.in. przy zamknięciu
        programu), żeby proces nie wisiał na parsowaniu z NAS. Każda faza loguje
        postęp, więc start nie wygląda na zawieszony.
        """
        def _cancelled() -> bool:
            return cancel is not None and cancel.is_set()

        if not self.dat_root.is_dir():
            raise NotADirectoryError(f"'{self.dat_root}' nie jest katalogiem")
        if log:
            log("Wczytuję DAT-y: szukam plików .dat…")
        files = [f for f in sorted(self.dat_root.rglob("*.dat")) if f.is_file()]
        if _cancelled():
            return []

        # RÓWNOLEGŁY stat() — jeden przebieg dla WSZYSTKICH DAT-ów. Na NAS/SMB
        # sekwencyjny stat 600+ plików to ~1 runda SMB na plik (dziesiątki
        # sekund); pula wątków ukrywa latencję. Sygnatury (mtime_ns, size) idą
        # potem i do dedupu, i do walidacji cache — bez drugiego stat.
        if log:
            log(f"Wczytuję DAT-y: sprawdzam sygnatury {len(files)} plików…")
        sigs: dict[Path, tuple] = self._stat_sigs(files, log)
        sizes = {f: s[1] for f, s in sigs.items()}
        if _cancelled():
            return []
        # SHA-1 kolidujących DAT-ów cache'owany po sygnaturze — identyczne DAT-y
        # ROMS/No-Intro (celowy układ) kolidują ZAWSZE; bez cache były
        # re-hashowane z NAS przy każdym wczytaniu (~36 s pierwszy raz).
        sha1c = self._load_sha1_cache() if self.use_cache else None
        if log:
            log("Wczytuję DAT-y: sprawdzam kolizje (przy pierwszym uruchomieniu "
                "liczę sumy — jednorazowo, ~30 s)…")
        files = self._dedupe_collisions(files, log, sizes=sizes,
                                        sigs=sigs, sha1_cache=sha1c)
        if sha1c is not None:
            self._save_sha1_cache(sha1c, {str(Path(os.path.abspath(f)))
                                          for f in sigs})
        if _cancelled():
            return []

        # Sidecary JSON RomVaulta jednym przebiegiem (rglob + równoległy odczyt),
        # nie glob per katalog na NAS (11 katalogów × ~5 s = ~53 s).
        if log:
            log("Wczytuję DAT-y: metadane JSON…")
        sidecars = self._sidecar_index(sigs, log)
        if _cancelled():
            return []

        cache = None
        cached = reparsed = 0
        if self.use_cache:
            from .datcache import DatParseCache
            # przy pierwszym starcie po aktualizacji: migracja monolitu →
            # pliki per DAT (loguje „Migruję…"), żeby start nie milczał.
            cache = DatParseCache(log=log)

        entries: list[DatEntry] = []
        skipped = 0
        for i, dat in enumerate(files):
            if _cancelled():
                if log:
                    log(f"PRZERWANO wczytywanie DAT-ów na {i}/{len(files)}.")
                break
            if on_progress:
                on_progress(i, len(files), dat.name)
            # Uszkodzony/pusty/nie-XML DAT NIE może wywalić całego skanu —
            # pomijamy go z komunikatem, reszta kolekcji wczytuje się normalnie.
            try:
                sig = sigs.get(dat)
                if cache is not None:
                    hit = cache.get(dat, sig=sig)   # sig z równoległego stat
                    if hit is not None:
                        raw_name, games = hit
                        cached += 1
                    else:
                        raw_name, games = cache.parse(dat, sig=sig)  # parsuje + zapis
                        reparsed += 1
                else:
                    raw_name = parse_dat_header(dat).get("name") or dat.stem
                    games = list(parse_dat(dat))
            except Exception as e:                      # noqa: BLE001
                skipped += 1
                if log:
                    log(f"POMIJAM uszkodzony DAT (nie sparsowano): {dat} — "
                        f"{type(e).__name__}: {e}")
                continue
            if not games:                               # pusty / nie-DAT / śmieci
                skipped += 1
                if log:
                    log(f"POMIJAM DAT bez gier (pusty/nieczytelny): {dat}")
                continue
            name = _safe_dirname(raw_name)
            rel = dat.parent.relative_to(self.dat_root)
            e = DatEntry(dat_path=dat, name=name,
                         target_dir=self.rom_root / rel / name)
            e.games = games                            # już sparsowane
            e.meta = sidecars.get(str(dat.parent), {}).get(dat.name, {})
            entries.append(e)

        if cache is not None:
            cache.prune({str(Path(os.path.abspath(f))) for f in files})
            cache.save()
            if log:
                log(f"Cache DAT-ów: z cache {cached}, sparsowano od nowa "
                    f"{reparsed} (katalog: {cache.dir}).")
        if skipped and log:
            log(f"UWAGA: pominięto {skipped} uszkodzonych DAT-ów "
                f"(puste/nie-XML) — patrz komunikaty wyżej.")

        return self.sort_entries(entries)

    def sort_entries(self, entries: list) -> list:
        """Porządek przetwarzania DAT-ów (= priorytet rodzic → dzieci), w miejscu.

        Kolejność katalogów z drzewa (_kolejnosc.json) → platforma → ręczny
        _priorytet.txt → większy DAT. Wołane przez
        `discover` i przez GUI po przesunięciu katalogu (bez ponownego skanu)."""
        manual = self._manual_priority()

        def _manual_rank(e: DatEntry) -> int:
            keys = (e.dat_path.name.lower(), e.dat_path.stem.lower(),
                    e.name.lower())
            for i, want in enumerate(manual):
                if want in keys:
                    return i
            return len(manual)

        from .dirrules import DirRules
        from .folder_order import folder_rank, load_order
        rules = DirRules(self.dat_root)
        order = load_order(self.dat_root)

        def _folder_rank(e: DatEntry) -> tuple:
            # KOLEJNOŚĆ KATALOGÓW z drzewa (_kolejnosc.json): katalog wyżej =
            # pierwszeństwo nad niższymi (ROMS → No-intro → 1G1R).
            return folder_rank(e.dat_path, self.dat_root, order) if order else ()

        # Dalej: platforma (Z ALIASAMI z reguły `platform`) → ręczny
        # _priorytet.txt → większy DAT. Między platformami kolejność nie ma
        # znaczenia (hierarchia nie linkuje między platformami).
        entries.sort(key=lambda e: (_folder_rank(e),
                                    effective_platform_key(e, rules),
                                    _manual_rank(e), -e.rom_count,
                                    str(e.target_dir).lower()))
        return entries

    def iter_loaded(self) -> Iterator[DatEntry]:
        for e in self.discover():
            yield e.load()
