"""Potokowa konwersja: nakładanie POBIERANIA (NAS→RAM), KONWERSJI (CPU) i
WYSYŁANIA (RAM→NAS) — jak potok w CPU. Gdy wysyłamy plik N, kolejny (N+1) już się
konwertuje, a następny (N+2) pobiera. Na NAS ukrywa latencję sieci pod CPU.

Zasady bezpieczeństwa (twarde):
- KONWERSJA seryjna (jedna na raz) — chdman/DolphinTool i tak biorą wiele rdzeni.
- ETAPY jako łańcuch kolejek FIFO → wynik zachowuje KOLEJNOŚĆ zgłoszeń (ważne dla
  rodzic→dziecko: rodzic sfinalizowany przed dzieckiem).
- FINALIZACJA (zapisy do indeksu/SQLite, kasowanie źródeł, callbacki) wykonuje
  WYŁĄCZNIE wątek WŁAŚCICIELA (feed/wait/drain) — SQLite jest jednowątkowe.
- BUDŻET RAM (bajty): feed() blokuje, aż zwolni się miejsce; miejsce zwalnia
  finalizacja (plik zszedł na NAS, katalog roboczy skasowany). Aby uniknąć
  zakleszczenia, feed() W TRAKCIE czekania FINALIZUJE gotowe zadania (to one
  zwalniają budżet).

Koordynator jest GENERYCZNY (bez wiedzy o chdman/NAS) — operacje wstrzykiwane
jako funkcje, więc daje się w całości przetestować na atrapach.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from queue import Queue
from typing import Any, Callable, Optional

_STOP = object()


@dataclass
class _Job:
    seq: int
    payload: Any
    cost: int = 0
    gathered: Any = None
    built: Any = None
    result: Any = None
    failed_stage: str = ""
    error: str = ""
    done: threading.Event = field(default_factory=threading.Event)


class StagePipeline:
    """gather → build → upload (osobne wątki), finalize/release w wątku właściciela.

    Wstrzykiwane operacje:
      gather(payload)           -> gathered   (I/O; wątek gathera)
      build(payload, gathered)  -> built      (CPU; wątek buildera)
      upload(payload, built)    -> result     (I/O; wątek uploadera)
      finalize(payload, result) -> None        (WŁAŚCICIEL; po sukcesie etapów)
      release(payload)          -> None        (WŁAŚCICIEL; ZAWSZE — zwolnij pliki)
    Zwrot None/False z etapu = pominięcie zadania (nie błąd) — dalsze etapy i
    finalize pomijane, ale release ZAWSZE się wykona. Wyjątek = to samo + log.
    """

    def __init__(self, *, gather: Callable, build: Callable, upload: Callable,
                 finalize: Callable, release: Optional[Callable] = None,
                 ram_budget: int = 0, log: Optional[Callable] = None,
                 cancel=None):
        self._gather = gather
        self._build = build
        self._upload = upload
        self._finalize = finalize
        self._release = release or (lambda _p: None)
        self._ram_budget = max(0, int(ram_budget))
        self._log = log or (lambda _m: None)
        self._cancel = cancel

        self._q_in: "Queue" = Queue()      # feed → gather
        self._q_gb: "Queue" = Queue()      # gather → build
        self._q_bu: "Queue" = Queue()      # build → upload

        self._cv = threading.Condition()   # budżet RAM + sygnał ukończenia
        self._used = 0
        self._pending: list[_Job] = []     # w kolejności zgłoszeń, do finalizacji
        self._seq = 0
        self._started = False
        self._closed = False
        self._threads: list[threading.Thread] = []

    # --- API właściciela ---------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for target in (self._gather_loop, self._build_loop, self._upload_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def feed(self, payload: Any, cost: int = 0) -> _Job:
        """Zgłasza zadanie (w kolejności). Blokuje, aż budżet RAM zmieści `cost`
        (w międzyczasie finalizuje gotowe zadania, by zwolnić miejsce)."""
        if not self._started:
            self.start()
        job = _Job(seq=self._seq, payload=payload, cost=max(0, int(cost)))
        self._seq += 1
        with self._cv:
            self._pending.append(job)
        self._reserve(job.cost)
        self._q_in.put(job)
        return job

    def _reserve(self, cost: int) -> None:
        with self._cv:
            while (self._ram_budget > 0 and self._used > 0
                   and self._used + cost > self._ram_budget
                   and not self._is_cancelled()):
                # finalizuj gotowe (zwalnia budżet); jeśli nic gotowe — czekaj
                if not self._drain_ready_locked():
                    self._cv.wait(timeout=0.5)
            self._used += cost

    def _free_locked(self, cost: int) -> None:
        self._used = max(0, self._used - cost)
        self._cv.notify_all()

    def _is_cancelled(self) -> bool:
        return self._cancel is not None and self._cancel.is_set()

    def _drain_ready_locked(self) -> bool:
        """Finalizuje prefiks gotowych zadań (kolejność zgłoszeń). Wywoływane z
        trzymanym `self._cv`; zwalnia go na czas finalize/release. Zwraca True,
        gdy coś sfinalizowano."""
        did = False
        while self._pending and self._pending[0].done.is_set():
            job = self._pending.pop(0)
            self._cv.release()
            try:
                if not job.failed_stage and not self._is_cancelled():
                    try:
                        self._finalize(job.payload, job.result)
                    except Exception as e:
                        self._log(f"finalize: BŁĄD {e}")
                try:
                    self._release(job.payload)
                except Exception as e:
                    self._log(f"release: BŁĄD {e}")
            finally:
                self._cv.acquire()
            self._free_locked(job.cost)
            did = True
        return did

    def wait(self, job: _Job) -> None:
        """Blokuje, aż DANE zadanie przejdzie upload, i finalizuje po kolei do
        niego włącznie (zależność rodzic→dziecko)."""
        job.done.wait()
        with self._cv:
            self._drain_ready_locked()

    def drain(self) -> None:
        """Czeka na wszystkie zgłoszone zadania i finalizuje je po kolei."""
        while True:
            with self._cv:
                if not self._pending:
                    return
                head = self._pending[0]
            head.done.wait()
            with self._cv:
                self._drain_ready_locked()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._q_in.put(_STOP)
        for t in self._threads:
            t.join(timeout=30)

    # --- wątki etapów (FIFO, STOP propaguje łańcuchem) ---------------------

    def _run_stage(self, in_q: "Queue", out_q: Optional["Queue"], fn,
                   stage: str) -> None:
        while True:
            item = in_q.get()
            if item is _STOP:
                if out_q is not None:
                    out_q.put(_STOP)
                return
            job = item
            if not job.failed_stage and not self._is_cancelled():
                try:
                    val = fn(job)
                    if val is None or val is False:
                        job.failed_stage = stage
                except Exception as e:
                    job.failed_stage = stage
                    job.error = str(e)
                    self._log(f"{stage}: BŁĄD {e}")
            elif not job.failed_stage:
                job.failed_stage = "cancel"
            if out_q is not None:
                out_q.put(job)
            else:                                  # ostatni etap → sygnał gotowe
                job.done.set()
                with self._cv:
                    self._cv.notify_all()

    def _gather_loop(self) -> None:
        def _do(job):
            job.gathered = self._gather(job.payload)
            return job.gathered
        self._run_stage(self._q_in, self._q_gb, _do, "gather")

    def _build_loop(self) -> None:
        def _do(job):
            job.built = self._build(job.payload, job.gathered)
            return job.built
        self._run_stage(self._q_gb, self._q_bu, _do, "build")

    def _upload_loop(self) -> None:
        def _do(job):
            job.result = self._upload(job.payload, job.built)
            return job.result
        self._run_stage(self._q_bu, None, _do, "upload")
