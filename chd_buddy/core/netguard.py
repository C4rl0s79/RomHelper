"""Straż dostępności NAS (dysk sieciowy) podczas długich operacji.

Laptop z zamkniętą pokrywą przy zaniku prądu przechodzi w uśpienie; po
wybudzeniu dysk sieciowy (Z:) wraca dopiero, gdy router/NAS wstaną. Bez straży
operacje w tym czasie sypały błędami (a skan gubił całe katalogi jako
„brakujące"). Tu: wykrycie niedostępności i CZEKANIE aż wolumin wróci, z jasnym
komunikatem w logu i na pasku — praca wznawia się sama, bez udziału usera.

Użycie:
- `configure(roots, log, status, cancel)` na starcie zadania (GUI robi to w
  `FnWorker`), `reset()` na końcu;
- `call(fn, *paths)` — operacja plikowa z ponowieniem po powrocie NAS;
- `checkpoint()` — tani punkt kontrolny w pętlach (sprawdza co CHECK_EVERY s);
- `wait_until_back(paths)` — gdy kod sam wykrył problem.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Iterable, Optional

# kody Windows oznaczające zerwanie/niedostępność zasobu sieciowego
NET_WINERR = {
    21,     # ERROR_NOT_READY (wolumin chwilowo niegotowy)
    51,     # ERROR_REM_NOT_LIST
    53,     # ERROR_BAD_NETPATH
    54,     # ERROR_NETWORK_BUSY
    55,     # ERROR_DEV_NOT_EXIST
    59,     # ERROR_UNEXP_NET_ERR
    64,     # ERROR_NETNAME_DELETED
    65,     # ERROR_NETWORK_ACCESS_DENIED
    67,     # ERROR_BAD_NET_NAME
    121,    # ERROR_SEM_TIMEOUT
    1130,   # ERROR_NOT_ENOUGH_SERVER_MEMORY
    1231,   # ERROR_NETWORK_UNREACHABLE
    1232,   # ERROR_HOST_UNREACHABLE
    1236,   # ERROR_CONNECTION_ABORTED
    2250,   # ERROR_NOT_CONNECTED
}

CHECK_EVERY = 20.0      # s — jak często checkpoint faktycznie pyta wolumin
POLL = 5.0              # s — odstęp prób w czasie czekania
STABLE = 2              # ile kolejnych udanych prób = „wrócił na dobre"
REMIND = 300.0          # s — przypomnienie w logu w czasie długiego czekania


class NasOffline(OSError):
    """NAS nie wrócił, a czekanie przerwano (Przerwij)."""


_lock = threading.Lock()            # jedno czekanie naraz (reszta wątków stoi)
_state: dict = {"roots": [], "log": None, "status": None, "cancel": None,
                "last": 0.0}


def anchor(path) -> str:
    """Korzeń woluminu: „Z:\\" albo „\\\\serwer\\udział\\"."""
    p = os.path.abspath(str(path))
    drive, _ = os.path.splitdrive(p)
    return (drive + os.sep) if drive else p


def configure(roots: Iterable = (), log: Optional[Callable[[str], None]] = None,
              status: Optional[Callable[[str], None]] = None,
              cancel=None) -> None:
    anchors: list[str] = []
    for r in roots or ():
        if not r:
            continue
        a = anchor(r)
        # obserwujemy tylko woluminy ŻYWE na starcie — odłączony od początku
        # dysk nie może wstrzymać całej pracy w nieskończoność
        if a not in anchors and alive(a):
            anchors.append(a)
    _state.update(roots=anchors, log=log, status=status, cancel=cancel,
                  last=time.monotonic())


def reset() -> None:
    _state.update(roots=[], log=None, status=None, cancel=None, last=0.0)


def is_net_error(e: BaseException) -> bool:
    return getattr(e, "winerror", None) in NET_WINERR


def alive(path) -> bool:
    try:
        return os.path.isdir(anchor(path))
    except OSError:
        return False


def _targets(paths: Iterable = ()) -> list[str]:
    """Woluminy ścieżek `paths`; bez ścieżek — obserwowane korzenie zadania."""
    out: list[str] = []
    for p in paths or ():
        if p:
            a = anchor(p)
            if a not in out:
                out.append(a)
    return out or list(_state["roots"])


def down(paths: Iterable = ()) -> list[str]:
    """Woluminy ścieżek `paths` (bez nich: obserwowane), które NIE odpowiadają."""
    return [a for a in _targets(paths) if not alive(a)]


def _fmt(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 \
        else f"{s // 60}:{s % 60:02d}"


def _emit(kind: str, msg: str) -> None:
    cb = _state.get(kind)
    if cb is not None:
        try:
            cb(msg)
        except Exception:
            pass


def wait_until_back(paths: Iterable = (), reason: str = "",
                    cancel=None) -> bool:
    """Blokuje, aż niedostępne woluminy wrócą. True = wróciły (albo nic nie
    padło), False = przerwano. Wątki równoległe czekają na tej samej blokadzie
    — komunikat w logu pojawia się raz."""
    paths = list(paths or ())
    if not down(paths):
        return True
    cancel = cancel if cancel is not None else _state.get("cancel")
    with _lock:
        gone = down(paths)
        if not gone:
            return True
        t0 = time.monotonic()
        _emit("log", f"⚠ NAS niedostępny ({', '.join(gone)})"
                     + (f" — {reason}" if reason else "")
                     + ". Praca WSTRZYMANA — wznowi się sama, gdy dysk wróci "
                       "(np. po wybudzeniu laptopa i połączeniu z routerem).")
        last_note = t0
        ok = 0
        while True:
            if cancel is not None and cancel.is_set():
                _emit("log", "⏹ Przerwano czekanie na NAS.")
                return False
            waited = time.monotonic() - t0
            _emit("status", f"⚠ NAS niedostępny — czekam na połączenie "
                            f"({_fmt(waited)})")
            end = time.monotonic() + POLL
            while time.monotonic() < end:
                if cancel is not None and cancel.is_set():
                    break
                time.sleep(0.25)
            ok = ok + 1 if not down(gone) else 0
            if ok >= STABLE:
                break
            if time.monotonic() - last_note >= REMIND:
                last_note = time.monotonic()
                _emit("log", f"…nadal czekam na NAS "
                             f"({_fmt(time.monotonic() - t0)})")
        _state["last"] = time.monotonic()
        _emit("log", f"✓ NAS znowu dostępny po {_fmt(time.monotonic() - t0)} "
                     f"— wznawiam pracę.")
        _emit("status", "NAS dostępny — wznawiam…")
        return True


def checkpoint(cancel=None) -> bool:
    """Tani punkt kontrolny do pętli: najwyżej co CHECK_EVERY s pyta obserwowane
    woluminy; gdy któryś padł — czeka. False = przerwano czekanie."""
    if not _state["roots"]:
        return True
    now = time.monotonic()
    if now - _state["last"] < CHECK_EVERY:
        return True
    _state["last"] = now
    return wait_until_back(cancel=cancel)


def call(fn: Callable, *paths, what: str = "", cancel=None):
    """`fn()` z ponawianiem po awarii NAS: błąd sieciowy (albo niedostępny
    wolumin którejś ze ścieżek) → czekaj na powrót i spróbuj ponownie. Inne
    błędy lecą dalej bez zmian."""
    blips = 0
    while True:
        try:
            return fn()
        except NasOffline:
            raise
        except OSError as e:
            gone = down(paths)
            if not gone:
                # wolumin odpowiada: chwilowa czkawka sieci — kilka prób z
                # przerwą, potem błąd leci dalej (trwały błąd ≠ zawieszenie)
                if not is_net_error(e) or blips >= 3:
                    raise
                blips += 1
                time.sleep(POLL)
                continue
            if not wait_until_back(paths, reason=what or str(e),
                                   cancel=cancel):
                raise NasOffline(f"NAS niedostępny: {e}") from e


def keep_awake():
    """Kontekst: system nie usypia się sam (bezczynność) w czasie pracy wątku.
    Nie blokuje uśpienia po zamknięciu pokrywy — to ustawienie zasilania."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        if os.name != "nt":
            yield
            return
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception:
            pass
        try:
            yield
        finally:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except Exception:
                pass
    return _ctx()
