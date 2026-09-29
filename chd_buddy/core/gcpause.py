"""Pauzy odśmiecacza (GC) przy WIELKICH, długowiecznych strukturach w pamięci.

Objaw (user): okno „nie odpowiada" na 0,5–2 s co kilkanaście–kilkadziesiąt s.
Pomiar (podgląd naprawy bez GUI, czujnik GIL + gc.callbacks): KAŻDE zatrzymanie
= pełne GC pokolenia 2 — 543 ms przy 2,5 mln obiektów, 1306 ms przy 5,5 mln,
1740 ms przy 8 mln (DAT-y 608, cache indeksu w RAM, raporty dopasowania). Pełne GC
trzyma GIL → stoją WSZYSTKIE wątki, także okno. Odstępy nieregularne, bo GC
odpala się wg tempa alokacji, nie zegara.

Lekarstwo: `gc.freeze()` po zbudowaniu dużych struktur — przenosi wszystko żyjące
do pokolenia STAŁEGO, którego GC nie przegląda (pauzy spadają do ułamków).
Zwykłe (niecykliczne) obiekty dalej zwalnia licznik referencji; zamrożone mogą
„wisieć" tylko CYKLE śmieci — dlatego po operacji `unfreeze()` + jedno zebranie.
"""
from __future__ import annotations

import gc
import threading
from contextlib import contextmanager

_lock = threading.Lock()
_depth = 0


def settle() -> None:
    """Zamroź wszystko, co teraz żyje (tanie). Wołać po zbudowaniu DUŻYCH,
    długowiecznych struktur (DAT-y, cache indeksu, raporty)."""
    gc.freeze()


@contextmanager
def long_operation():
    """Na czas długiej operacji: zamrożone, co już jest (DAT-y itp.); na końcu
    OSTATNIEJ zagnieżdżonej operacji — odmrożenie i JEDNO pełne zebranie (jedna
    pauza w chwili zakończenia zamiast co kilkanaście sekund w trakcie)."""
    global _depth
    with _lock:
        _depth += 1
    gc.freeze()
    try:
        yield
    finally:
        with _lock:
            _depth -= 1
            last = _depth == 0
        if last:
            gc.unfreeze()
            gc.collect()
