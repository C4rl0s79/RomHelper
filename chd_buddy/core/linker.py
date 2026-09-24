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


def create_link(link_path: Path, target: Path, is_dir: bool,
                *, prefer_hardlink: bool = True) -> None:
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
    wskazuje drzewo na INNYM woluminie (serwer)."""
    if prefer_hardlink and not is_dir and _same_volume(link_path, target):
        try:
            os.link(str(target), str(link_path))
            return
        except OSError:
            pass                    # cross-volume / brak wsparcia → symlink niżej
    try:
        os.symlink(str(target), str(link_path), target_is_directory=is_dir)
    except OSError as e:
        if getattr(e, "winerror", None) == 1314:
            raise LinkPrivilegeError(_PRIVILEGE_HINT) from e
        raise


def remove_link(path: Path) -> bool:
    """Usuwa wpis TYLKO jeśli jest linkiem. Zwraca True gdy usunięto."""
    if not is_link(path):
        return False
    if path.is_dir():
        os.rmdir(path)   # rmdir na symlinku katalogu usuwa link, nie zawartość
    else:
        os.unlink(path)
    return True


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
        seen: set = set()
        for root in roots:
            if not root or not Path(root).is_dir():
                continue
            try:
                rows = list(index.all_under(root, physical_only=False))
            except Exception:
                rows = []
            for row in rows:
                if cancel is not None and cancel.is_set():
                    return removed
                try:
                    if not row["is_link"]:
                        continue
                except (KeyError, IndexError):
                    continue
                p = Path(row["path"])
                k = os.path.normcase(str(p))
                if k in seen:
                    continue
                seen.add(k)
                checked += 1
                if log and checked % 2000 == 0:
                    log(f"  …sprawdzono {checked} linków (zerwanych: {removed})")
                if link_is_broken(p):       # po CELU (readlink), nie po podążaniu
                    _drop(p)
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


