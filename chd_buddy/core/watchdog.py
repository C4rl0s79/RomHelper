"""Strażnik CISZY: gdy długa operacja nie daje znaku życia, sam mówi, GDZIE stoi.

Zamiast łatać każdą pętlę osobno (platforma po platformie), zadanie jest
obserwowane z boku: każde zdarzenie (log, pasek) „dotyka" strażnika; gdy przez
`first` sekund nic nie przyszło, strażnik podgląda stos wątków programu
(`sys._current_frames`) i loguje funkcję, plik:linię i obiekt, na którym pracuje
(gra / plik). Działa w każdej fazie, także tych, które jeszcze nie mają paska —
a linie trafiają do pliku logu, więc widać, co trzeba poprawić.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable, Optional

_PKG = "chd_buddy"
# nazwy zmiennych lokalnych, które zwykle opisują „na czym pracujemy"
_HINTS = ("game", "path", "src", "dst", "archive", "chd_path", "p", "row",
          "rep", "entry", "name", "s")


def _hint(frame) -> str:
    loc = frame.f_locals
    for k in _HINTS:
        if k not in loc:
            continue
        v = loc[k]
        for attr in ("name", "game", "path", "source_path"):
            if hasattr(v, attr) and isinstance(getattr(v, attr, None), str):
                return f"{k}={getattr(v, attr)}"
        if isinstance(v, (str, os.PathLike)):
            return f"{k}={os.fspath(v)}"
        try:
            if hasattr(v, "keys") and "path" in v.keys():
                return f"{k}={v['path']}"
        except Exception:
            pass
    return ""


def describe_threads(exclude: tuple = ()) -> list[str]:
    """Najgłębsze ramki kodu programu w każdym wątku (poza `exclude`)."""
    out: list[str] = []
    # główny wątek = pętla zdarzeń GUI (zawsze „stoi" w oknie) — pomijamy go;
    # kod okna w WĄTKACH ROBOCZYCH (np. przygotowanie skanu) się liczy
    main = threading.main_thread().ident
    for tid, frame in sys._current_frames().items():
        if tid in exclude or tid == main:
            continue
        chain = []
        f = frame
        while f is not None:
            # w exe (PyInstaller) ścieżki modułów są WZGLĘDNE („chd_buddy/…"),
            # bez wiodącego separatora — stąd „/" + fn
            fn = "/" + f.f_code.co_filename.replace("\\", "/")
            if f"/{_PKG}/" in fn and not fn.endswith("/watchdog.py"):
                chain.append(f)
            f = f.f_back
        if not chain:
            continue
        top = chain[0]                     # najgłębsza ramka programu
        where = (f"{top.f_code.co_name} "
                 f"({os.path.basename(top.f_code.co_filename)}:{top.f_lineno})")
        callers = " ← ".join(c.f_code.co_name for c in chain[1:3])
        hint = next((h for h in (_hint(c) for c in chain) if h), "")
        out.append(where + (f" ← {callers}" if callers else "")
                   + (f" — {hint}" if hint else ""))
    return out


class StallWatch:
    """touch() przy każdym zdarzeniu; po `first` s ciszy loguje miejsce pracy,
    potem co `every` s (dopóki cisza trwa)."""

    def __init__(self, emit: Callable[[str], None], first: float = 20.0,
                 every: float = 60.0):
        self._emit = emit
        self.first, self.every = first, every
        self._last = time.monotonic()
        self._reported = 0.0
        self._stop = threading.Event()
        self._thr: Optional[threading.Thread] = None
        self.stalls: list[tuple[float, list[str]]] = []   # (sekundy ciszy, stos)

    def touch(self) -> None:
        self._last = time.monotonic()
        self._reported = 0.0

    def start(self) -> "StallWatch":
        self._thr = threading.Thread(target=self._loop, daemon=True,
                                     name="stall-watch")
        self._thr.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        me = threading.get_ident()
        while not self._stop.wait(1.0):
            idle = time.monotonic() - self._last
            due = self.first if not self._reported else self._reported + self.every
            if idle < due:
                continue
            self._reported = idle
            where = describe_threads(exclude=(me,))
            self.stalls.append((idle, where))
            msg = (f"⏳ [{int(idle)} s bez postępu] trwa: "
                   + (" | ".join(where[:3]) if where else "(poza kodem programu)"))
            try:
                self._emit(msg)
            except Exception:
                pass
