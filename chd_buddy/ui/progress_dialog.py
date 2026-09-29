"""Osobne okno postępu — widać CO SIĘ DZIEJE i da się przerwać.

Wcześniej długie operacje (zwłaszcza CHD) wyglądały jak zawieszony program:
pasek stał, nie było wiadomo przy którym pliku jesteśmy. To okno pokazuje
bieżącą operację, licznik, czas i pełny log na żywo — plus przycisk Przerwij.

Przerwanie jest BEZPIECZNE: to, co już policzone/naprawione, jest zapisane
(indeks commituje partiami, operacje plikowe są atomowe), więc kolejny przebieg
kontynuuje, a nie zaczyna od zera.
"""
from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..core.i18n import tr


class ProgressDialog(QDialog):
    """Modeless okno postępu. `cancel_event` to threading.Event."""

    def __init__(self, parent, title: str, cancel_event):
        super().__init__(parent)
        self.cancel_event = cancel_event
        self._t0 = time.monotonic()
        self._finished = False
        # CZUWANIE: kiedy przyszło ostatnie zdarzenie (log/pasek) — długa cisza
        # ≠ zawieszenie (np. wysyłka dużego pliku, SMB), ale user MUSI to widzieć
        self._last_event = time.monotonic()
        self._nas_roots: list = []
        self._nas_state: dict = {}          # korzeń -> (ok, kiedy sprawdzono)
        self._nas_probe_at = 0.0
        self._nas_busy = False
        self.setWindowTitle(title)
        self.resize(760, 420)
        # bez przycisku zamykania — kończy się samo albo przez Przerwij
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        lay = QVBoxLayout(self)
        self.lbl_op = QLabel(tr("Start…"))
        self.lbl_op.setWordWrap(True)
        f = self.lbl_op.font()
        f.setBold(True)
        self.lbl_op.setFont(f)
        lay.addWidget(self.lbl_op)

        # OGÓLNY: wszystkie pliki do naprawy (przesuwa się z każdym plikiem)
        lay.addWidget(QLabel(tr("Ogółem (pliki):")))
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)          # nieokreślony do 1. sygnału
        self.bar.setTextVisible(True)
        lay.addWidget(self.bar)

        # SZCZEGÓŁOWY: bieżący plik (kompresja / wypakowanie / przenoszenie)
        self.lbl_detail = QLabel("")
        self.lbl_detail.setWordWrap(True)
        lay.addWidget(self.lbl_detail)
        self.bar_detail = QProgressBar()
        self.bar_detail.setRange(0, 100)
        self.bar_detail.setValue(0)
        self.bar_detail.setTextVisible(True)
        self.bar_detail.setFormat("")
        lay.addWidget(self.bar_detail)

        # RÓWNOLEGŁE: po jednym pasku na każdy plik liczony jednocześnie
        # (skan wielowątkowy na NAS/SSD). Tworzone leniwie, chowane po pliku.
        self.lbl_slots = QLabel(tr("Pliki liczone równolegle:"))
        self.lbl_slots.setVisible(False)
        lay.addWidget(self.lbl_slots)
        self._slots_lay = QVBoxLayout()
        self._slots_lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self._slots_lay)
        self._slot_bars: dict = {}       # slot -> (QLabel, QProgressBar)

        self.lbl_time = QLabel(tr("czas:") + " 0:00")
        lay.addWidget(self.lbl_time)
        # stan „czy to żyje": cisza od X, stan NAS (sprawdzany w tle)
        self.lbl_alive = QLabel("")
        self.lbl_alive.setWordWrap(True)
        lay.addWidget(self.lbl_alive)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        lay.addWidget(self.log, 1)

        row = QHBoxLayout()
        row.addStretch()
        self.btn_cancel = QPushButton(tr("⛔ Przerwij"))
        self.btn_cancel.setToolTip(
            "Zatrzymuje po bieżącej operacji. Wszystko, co już zrobione, "
            "zostaje zapisane — kolejny przebieg dokończy resztę.")
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_close = QPushButton(tr("Zamknij"))
        self.btn_close.setEnabled(False)
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(500)
        self._log_buf: list = []
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._flush_log)
        self._log_timer.start(100)

    # --- API wołane z okna głównego -----------------------------------------

    def set_nas_roots(self, roots) -> None:
        """Korzenie woluminów (np. Z:) sprawdzane w tle przy długiej ciszy."""
        self._nas_roots = [r for r in dict.fromkeys(roots) if r]

    def _touch(self) -> None:
        self._last_event = time.monotonic()

    def append_log(self, msg: str) -> None:
        """Linia → bufor; do widżetu PACZKĄ co 100 ms (`_flush_log`) — tysiące
        pojedynczych appendPlainText w serii przycinały okno na 0,5–2 s."""
        self._touch()
        self._log_buf.append(msg)

    def _flush_log(self) -> None:
        buf = self._log_buf
        if not buf:
            return
        self._log_buf = []
        self.log.appendPlainText("\n".join(buf[-5000:]))   # = MaximumBlockCount

    # QProgressBar w Qt bierze C++ int (32-bit). Postęp BAJTOWY dużych plików
    # (CHD/ISO > 2,1 GB) przekracza INT_MAX i rzuca OverflowError. Skalujemy
    # (done, total) do bezpiecznego zakresu, zachowując proporcję (procent).
    _SAFE_MAX = 1_000_000

    @classmethod
    def _scale(cls, done: int, total: int) -> tuple[int, int]:
        if total <= cls._SAFE_MAX:
            return int(done), int(total)
        d = int(done * cls._SAFE_MAX / total) if total else 0
        return max(0, min(d, cls._SAFE_MAX)), cls._SAFE_MAX

    def set_progress(self, done: int, total: int, text: str) -> None:
        self._touch()
        if total > 0:
            d, t = self._scale(done, total)
            self.bar.setRange(0, t)
            self.bar.setValue(d)
            # liczniki (pliki/CHD/DAT-y) są małe → pokaż X/Y; przy skalowaniu
            # dużych wartości pokaż sam procent, żeby X/Y nie mylił
            self.bar.setFormat("%v / %m  (%p%)" if total <= self._SAFE_MAX
                               else "%p%")
        else:
            self.bar.setRange(0, 0)
            self.bar.setFormat("")
        if text:
            self.lbl_op.setText(text)

    def set_detail(self, done: int, total: int, text: str) -> None:
        """Pasek szczegółowy: postęp bieżącego pliku (kompresja/przenoszenie).
        total<=0 => tryb nieokreślony (pulsuje); done<0 => wyzeruj/schowaj."""
        self._touch()
        if done < 0:
            self.bar_detail.setRange(0, 100)
            self.bar_detail.setValue(0)
            self.bar_detail.setFormat("")
            self.lbl_detail.setText("")
            return
        if total > 0:
            d, t = self._scale(done, total)
            self.bar_detail.setRange(0, t)
            self.bar_detail.setValue(d)
            self.bar_detail.setFormat("%p%")
        else:
            self.bar_detail.setRange(0, 0)      # pulsujący (nieznany postęp)
            self.bar_detail.setFormat("")
        self.lbl_detail.setText(text or "")

    def _slot_widgets(self, slot: int):
        """Leniwie tworzy (etykieta, pasek) dla slotu równoległego."""
        pair = self._slot_bars.get(slot)
        if pair is None:
            lbl = QLabel("")
            lbl.setWordWrap(True)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            bar.setFormat("")
            self._slots_lay.addWidget(lbl)
            self._slots_lay.addWidget(bar)
            pair = (lbl, bar)
            self._slot_bars[slot] = pair
            self.lbl_slots.setVisible(True)
        return pair

    def set_slot(self, slot: int, done: int, total: int, text: str) -> None:
        """Pasek jednego równoległego pliku. text=='' albo total<0 => zwolniony
        (chowamy). total<=0 => pulsuje; inaczej postęp bajtowy."""
        self._touch()
        # ODPORNOŚĆ: zły typ (np. tekst chdmana w miejscu liczby) wywracał
        # obsługę sygnału ZANIM pasek się pokazał → pasek nigdy nie był widoczny
        try:
            done, total = int(done), int(total)
        except (TypeError, ValueError):
            done, total = 0, 0                # pulsuj zamiast znikać
        lbl, bar = self._slot_widgets(slot)
        if not text or total < 0:
            bar.setVisible(False)
            lbl.setVisible(False)
            return
        lbl.setVisible(True)
        bar.setVisible(True)
        if total > 0:
            d, t = self._scale(done, total)
            bar.setRange(0, t)
            bar.setValue(d)
            bar.setFormat("%p%")
        else:
            bar.setRange(0, 0)
            bar.setFormat("")
        lbl.setText(text)

    def _clear_slots(self) -> None:
        for lbl, bar in self._slot_bars.values():
            bar.setVisible(False)
            lbl.setVisible(False)
        self.lbl_slots.setVisible(False)

    def finish(self, err: str = "") -> None:
        self._flush_log()                  # ostatnie linie przed podsumowaniem
        self._finished = True
        self.lbl_alive.setText("")
        self._clear_slots()
        self._timer.stop()
        self.bar.setRange(0, 100)
        self.bar_detail.setRange(0, 100)
        self.bar_detail.setValue(0)
        self.bar_detail.setFormat("")
        self.lbl_detail.setText("")
        was_cancel = self.cancel_event.is_set()
        self.bar.setValue(0 if err else 100)
        if err:
            self.lbl_op.setText(tr("BŁĄD — szczegóły w logu"))
        elif was_cancel:
            self.lbl_op.setText(tr("PRZERWANE — postęp zapisany, można wznowić"))
        else:
            self.lbl_op.setText(tr("Gotowe"))
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.show()

    # --- wewnętrzne ----------------------------------------------------------

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.btn_cancel.setEnabled(False)
        self.lbl_op.setText(tr("Przerywam: kończę bieżące gry, nie biorę nowych… "
                               "(postęp zapisany)"))
        self.append_log(tr("== ŻĄDANIE PRZERWANIA — dokańczam gry będące w "
                           "trakcie, nie zaczynam nowych; po ich zakończeniu "
                           "stop. Zrobione jest zapisane, wznowienie dokończy "
                           "resztę. =="))

    # po ilu sekundach ciszy pokazać ostrzeżenie i zacząć sprawdzać NAS
    _IDLE_WARN = 45
    _NAS_EVERY = 30

    def _tick(self) -> None:
        s = int(time.monotonic() - self._t0)
        self.lbl_time.setText(tr("czas:") + f" {s // 60}:{s % 60:02d}")
        if self._finished:
            return
        idle = int(time.monotonic() - self._last_event)
        if idle < self._IDLE_WARN:
            self.lbl_alive.setText("")
            return
        # DŁUGA CISZA: sprawdź NAS w TLE (zapytanie do martwego SMB potrafi
        # wisieć dziesiątki sekund — nie może blokować okna)
        now = time.monotonic()
        if (self._nas_roots and not self._nas_busy
                and now - self._nas_probe_at >= self._NAS_EVERY):
            self._nas_busy = True
            self._nas_probe_at = now
            threading.Thread(target=self._probe_nas, daemon=True).start()
        nas = ""
        if self._nas_state:
            dead = [r for r, (ok, _t) in self._nas_state.items() if not ok]
            nas = (tr("  NAS NIE odpowiada:") + " " + ", ".join(dead)
                   + tr(" — program czeka na połączenie.")) if dead                 else tr("  NAS odpowiada.")
        self.lbl_alive.setText(
            tr("⏳ brak nowych zdarzeń od") + f" {idle // 60}:{idle % 60:02d}"
            + tr(" — trwa ostatnia operacja (duży plik / sieć). To nie musi "
                 "być zawieszenie.") + nas)

    def _probe_nas(self) -> None:
        state = {}
        for r in self._nas_roots:
            try:
                ok = os.path.isdir(r)
            except OSError:
                ok = False
            state[r] = (ok, time.monotonic())
        self._nas_state = state
        self._nas_busy = False

    def closeEvent(self, ev) -> None:      # nie zamykaj w trakcie pracy
        if self._finished:
            ev.accept()
        else:
            ev.ignore()
