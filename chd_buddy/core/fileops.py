"""Operacje plikowe z raportowaniem postępu (kopiowanie/przenoszenie kawałkami).

Duże pliki (CHD/ISO — zwłaszcza z RAM dysku na fizyczny) potrafią kopiować się
kilkadziesiąt sekund. `shutil.move`/`copyfileobj` nie dają znaku życia, więc
pasek stał. Tu kopiujemy blokami i po każdym raportujemy postęp bajtowy —
każda operacja plikowa jest widoczna.

Kontrakt callbacku: on_progress(done_bytes, total_bytes, label).
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Callable, Optional

ProgCB = Callable[[int, int, str], None]
_CHUNK = 8 * 1024 * 1024        # 8 MiB — kompromis szybkość / częstość aktualizacji


def atomic_write_text(path, text: str, *, backup: bool = False,
                      encoding: str = "utf-8") -> Path:
    """JEDYNY sposób zapisu plików konfiguracyjnych: treść do pliku
    tymczasowego obok, fsync, potem ATOMOWA podmiana. Zerwanie NAS / zamknięcie
    programu w trakcie zostawia STARY plik nietknięty — `write_text` najpierw
    czyści plik (29.09: `_reguly.json` = 0 bajtów → program liczył wszystko na
    domyślnych regułach, 4551 plików „bez DAT-a” do ToSort).
    backup=True — poprzednia (niepusta) wersja zostaje jako `<plik>.bak`."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding=encoding) as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if backup:
        # kopia też ATOMOWO: .bak.tmp → os.replace; przerwanie zostawia starą,
        # pełną .bak (dawniej copy2 prosto do .bak → 0 B po przerwaniu, 30.09)
        try:
            if p.is_file() and p.stat().st_size > 0:
                btmp = p.with_name(p.name + ".bak.tmp")
                shutil.copy2(p, btmp)
                with open(btmp, "rb+") as f:
                    os.fsync(f.fileno())
                if btmp.stat().st_size > 0:
                    os.replace(btmp, p.with_name(p.name + ".bak"))
        except OSError:
            pass
    os.replace(tmp, p)
    return p


def copy_with_progress(src, dst, on_progress: Optional[ProgCB] = None,
                       label: str = "", chunk: int = _CHUNK) -> int:
    """Kopiuje src→dst blokami, raportując on_progress(done, total, label).

    Zachowuje metadane (copystat). Zwraca liczbę skopiowanych bajtów.
    Pusty plik też wywoła on_progress(0, 0, label) raz (widać etykietę).
    """
    src, dst = Path(src), Path(dst)
    try:
        total = src.stat().st_size
    except OSError:
        total = 0
    done = 0
    if on_progress is not None:
        on_progress(0, total, label)
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            buf = fi.read(chunk)
            if not buf:
                break
            fo.write(buf)
            done += len(buf)
            if on_progress is not None:
                on_progress(done, total, label)
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass
    return done


PAR_WORKERS = 8                 # równoległe odczyty/zapisy (NAS przez internet)


def copy_parallel(src, dst, on_progress: Optional[ProgCB] = None,
                  label: str = "", workers: int = PAR_WORKERS,
                  chunk: int = _CHUNK) -> int:
    """Kopia src→dst KILKOMA równoległymi odczytami/zapisami (każdy wątek na
    własnym uchwycie, swój kawałek pliku). Na NAS przez internet (Tailscale,
    33 ms na rundę) jeden strumień czeka na każdy blok osobno: pomiar 2–3 MB/s
    wobec ~21 MB/s przy 8 odczytach naraz (Total Commander ~30 MB/s robi to
    samo). Małe pliki (< 2 bloki) — zwykła kopia. Po kopii kontrola rozmiaru.
    on_progress(done, total, label) bywa wołane z wątków roboczych."""
    import threading
    src, dst = Path(src), Path(dst)
    size = src.stat().st_size
    if workers <= 1 or size < 2 * chunk:
        return copy_with_progress(src, dst, on_progress, label, chunk)
    if on_progress is not None:
        on_progress(0, size, label)
    with open(dst, "wb") as fo:
        fo.truncate(size)
    offsets = list(range(0, size, chunk))
    lock = threading.Lock()
    state = {"next": 0, "done": 0, "err": None}

    def work() -> None:
        try:
            with open(src, "rb") as fi, open(dst, "r+b") as fo:
                while True:
                    with lock:
                        if state["err"] is not None or state["next"] >= len(offsets):
                            return
                        off = offsets[state["next"]]
                        state["next"] += 1
                    fi.seek(off)
                    want = min(chunk, size - off)
                    buf = fi.read(want)
                    if len(buf) != want:
                        raise OSError(f"krótki odczyt {src} @ {off}: "
                                      f"{len(buf)} z {want} B")
                    fo.seek(off)
                    fo.write(buf)
                    with lock:
                        state["done"] += len(buf)
                        done = state["done"]
                    if on_progress is not None:
                        on_progress(done, size, label)
        except BaseException as e:          # pierwszy błąd zatrzymuje resztę
            with lock:
                if state["err"] is None:
                    state["err"] = e

    ts = [threading.Thread(target=work, daemon=True)
          for _ in range(min(workers, len(offsets)))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    if state["err"] is not None:
        raise state["err"]
    got = dst.stat().st_size
    if got != size or state["done"] != size:
        raise OSError(f"kopia niepełna {dst}: {state['done']}/{size} B "
                      f"(plik {got} B)")
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass
    return size


UPLOAD_CHUNK = 64 * 1024 * 1024    # wysyłka w Pythonie: 64 MB (9,6–11 vs 8 MB/s przy 8 MB)
ROBOCOPY_MIN = 32 * 1024 * 1024    # mniejsze pliki — nie warto startować procesu
_PCT = re.compile(rb"(\d{1,3}(?:[.,]\d+)?)%")


def _robocopy_exe() -> Optional[str]:
    if sys.platform != "win32":
        return None
    return shutil.which("robocopy")


def robocopy_upload(src, tmp, on_progress: Optional[ProgCB] = None,
                    label: str = "") -> None:
    """Kopia src→tmp przez robocopy (Windows). Pomiar wysyłki na NAS przez
    internet (Tailscale, 33 ms): robocopy 12–13 MB/s, najlepsza kopia w
    Pythonie (1 strumień, blok 64 MB) ~11 MB/s, CopyFile2 6,4 MB/s, zapisy
    równoległe 6–7 MB/s. robocopy nie zmienia nazwy, więc kopiujemy HARDLINK
    źródła o nazwie `tmp.name` z prywatnego katalogu obok źródła (ten sam
    wolumin, bez kopii); źródło zostaje nietknięte. Błąd → OSError (wołający
    przechodzi na kopię w Pythonie)."""
    import subprocess
    src, tmp = Path(src), Path(tmp)
    exe = _robocopy_exe()
    if exe is None:
        raise OSError("robocopy niedostępne")
    total = src.stat().st_size
    stage = src.parent / (".rh_upload_" + uuid.uuid4().hex[:12])
    stage.mkdir()
    try:
        os.link(src, stage / tmp.name)
        if on_progress is not None:
            on_progress(0, total, label)
        # /IS /IT — kopiuj nawet gdy w celu leży „taki sam" stary tmp;
        # /R:2 /W:5 — domyślnie robocopy ponawia milion razy co 30 s
        # „Z:\" w cudzysłowie robocopy czyta jako escapowany cudzysłów
        dst_dir = str(tmp.parent)
        if dst_dir.endswith(("\\", "/")):
            dst_dir += "."
        cmd = [exe, str(stage), dst_dir, tmp.name, "/R:2", "/W:5",
               "/IS", "/IT", "/NJH", "/NJS", "/NDL", "/NC", "/BYTES"]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        tail = b""
        last = -1
        assert proc.stdout is not None
        while True:
            data = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") \
                else proc.stdout.read(4096)
            if not data:
                break
            tail = (tail + data)[-8192:]
            if on_progress is not None:
                m = None
                for m in _PCT.finditer(data):
                    pass
                if m is not None:
                    pct = float(m.group(1).replace(b",", b"."))
                    done = min(total, int(total * pct / 100))
                    if done != last:
                        last = done
                        on_progress(done, total, label)
        rc = proc.wait()
        # robocopy: bit 0 = skopiowano, >= 8 = błąd; 0 = nic nie skopiowano
        if rc >= 8 or not rc & 1:
            msg = tail.decode("oem" if sys.platform == "win32" else "utf-8",
                              errors="replace").strip().splitlines()
            raise OSError(f"robocopy kod {rc}: {' | '.join(msg[-3:])}")
        got = tmp.stat().st_size
        if got != total:
            raise OSError(f"robocopy: niepełna kopia {tmp} ({got}/{total} B)")
        if on_progress is not None:
            on_progress(total, total, label)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def move_with_progress(src, dst, on_progress: Optional[ProgCB] = None,
                       label: str = "", ensure_parent: bool = True) -> None:
    """Przenosi src→dst. Ten sam wolumin → os.replace (natychmiast, bez kopii).
    Inny wolumin (np. RAM R: → D:) → kopia blokami z postępem + usunięcie
    źródła. Przy błędzie w połowie kopii kasujemy plik tymczasowy (nic
    niekompletnego nie ląduje pod docelową nazwą)."""
    src, dst = Path(src), Path(dst)
    # ensure_parent=False — wołający już zapewnił katalog (na NAS mkdir to
    # 2 rundy SMB na KAŻDY plik)
    if ensure_parent:
        dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dst)        # atomowy rename (ten sam dysk)
        return
    except FileNotFoundError:
        if not ensure_parent and src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)   # katalog jednak znikł
            os.replace(src, dst)
            return
        raise
    except OSError:
        pass                        # cross-device — kopiujemy niżej
    tmp = dst.with_name(dst.name + ".chdbuddy_move_tmp")
    try:
        # WYSYŁKA = JEDEN strumień. Równoległy zapis w różne miejsca pliku na
        # NAS (NTFS po drugiej stronie dopełnia zerami wszystko przed miejscem
        # zapisu) dawał ~0,1 MB/s wobec 5,4 MB/s zapisu kolejnego (pomiar
        # 0.6.78). Równolegle tylko POBIERANIE (copy_parallel).
        # Duży plik → robocopy (najszybsza wysyłka w pomiarze 0.6.79); gdy
        # zawiedzie — ten sam strumień w Pythonie, blokami 64 MB.
        sent = False
        try:
            size = src.stat().st_size
        except OSError:
            size = 0
        if size >= ROBOCOPY_MIN and _robocopy_exe() is not None:
            try:
                robocopy_upload(src, tmp, on_progress, label)
                sent = True
            except OSError:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        if not sent:
            copy_with_progress(src, tmp, on_progress, label, chunk=UPLOAD_CHUNK)
        os.replace(tmp, dst)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    try:
        os.unlink(src)              # źródło usuwamy dopiero po udanej kopii
    except OSError:
        pass
