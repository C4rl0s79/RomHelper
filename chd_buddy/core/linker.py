"""Symlinki: bezpieczny mirror drzewa ROM-ów + deduplikacja linkami.

Port logiki z retrobat_safe_linker.ps1 (mirror katalogów systemów z serwera
do lokalnego drzewa RetroBata) + nowa deduplikacja: identyczne fizycznie pliki
(wg indeksu SQLite) są zastępowane symlinkami do jednej kopii.

Twarda zasada bezpieczeństwa (jak w skrypcie PS1): moduł USUWA wyłącznie
reparse pointy (symlinki/junctions). Zwykłego pliku ani katalogu nie ruszy —
najwyżej go pominie i policzy w statystykach.

Symlinki na Windows wymagają uprawnienia (tryb dewelopera albo uruchomienie
jako administrator) — brak uprawnień zgłaszamy czytelnie jako
LinkPrivilegeError zamiast tajemniczego WinError 1314.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from .fileindex import is_reparse_stat

# Katalogi lokalnych materiałów RetroBata — nigdy nie linkowane/nie czyszczone.
DEFAULT_EXCLUDES = ("images", "manuals", "videos")

LogCB = Callable[[str], None]

_PRIVILEGE_HINT = (
    "Brak uprawnień do tworzenia symlinków. Włącz tryb dewelopera "
    "(Ustawienia → System → Dla deweloperów) albo uruchom program "
    "jako administrator."
)


class LinkPrivilegeError(OSError):
    """WinError 1314 — proces nie ma prawa tworzyć symlinków."""


def is_link(path: Path) -> bool:
    """Czy ścieżka jest reparse pointem (symlink/junction)."""
    try:
        return is_reparse_stat(os.lstat(path))
    except OSError:
        return False


def link_target(path: Path) -> Optional[str]:
    """Absolutny CEL symlinku (rozwiązany względem katalogu linku), albo None."""
    try:
        tgt = os.readlink(str(path))
    except OSError:
        return None
    if not os.path.isabs(tgt):
        tgt = os.path.join(os.path.dirname(str(path)), tgt)
    return tgt.replace("\\\\?\\", "")


def link_is_broken(path: Path) -> bool:
    """Czy symlink jest ZERWANY — sprawdzając ISTNIENIE CELU (readlink→target),
    a NIE podążając za linkiem. Kluczowe na SMB: przy wyłączonej ocenie R2R
    Windows NIE podąża za linkiem remote→remote, więc `path.exists()` zwraca
    False nawet dla POPRAWNEGO linku → dawniej kasowaliśmy dobre linki. Cel
    sprawdzamy jako zwykłą ścieżkę (lexists), więc działa niezależnie od R2R."""
    tgt = link_target(path)
    if tgt is None:
        return False                  # nie odczytano celu — nie zgaduj „zerwany"
    return not os.path.lexists(tgt)


def same_file(a: Path, b: Path) -> bool:
    """Czy dwie ścieżki wskazują TĘ SAMĄ fizyczną treść — hardlink (ten sam
    st_dev+st_ino) albo symlink jednej do drugiej. Pozwala rozpoznać „już
    zlinkowane" przy powtórnym uruchomieniu: hardlink NIE jest reparse pointem,
    więc `is_link` go nie wykryje, a bez tego dziecko byłoby błędnie uznane za
    'zwykły plik' (KONFLIKT / zbędna przebudowa fizyczna)."""
    try:
        sa = os.stat(a)
        sb = os.stat(b)
    except OSError:
        return False
    return (sa.st_ino != 0 and sa.st_ino == sb.st_ino
            and sa.st_dev == sb.st_dev)


def _same_volume(a: Path, b: Path) -> bool:
    """Czy dwie ścieżki są na TYM SAMYM woluminie (litera dysku albo UNC share).
    `splitdrive` daje 'C:' dla liter i '\\\\serwer\\share' dla UNC — porównanie
    obu obejmuje więc też NAS-a (hardlink przez SMB działa w obrębie share)."""
    da = os.path.splitdrive(os.path.abspath(str(a)))[0]
    db = os.path.splitdrive(os.path.abspath(str(b)))[0]
    return bool(da) and os.path.normcase(da) == os.path.normcase(db)


# błędy oznaczające „hardlink tu NIEMOŻLIWY" (a nie chwilową awarię):
# 1 ERROR_INVALID_FUNCTION, 17 ERROR_NOT_SAME_DEVICE, 50 ERROR_NOT_SUPPORTED,
# 1142 ERROR_TOO_MANY_LINKS
_NO_HARDLINK_WINERR = {1, 17, 50, 1142}


def create_link(link_path: Path, target: Path, is_dir: bool,
                *, prefer_hardlink: bool = True) -> str:
    """Łączy `link_path` z treścią `target`.

    Dla PLIKÓW na tym samym woluminie preferujemy HARDLINK (`os.link`): nie
    wymaga trybu dewelopera/administratora (WinError 1314) i działa tam, gdzie
    symlinki nie (np. SMB Z:). Hardlink to równorzędny wpis katalogowy tej samej
    treści — z punktu widzenia indeksu/dedupu zwykły plik (nie reparse point).
    Symlink jest fallbackiem: inny wolumin, katalog, albo gdy hardlink odmówi
    (EXDEV / serwer bez wsparcia).

    `prefer_hardlink=False` wymusza symlink — dla mirror_tree (RetroBat), które
    polega na semantyce reparse pointa: bezpiecznie usuwa TYLKO stworzone przez
    siebie linki (is_link), nie tykając prawdziwych plików usera, i z założenia
    wskazuje drzewo na INNYM woluminie (serwer).

    Zwraca "hard" albo "sym". Zajęta ścieżka / brak katalogu → FileExistsError /
    FileNotFoundError od razu (bez zbędnej próby symlinku)."""
    if prefer_hardlink and not is_dir and _same_volume(link_path, target):
        try:
            os.link(str(target), str(link_path))
            return "hard"
        except OSError as e:
            # TEN SAM wolumin = TYLKO hardlink. Symlink wolno wyłącznie, gdy
            # system JAWNIE nie obsługuje hardlinków (inny wolumin mimo litery,
            # brak funkcji). Dawniej KAŻDY błąd (np. chwilowa czkawka SMB przy
            # równoległych linkach) po cichu robił symlink — a user chce w
            # kolekcji wyłącznie hardlinki (29.09).
            import errno as _errno
            if (getattr(e, "winerror", None) not in _NO_HARDLINK_WINERR
                    and e.errno not in (_errno.EXDEV, _errno.EMLINK)):
                raise
    try:
        os.symlink(str(target), str(link_path), target_is_directory=is_dir)
    except OSError as e:
        if getattr(e, "winerror", None) == 1314:
            raise LinkPrivilegeError(_PRIVILEGE_HINT) from e
        raise
    return "sym"


def remove_link(path: Path) -> bool:
    """Usuwa wpis TYLKO jeśli jest linkiem. Zwraca True gdy usunięto."""
    if not is_link(path):
        return False
    if path.is_dir():
        os.rmdir(path)   # rmdir na symlinku katalogu usuwa link, nie zawartość
    else:
        os.unlink(path)
    return True


def replace_with_hardlink(path: Path, target: Path) -> Optional[OSError]:
    """`path` staje się HARDLINKIEM `target` — ATOMOWO: hardlink pod nazwą
    tymczasową, potem os.replace w miejsce starego wpisu (symlinku albo
    dawnego hardlinku). Żadnej chwili bez pliku; bez uprawnień administratora.
    Zwraca błąd (stary wpis nietknięty) albo None."""
    tmp = Path(str(path) + ".rh_hardlink_tmp")
    try:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        os.link(str(target), str(tmp))
    except OSError as e:
        return e
    try:
        os.replace(str(tmp), str(path))
        return None
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return e


def hardlink_twins(path, index) -> list:
    """Inne nazwy TEGO SAMEGO pliku fizycznego (hardlinki) — kandydaci z
    indeksu (ta sama suma i rozmiar), potwierdzeni `same_file`. Wołać PRZED
    podmianą pliku w miejscu: nowy plik to inny plik na dysku, więc jego
    dawne hardlinki zostałyby ze STARĄ treścią (dziecko z zipem zstd/CHD-CD
    obok przepakowanego rodzica = druga kopia fizyczna i ponowna praca)."""
    if index is None:
        return []
    key = str(Path(os.path.abspath(str(path))))
    try:
        cands = index.same_content(key)
    except Exception:
        return []
    out = []
    for cand in cands:
        try:
            if same_file(Path(cand), Path(key)):
                out.append(cand)
        except OSError:
            continue
    return out


def relink_twins(path, twins, index=None, log: Optional[LogCB] = None) -> int:
    """PO podmianie `path` w miejscu: każdy dawny hardlink (`hardlink_twins`)
    znów wskazuje NOWY plik; wpis indeksu z danymi nowego pliku. Zwraca ile."""
    n = 0
    for t in twins or ():
        err = replace_with_hardlink(Path(t), Path(path))
        if err is not None:
            if log:
                log(f"  BŁĄD przepięcia hardlinku {t}: {err}")
            continue
        n += 1
        if index is not None:
            try:
                index.record_hardlink(t, path)
            except Exception:
                pass
        if log:
            log(f"  hardlink przepięty na nowy plik: {t}")
    return n


def remove_broken_links(roots, index=None, log: Optional[LogCB] = None,
                        cancel=None) -> int:
    """Usuwa ZERWANE symlinki (cel nie istnieje) w podanych korzeniach.

    Powstają, gdy plik-cel zostaje przeniesiony/skonwertowany/skasowany po
    utworzeniu linku (np. luźna ścieżka rodzica zjedzona przez konwersję do
    CHD). Zerwany link nic nie wskazuje i psuje konwersje/skróty — kasujemy
    go; poprawny link zostanie odtworzony przy naprawie, gdy cel wróci.

    Z INDEKSEM: sprawdzamy TYLKO znane linki (`is_link`) — `exists()` woła się
    wyłącznie na nich (garść), zamiast `os.walk` + stat na KAŻDYM pliku (na NAS
    to 100k+ zapytań = minuty ciszy w „Start…"). `cancel` przerywa responsywnie.
    Bez indeksu: fallback na os.walk (też z cancel)."""
    removed = 0
    checked = 0

    def _drop(p: Path) -> bool:
        nonlocal removed
        try:
            remove_link(p)
        except OSError as e:
            if log:
                log(f"nie usunięto zerwanego linku {p}: {e}")
            return False
        if index is not None:
            try:
                index.remove_path(p)
            except OSError:
                pass
        removed += 1
        if log:
            log(f"USUNIĘTO zerwany link: {p}")
        return True

    if index is not None:
        # ZNANE SYMLINKI z indeksu → RÓWNOLEGLE (NAS przez internet: jedna
        # runda SMB na link szeregowo = minuty). Każdy symlink:
        #  - cel NIE istnieje → usuń (zerwany),
        #  - cel istnieje na TYM SAMYM woluminie → zamień na HARDLINK (w
        #    kolekcji mają być wyłącznie hardlinki — user 29.09; symlink na SMB
        #    to zależność od celu i rundy NAS przy każdym dopasowaniu),
        #  - inny wolumin → zostaw.
        # I/O w wątkach, indeks tylko w wątku wołającym (SQLite jednowątkowe).
        from concurrent.futures import ThreadPoolExecutor
        paths: list = []
        seen: set = set()
        for root in roots:
            if not root or not Path(root).is_dir():
                continue
            try:
                rows = list(index.all_under(root, physical_only=False))
            except Exception:
                rows = []
            for row in rows:
                try:
                    if not row["is_link"]:
                        continue
                except (KeyError, IndexError):
                    continue
                k = os.path.normcase(row["path"])
                if k not in seen:
                    seen.add(k)
                    paths.append(Path(row["path"]))
        if log and paths:
            log(f"Symlinki w kolekcji: {len(paths)} — zerwane usuwam, pozostałe "
                f"zamieniam na hardlinki…")

        def _one(p: Path):
            if cancel is not None and cancel.is_set():
                return ("skip", p, None)
            tgt = link_target(p)
            if tgt is None:
                return ("skip", p, None)
            if not os.path.lexists(tgt):
                try:
                    remove_link(p)
                    return ("removed", p, None)
                except OSError as e:
                    return ("error", p, e)
            if not _same_volume(p, Path(tgt)) or os.path.isdir(tgt):
                return ("skip", p, None)
            err = replace_with_hardlink(p, Path(tgt))
            return ("error", p, err) if err else ("hard", p, tgt)

        converted = 0
        with ThreadPoolExecutor(16) as ex:
            for kind, p, info in ex.map(_one, paths):
                checked += 1
                if log and checked % 2000 == 0:
                    log(f"  …sprawdzono {checked} linków (zerwanych: {removed}, "
                        f"zamienionych: {converted})")
                if kind == "removed":
                    removed += 1
                    if index is not None:
                        try:
                            index.remove_path(p)
                        except Exception:
                            pass
                    if log:
                        log(f"USUNIĘTO zerwany link: {p}")
                elif kind == "hard":
                    converted += 1
                    try:
                        index.remove_path(p)          # wpis symlinku precz
                        index.record_hardlink(p, info)  # hardlink z danymi celu
                    except Exception:
                        pass
                    if log:
                        log(f"ZAMIENIONO symlink → hardlink: {p}")
                elif kind == "error" and log:
                    log(f"nie obsłużono linku {p}: {info}")
        if log and paths:
            log(f"Symlinki: usunięto zerwanych {removed}, zamieniono na "
                f"hardlinki {converted}.")
        return removed

    # BEZ indeksu: pełny os.walk (rzadka ścieżka), też z cancel
    for root in roots:
        if not root or not Path(root).is_dir():
            continue
        for dirpath, _dn, filenames in os.walk(root):
            if cancel is not None and cancel.is_set():
                return removed
            for name in filenames:
                p = Path(dirpath) / name
                if is_link(p) and link_is_broken(p):
                    _drop(p)
    return removed


# --- Mirror drzewa (serwer -> lokalny RetroBat) ------------------------------

@dataclass
class MirrorStats:
    created: int = 0
    removed_stale: int = 0
    skipped_existing: int = 0   # link już jest (bez --force nie ruszamy)
    skipped_normal: int = 0     # zwykły plik/katalog w celu — nietykalny
    errors: int = 0

    def summary(self) -> str:
        return (f"utworzono {self.created}, usunięto nieaktualne {self.removed_stale}, "
                f"istniejące {self.skipped_existing}, pominięte zwykłe {self.skipped_normal}, "
                f"błędy {self.errors}")


def mirror_tree(
    source_root: Path,
    target_root: Path,
    *,
    exclude_names: Sequence[str] = DEFAULT_EXCLUDES,
    rebuild: bool = False,
    force: bool = False,
    dry_run: bool = False,
    log: Optional[LogCB] = None,
) -> MirrorStats:
    """Mirroruje katalogi systemów: target/<system>/<wpis> -> source/<system>/<wpis>.

    Katalogi systemów (poziom 1) są tworzone jako PRAWDZIWE katalogi, ich
    zawartość (poziom 2: pliki i podkatalogi) jako symlinki. Tryby:
    - sync (domyślny): usuń nieaktualne linki, dodaj brakujące;
    - rebuild: najpierw usuń WSZYSTKIE zarządzane linki, potem utwórz od nowa.
    """
    src = Path(os.path.abspath(source_root))
    dst = Path(os.path.abspath(target_root))
    if not src.is_dir():
        raise NotADirectoryError(f"'{src}' nie jest katalogiem")
    excl = {e.lower() for e in exclude_names}
    stats = MirrorStats()

    def _log(msg: str) -> None:
        if log:
            log(msg)

    if not dry_run:
        dst.mkdir(parents=True, exist_ok=True)

    for system in sorted(p for p in src.iterdir() if p.is_dir()):
        if system.name.lower() in excl:
            continue
        sys_dst = dst / system.name
        if not dry_run:
            sys_dst.mkdir(exist_ok=True)

        # 1) czyszczenie: rebuild = wszystkie linki; sync = tylko osierocone
        if sys_dst.is_dir():
            for entry in sys_dst.iterdir():
                if entry.name.lower() in excl or not is_link(entry):
                    continue
                stale = rebuild or not (system / entry.name).exists()
                if not stale:
                    continue
                _log(f"USUŃ LINK  {entry}")
                if not dry_run:
                    try:
                        remove_link(entry)
                    except OSError as e:
                        stats.errors += 1
                        _log(f"BŁĄD usuwania {entry}: {e}")
                        continue
                stats.removed_stale += 1

        # 2) tworzenie brakujących linków
        for entry in sorted(system.iterdir()):
            if entry.name.lower() in excl:
                continue
            to = sys_dst / entry.name
            try:
                exists = os.path.lexists(to)
            except OSError:
                exists = False
            if exists:
                if is_link(to):
                    if force:
                        _log(f"NADPISZ    {to}")
                        if not dry_run:
                            remove_link(to)
                            create_link(to, entry, entry.is_dir(),
                                        prefer_hardlink=False)
                        stats.created += 1
                    else:
                        stats.skipped_existing += 1
                else:
                    stats.skipped_normal += 1
                    _log(f"POMIŃ ZWYKŁY  {to}")
                continue
            _log(f"LINK       {to} -> {entry}")
            if not dry_run:
                try:
                    create_link(to, entry, entry.is_dir(),
                                prefer_hardlink=False)
                except LinkPrivilegeError:
                    raise
                except OSError as e:
                    stats.errors += 1
                    _log(f"BŁĄD linku {to}: {e}")
                    continue
            stats.created += 1

    return stats


