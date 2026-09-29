"""Potokowa konwersja: nakładanie POBIERANIA (NAS→RAM), KONWERSJI (CPU) i
WYSYŁANIA (RAM→NAS) — jak potok w CPU. Gdy wysyłamy plik N, kolejny (N+1) już się
konwertuje, a następny (N+2) pobiera. Na NAS ukrywa latencję sieci pod CPU.

Zasady bezpieczeństwa (twarde):
- KONWERSJA seryjna (jedna na raz) — chdman/DolphinTool i tak biorą wiele rdzeni.
- ETAPY jako łańcuch kolejek FIFO → wynik zachowuje KOLEJNOŚĆ zgłoszeń (ważne dla
  rodzic→dziecko: rodzic sfinalizowany przed dzieckiem).
- FINALIZACJA (zapisy do indeksu/SQLite, kasowanie źródeł, callbacki) wykonuje
  WYŁĄCZNIE wątek WŁAŚCICIELA (feed/wait/drain) — SQLite jest jednowątkowe.
- BUDŻET RAM (bajty) rezerwuje WĄTEK POBIERANIA w chwili, gdy BIERZE zadanie
  (nie feed() przy zleceniu). Dawniej gry czekające w kolejce do jedynego wątku
  pobierania trzymały już swój budżet → nowe zlecenia stały, choć RAM był pusty
  (log PS2: 5 min przestoju). Miejsce zwalnia finalizacja (plik zszedł na NAS,
  katalog roboczy skasowany).
- KOLEJKA ZLECEŃ ograniczona LICZBĄ (nie RAM-em): feed() blokuje, gdy czeka już
  `gather_workers + 1` niepobranych zadań, i w trakcie czekania FINALIZUJE gotowe
  (to one zwalniają budżet) — brak zakleszczenia.
- POBIERANIE: domyślnie JEDNO naraz (`gather_workers=1`, ustawienie
  `download_workers`) — potok „na zakładkę": plik N+1 pobiera się, gdy N się
  przerabia, a N-1 wysyła. Kilka wątków pobierania jest możliwe, ale dzieli
  łącze. W trybie `ordered` zawsze 1 (FIFO — inaczej późniejsze zadanie mogłoby
  zająć budżet przed głową kolejki = zakleszczenie).

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
    reserved: bool = False          # budżet zarezerwowany przez wątek pobierania
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
                 cancel=None, build_workers: int = 1, ordered: bool = True,
                 gather_workers: int = 1):
        self._gather = gather
        self._build = build
        self._upload = upload
        self._finalize = finalize
        self._release = release or (lambda _p: None)
        self._ram_budget = max(0, int(ram_budget))
        self._log = log or (lambda _m: None)
        self._cancel = cancel
        # RÓWNOLEGŁA KONWERSJA: N wątków build (chdman/DolphinTool). Dla MAŁYCH
        # gier (CD: 3DO/PS1/Saturn) jeden chdman nie wysyca CPU/NAS — 8 naraz
        # wypełnia zasoby. Ile realnie biegnie ogranicza BUDŻET RAM (feed rezerwuje
        # `cost`). Bezpieczne, bo potok włącza się TYLKO bez współdzielonych
        # odcisków (ordered=False) → brak zależności rodzic→dziecko.
        self._build_workers = max(1, int(build_workers))
        self._ordered = bool(ordered)
        self._build_live = self._build_workers
        self._build_active = 0             # kompresje TRWAJĄCE teraz (wątki chdman)
        # RÓWNOLEGŁE POBIERANIE — tylko bez zależności kolejnościowych (patrz
        # docstring modułu: ordered + wiele pobierających = zakleszczenie budżetu)
        self._gather_workers = (1 if self._ordered
                                else max(1, int(gather_workers)))
        self._gather_live = self._gather_workers
        self._queued = 0                   # zlecone, jeszcze nie wzięte do pobrania
        self._max_backlog = self._gather_workers + 1

        self._q_in: "Queue" = Queue()      # feed → gather
        self._q_gb: "Queue" = Queue()      # gather → build (N konsumentów)
        self._q_bu: "Queue" = Queue()      # build → upload

        self._cv = threading.Condition()   # budżet RAM + sygnał ukończenia
        self._used = 0
        self._pending: list[_Job] = []     # zgłoszone, do finalizacji
        self._seq = 0
        self._started = False
        self._closed = False
        self._threads: list[threading.Thread] = []

    # --- API właściciela ---------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        # M × gather + N × build (każdy z własnym SLOTEM 0..N-1 na osobny pasek
        # postępu) + upload (1)
        targets = [lambda i=i: self._gather_loop(i)
                   for i in range(self._gather_workers)]
        targets += [lambda i=i: self._build_loop(i)
                    for i in range(self._build_workers)]
        targets.append(self._upload_loop)
        for target in targets:
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def feed(self, payload: Any, cost: int = 0) -> _Job:
        """Zgłasza zadanie (w kolejności). Blokuje, gdy kolejka niepobranych
        zadań jest pełna (w międzyczasie finalizuje gotowe — to one zwalniają
        budżet RAM, na który czekają wątki pobierania). Budżet `cost`
        rezerwuje dopiero wątek pobierania (`_admit`)."""
        if not self._started:
            self.start()
        job = _Job(seq=self._seq, payload=payload, cost=max(0, int(cost)))
        self._seq += 1
        with self._cv:
            self._pending.append(job)
            while (self._queued >= self._max_backlog
                   and not self._is_cancelled()):
                if not self._drain_ready_locked():
                    self._cv.wait(timeout=0.5)
            self._queued += 1
            self._drain_ready_locked()     # przy okazji: domknij gotowe
        self._q_in.put(job)
        return job

    def _admit(self, job: _Job) -> None:
        """WĄTEK POBIERANIA: czekaj, aż budżet RAM zmieści zadanie, i zarezerwuj.
        „Zawsze wpuść jedno" (used == 0) — zadanie większe niż budżet idzie samo.
        Budżet zwalnia finalizacja w wątku właściciela (feed/wait/drain)."""
        with self._cv:
            while (self._ram_budget > 0 and self._used > 0
                   and self._used + job.cost > self._ram_budget
                   and not self._is_cancelled()):
                self._cv.wait(timeout=0.5)
            self._used += job.cost
            job.reserved = True

    def _free_locked(self, cost: int) -> None:
        self._used = max(0, self._used - cost)
        self._cv.notify_all()

    def _is_cancelled(self) -> bool:
        return self._cancel is not None and self._cancel.is_set()

    def _next_ready_locked(self) -> Optional[_Job]:
        """Zwraca (i usuwa z _pending) następne zadanie do finalizacji. W trybie
        ordered — tylko GŁOWĘ, gdy gotowa (rodzic→dziecko). W trybie ordered=False
        — DOWOLNE gotowe (potok bez zależności → finalizacja poza kolejnością)."""
        if not self._pending:
            return None
        if self._ordered:
            if self._pending[0].done.is_set():
                return self._pending.pop(0)
            return None
        for i, job in enumerate(self._pending):
            if job.done.is_set():
                return self._pending.pop(i)
        return None

    def _drain_ready_locked(self) -> bool:
        """Finalizuje gotowe zadania. Wywoływane z trzymanym `self._cv`; zwalnia
        go na czas finalize/release. Zwraca True, gdy coś sfinalizowano."""
        did = False
        while True:
            job = self._next_ready_locked()
            if job is None:
                break
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
            if job.reserved:
                self._free_locked(job.cost)
            else:
                self._cv.notify_all()
            did = True
        return did

    def wait(self, job: _Job) -> None:
        """Blokuje, aż DANE zadanie przejdzie upload, i finalizuje po kolei do
        niego włącznie (zależność rodzic→dziecko). W międzyczasie finalizuje
        KAŻDE gotowe — dane zadanie może czekać na budżet RAM trzymany przez
        zadania już ukończone, a niesfinalizowane (inaczej zakleszczenie)."""
        with self._cv:
            while True:
                self._drain_ready_locked()
                if job not in self._pending:
                    return
                self._cv.wait(timeout=0.5)

    def drain(self) -> None:
        """Czeka na wszystkie zgłoszone zadania i finalizuje je (ordered — po
        kolei). NIE czeka na głowę kolejki: bez `ordered` głowa może czekać na
        budżet RAM, który zwolni dopiero finalizacja zadań za nią."""
        with self._cv:
            while self._pending:
                if not self._drain_ready_locked():
                    self._cv.wait(timeout=0.5)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for _ in range(self._gather_workers):
            self._q_in.put(_STOP)
        for t in self._threads:
            t.join(timeout=30)

    # --- wątki etapów (FIFO, STOP propaguje łańcuchem) ---------------------

    def _run_stage(self, in_q: "Queue", out_q: Optional["Queue"], fn,
                   stage: str, on_stop: Optional[Callable] = None,
                   on_take: Optional[Callable] = None) -> None:
        while True:
            item = in_q.get()
            if item is _STOP:
                if on_stop is not None:
                    on_stop()
                elif out_q is not None:
                    out_q.put(_STOP)
                return
            job = item
            if on_take is not None:
                on_take(job)
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

    def _gather_loop(self, gather_idx: int = 0) -> None:
        def _take(job):
            # zadanie zeszło z kolejki zleceń → feed() może zlecić następne
            with self._cv:
                self._queued = max(0, self._queued - 1)
                self._cv.notify_all()

        def _do(job):
            self._admit(job)               # budżet RAM dopiero TERAZ
            if self._is_cancelled():
                return None
            # WŁASNY pasek postępu pobierania: numery ZA paskami kompresji
            # (build ma 0..N-1), więc równoległe pobierania nie piszą na jeden
            if isinstance(job.payload, dict):
                job.payload["_gather_slot"] = self._build_workers + gather_idx
            job.gathered = self._gather(job.payload)
            return job.gathered
        # ostatni żywy wątek pobierania → po jednym STOP dla KAŻDEGO wątku build
        def _on_stop():
            with self._cv:
                self._gather_live -= 1
                last = self._gather_live == 0
            if last:
                for _ in range(self._build_workers):
                    self._q_gb.put(_STOP)
        self._run_stage(self._q_in, self._q_gb, _do, "gather", on_stop=_on_stop,
                        on_take=_take)

    def _build_loop(self, slot_idx: int = 0) -> None:
        def _do(job):
            # przekaż numer SLOTU (pasek postępu) do fazy build przez payload,
            # nie zmieniając generycznego kontraktu build(payload, gathered)
            # ILE KOMPRESJI TRWA NAPRAWDĘ (z tą) — faza build dzieli pulę wątków
            # chdman wg tej liczby. Dawniej podział był z góry „na 4 równoległe",
            # a przy jednym pobraniu naraz przez wolne łącze kompresja szła
            # zwykle SAMA na 1–2 wątkach (CPU 8%, user).
            with self._cv:
                self._build_active += 1
                active = self._build_active
            if isinstance(job.payload, dict):
                job.payload["_pipe_slot"] = slot_idx
                job.payload["_pipe_active"] = active
                # liczba trwających W DANEJ CHWILI — faza build pyta tuż przed
                # samą kompresją (wcześniej robi jednowątkowe rozpakowanie)
                job.payload["_pipe_active_fn"] = lambda: self._build_active
            try:
                job.built = self._build(job.payload, job.gathered)
            finally:
                with self._cv:
                    self._build_active -= 1
            return job.built
        # ostatni żywy wątek build przekazuje STOP do uploadu (tylko raz)
        def _on_stop():
            with self._cv:
                self._build_live -= 1
                last = self._build_live == 0
            if last:
                self._q_bu.put(_STOP)
        self._run_stage(self._q_gb, self._q_bu, _do, "build", on_stop=_on_stop)

    def _upload_loop(self) -> None:
        def _do(job):
            job.result = self._upload(job.payload, job.built)
            return job.result
        self._run_stage(self._q_bu, None, _do, "upload")
