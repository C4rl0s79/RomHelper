"""RAM dysk (ImDisk) na operacje tymczasowe: wypakowanie/przepakowanie CHD.

Wszystkie ciężkie ekstrakcje (identyfikacja CD-CHD, przepakowanie kontenera,
round-trip) lądują na ulotnym dysku w RAM zamiast na fizycznym NTFS. Dzięki
temu: nie zapychają dysku kolekcji, nic nie zostaje po przerwaniu (brak
utraconych klastrów), i jest szybciej.

Cykl życia: tworzymy przy starcie programu (inicjalizacja chwilę trwa),
usuwamy przy zamknięciu. Gdy plik nie mieści się w RAM albo ImDisk nie ma —
scratch spada na fizyczny dysk z wolnym miejscem (patrz scratch.py).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

LogCB = Callable[[str], None]
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Aktywny RAM dysk (ścieżka korzenia) — ustawiany po utworzeniu, czyszczony
# po usunięciu. scratch.py preferuje go, gdy plik się mieści.
_ACTIVE: Optional[Path] = None
# Zapamiętane parametry ostatniego RAM dysku — do ODTWORZENIA, gdy zniknie nagle
# w trakcie (np. odmontowany przez inną instancję/AV). Patrz remount().
_SIZE_GB: int = 40
_LETTER: str = "R"


def _imdisk_exe() -> Optional[str]:
    exe = shutil.which("imdisk")
    if exe:
        return exe
    cand = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "imdisk.exe"
    return str(cand) if cand.is_file() else None


def available() -> bool:
    return _imdisk_exe() is not None


def active_root() -> Optional[Path]:
    """Korzeń aktywnego RAM dysku albo None.

    Gdy `_ACTIVE` nie jest ustawione W TYM procesie (create() szło w tle i skan
    ruszył zanim skończyło; albo relaunch elewacji zaczął od nowa) — RAM-dysk i
    tak MOŻE być już zamontowany. Bez tej detekcji `pick_scratch_root` pomijał
    ramdysk i chdman pisał temp na NVMe (user: „nic nie ląduje na R:, wielki plik
    w temp"). Więc: gdy `_ACTIVE` puste, sprawdź zapamiętaną literę — jeśli <L>:
    istnieje i jest ZAPISYWALNY, uznaj za aktywny i zapamiętaj (dalsze wywołania
    idą już szybką ścieżką)."""
    global _ACTIVE
    if _ACTIVE is not None and _ACTIVE.is_dir():
        return _ACTIVE
    root = Path(f"{_LETTER}:\\")
    if _ready(root):
        _ACTIVE = root
        return root
    return None


def reuse_if_exists(letter: str = "R") -> Optional[Path]:
    """Szybko (bez subprocess) rejestruje ISTNIEJĄCY, zapisywalny wolumin
    <letter>: jako aktywny RAM dysk. Do wywołania SYNCHRONICZNIE na starcie —
    dzięki temu scratch widzi RAM dysk z poprzedniej sesji od razu, nawet zanim
    dokończy się pełne create() w tle."""
    global _ACTIVE, _LETTER
    _LETTER = letter
    root = Path(f"{letter}:\\")
    if _ready(root):
        _ACTIVE = root
        return root
    return None


def _writable(root: Path) -> bool:
    try:
        probe = root / ".chdbuddy_probe"
        probe.write_bytes(b"x")
        probe.unlink()
        return True
    except OSError:
        return False


def _fs_name(root: Path) -> str:
    """Nazwa systemu plików woluminu (np. 'NTFS') przez WinAPI, albo '' gdy
    wolumin jest RAW/niesformatowany lub niedostępny.

    KLUCZOWE: sam write-probe potrafi mylnie „przejść" na świeżym woluminie RAW
    (goły imdisk.exe ignoruje `-p /fs`), który Explorer i tak pokazuje jako
    RAW/bez pojemności (patrz komentarz w create()). Dlatego GOTOWOŚĆ dysku
    weryfikujemy też realną nazwą FS — inaczej active_root()/reuse_if_exists()
    mogłyby oddać RAW-dysk jako scratch. Poza Windows zwraca '' (nie używane)."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        fsbuf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(str(root)), None, 0, None, None, None,
            fsbuf, len(fsbuf))
        return fsbuf.value if ok else ""
    except Exception:
        return ""


def _ready(root: Path) -> bool:
    """Wolumin zamontowany, ZE ZNANYM systemem plików i zapisywalny.

    Na Windows wymagamy realnej nazwy FS (nie RAW) — write-probe sam w sobie
    bywa zwodniczy na świeżym RAW. Poza Windows: is_dir + zapis (jak dotąd)."""
    if not root.is_dir():
        return False
    if os.name == "nt" and not _fs_name(root):
        return False
    return _writable(root)


def _detach(exe: str, drive: str) -> None:
    """Zdejmuje urządzenie ImDisk z litery `drive` (np. gdy RAW nie da się
    sformatować) — żeby móc utworzyć od nowa."""
    try:
        subprocess.run([exe, "-D", "-m", drive], capture_output=True, text=True,
                       encoding="oem", errors="replace", creationflags=_FLAGS)
        time.sleep(1.0)
    except OSError:
        pass


def _imdisk_has_device(exe: str, drive: str) -> bool:
    """Czy ImDisk MA urządzenie zamontowane na literze `drive` (nawet RAW)."""
    try:
        r = subprocess.run([exe, "-l", "-m", drive], capture_output=True,
                           text=True, encoding="oem", errors="replace",
                           creationflags=_FLAGS)
        return r.returncode == 0
    except OSError:
        return False


def _format_volume(letter: str, label: str, log: Optional[LogCB] = None) -> bool:
    """Formatuje wolumin `letter:` na NTFS BEZ promptów (Format-Volume). ImDisk
    bez Toolkitu tworzy dysk RAW — musimy sformatować sami. Zwraca True gdy
    wolumin jest po tym zapisywalny."""
    root = Path(f"{letter}:\\")
    ps = ("powershell", "-NoProfile", "-NonInteractive", "-Command",
          f"Format-Volume -DriveLetter {letter} -FileSystem NTFS "
          f"-NewFileSystemLabel {label} -Confirm:$false -Force")
    try:
        subprocess.run(ps, capture_output=True, text=True, encoding="oem",
                       errors="replace", creationflags=_FLAGS, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as e:
        if log:
            log(f"RAM dysk: formatowanie {letter}: nieudane ({e}).")
        return False
    for _ in range(15):                           # daj chwilę na „przyswojenie" FS
        if _ready(root):
            return True
        time.sleep(0.4)
    return _ready(root)


def create(size_gb: int = 40, letter: str = "R", label: str = "RAMTEMP",
           timeout: float = 20.0, log: Optional[LogCB] = None,
           attempts: int = 4, retry_wait: float = 3.0) -> Optional[Path]:
    """Tworzy RAM dysk ImDisk i zwraca jego korzeń (albo None).

    imdisk -a -s <N>G -m <L>: -p "/fs:ntfs /q /y /v:<label>"
    Czeka aż wolumin będzie zamontowany i ZAPISYWALNY.

    Odporne na dwa realne stany:
    - litera zajęta przez ZALEGŁY wolumin RAW (po crashu/nieudanym formacie) —
      ImDisk zwraca wtedy mylący błąd 3 „Za mało zasobów pamięci". Zamiast
      tworzyć na zajętej literze — FORMATUJEMY istniejące urządzenie.
    - goły `imdisk.exe` (bez ImDisk Toolkit) IGNORUJE `-p /fs` i zostawia dysk
      RAW — po `imdisk -a` formatujemy sami (`Format-Volume`, bez promptów).
    """
    global _ACTIVE, _SIZE_GB, _LETTER
    _LETTER = letter                              # zapamiętaj do remount()
    exe = _imdisk_exe()
    if exe is None:
        if log:
            log("RAM dysk: brak ImDisk — operacje tymczasowe na dysku "
                "fizycznym z wolnym miejscem.")
        return None
    drive = f"{letter}:"
    root = Path(drive + "\\")
    last_err = ""
    for attempt in range(1, attempts + 1):
        # 1) już zamontowany i ZAPISYWALNY (poprzednia sesja/próba) → używamy
        if _ready(root):
            _ACTIVE = root
            _SIZE_GB = size_gb
            if log:
                log(f"RAM dysk: używam istniejącego {drive}")
            return root
        # 2) urządzenie ImDisk JEST, ale wolumin RAW (niesformatowany — częste,
        #    gdy poprzednie tworzenie/format nie dokończyło albo zostało po
        #    crashu). Formatujemy — NIE próbujemy tworzyć na ZAJĘTEJ literze
        #    (to daje mylący błąd 3 „Za mało zasobów pamięci").
        if _imdisk_has_device(exe, drive):
            # BEZPIECZEŃSTWO: formatuj TYLKO gdy wolumin naprawdę RAW (brak FS).
            # Gdy `_ready` padło, ale FS ISTNIEJE, to write-probe zawiódł tylko
            # PRZEJŚCIOWO — wolumin chwilowo zajęty (np. równoległe ekstrakcje
            # chdman piszą na R:). Reformatowanie zniszczyłoby te trwające
            # operacje innych wątków (remount po nieudanym mkdir mógł tu trafić).
            # Więc: sformatowany-ale-zajęty → uznaj za gotowy, NIE formatuj.
            if _fs_name(root):
                _ACTIVE = root
                _SIZE_GB = size_gb
                if log:
                    log(f"RAM dysk: {drive} zajęty, ale sformatowany "
                        f"({_fs_name(root)}) — używam bez formatowania.")
                return root
            if log:
                log(f"RAM dysk: {drive} istnieje, ale niesformatowany (RAW) — "
                    f"formatuję.")
            if _format_volume(letter, label, log=log):
                _ACTIVE = root
                _SIZE_GB = size_gb
                if log:
                    log(f"RAM dysk: gotowy {drive} (sformatowany).")
                return root
            _detach(exe, drive)                   # nie da się → zdejmij, od nowa
        # 3) utwórz ŚWIEŻY (z formatem przez -p, gdy ImDisk Toolkit to obsługuje)
        try:
            r = subprocess.run(
                [exe, "-a", "-s", f"{size_gb}G", "-m", drive,
                 "-p", f"/fs:ntfs /q /y /v:{label}"],
                capture_output=True, text=True, encoding="oem",
                errors="replace", creationflags=_FLAGS)
        except OSError as e:
            last_err = str(e)
            r = None
        if r is not None and r.returncode == 0:
            # `-a` zamontował URZĄDZENIE, ale NIE ufamy, że jest sformatowane:
            # goły imdisk.exe (bez ImDisk Toolkit) IGNORUJE `-p /fs` i zostawia
            # dysk RAW, a write-probe potrafi „przejść" na świeżym woluminie,
            # który Explorer i tak pokazuje jako RAW/bez pojemności (user MUSIAŁ
            # formatować RĘCZNIE). Dlatego czekamy tylko aż urządzenie SIĘ
            # POJAWI, po czym ZAWSZE formatujemy jawnie (Format-Volume; na pustym
            # ulotnym dysku szybki i nieszkodliwy) i dopiero wtedy uznajemy R:
            # za gotowy — „twórz od razu z formatowaniem", jak wymagał user.
            deadline = time.time() + timeout
            while time.time() < deadline:
                if _ready(root) or _imdisk_has_device(exe, drive):
                    break
                time.sleep(0.4)
            if _ready(root) or _imdisk_has_device(exe, drive):
                if _format_volume(letter, label, log=log):
                    _ACTIVE = root
                    _SIZE_GB = size_gb
                    if log:
                        log(f"RAM dysk: gotowy {drive} "
                            f"({size_gb} GB, sformatowany).")
                    return root
                last_err = "utworzony, ale formatowanie nie powiodło się"
            else:
                last_err = f"urządzenie nie pojawiło się w {timeout:.0f}s"
        elif r is not None:
            last_err = (f"ImDisk zwrócił {r.returncode}: "
                        f"{(r.stderr or r.stdout).strip()[:200]}")
        if attempt < attempts:
            if log:
                log(f"RAM dysk: próba {attempt}/{attempts} nieudana "
                    f"({last_err}) — czekam {retry_wait:.0f}s i ponawiam.")
            time.sleep(retry_wait)
    if log:
        log(f"RAM dysk: nie utworzono {drive} po {attempts} próbach "
            f"({last_err}). Operacje tymczasowe pójdą na dysk fizyczny.")
    return None


def remount(log: Optional[LogCB] = None) -> Optional[Path]:
    """Odtwarza RAM dysk z ZAPAMIĘTANYCH parametrów (rozmiar+litera) po jego
    nagłym zniknięciu w trakcie pracy. Jedna szybka próba (bez długich retry),
    żeby nie blokować operacji. Zwraca korzeń albo None."""
    if active_root() is not None:                # już jest — nic nie rób
        return _ACTIVE
    if not available():
        return None
    if log:
        log(f"RAM dysk: {_LETTER}: zniknął w trakcie — próbuję odtworzyć.")
    return create(size_gb=_SIZE_GB, letter=_LETTER, log=log,
                  attempts=1, retry_wait=0.0)


def remove(letter: str = "R", log: Optional[LogCB] = None,
           attempts: int = 3) -> None:
    """Usuwa RAM dysk (imdisk -D -m <L>:) — wywołać przy zamknięciu programu.

    ODPORNIE: `-D` (wymuszony detach) potrafi „odbić się", gdy wolumin jest
    jeszcze ZAJĘTY (uchwyty po świeżo zakończonych ekstrakcjach chdman na R:,
    procesy potomne nie do końca zwolnione). Dawniej błąd był POŁYKANY i R:
    zostawał. Teraz sprawdzamy kod wyniku i istnienie woluminu, ponawiamy z
    krótką przerwą i logujemy wynik (widać, jeśli naprawdę się nie da)."""
    global _ACTIVE
    _ACTIVE = None
    exe = _imdisk_exe()
    if exe is None:
        return
    drive = f"{letter}:"
    root = Path(drive + "\\")
    if not root.exists():
        return
    last = ""
    for i in range(1, max(1, attempts) + 1):
        try:
            r = subprocess.run([exe, "-D", "-m", drive],
                               capture_output=True, text=True, encoding="oem",
                               errors="replace", creationflags=_FLAGS)
            last = (r.stderr or r.stdout or "").strip()
        except OSError as e:
            last = str(e)
        time.sleep(0.6)
        if not root.exists():
            if log:
                log(f"RAM dysk: usunięty {drive}"
                    + (f" (próba {i})" if i > 1 else "") + ".")
            return
    # wciąż jest — zwykle uchwyty trzymane przez WŁASNY, jeszcze niezakończony
    # proces; zwolnią się przy wyjściu, a następny start i tak go przejmie/
    # sformatuje (create() obsługuje reuse/RAW). Logujemy, nie wisimy.
    if log:
        log(f"RAM dysk: {drive} nadal zajęty, nie odmontowano teraz"
            + (f" ({last})" if last else "")
            + " — zwolni się przy wyjściu / następny start go przejmie.")
