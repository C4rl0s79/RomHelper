"""AUDYT „planowanie nie dotyka NAS": pełny podgląd (dry_run) całej kolekcji
na KOPII indeksu; KAŻDE wywołanie systemu plików na Z: jest liczone z miejscem
w kodzie i obsługiwane z INDEKSU (emulacja), bez sięgania do NAS. Wynik:
audit_fs.txt — ranking miejsc (plik:linia funkcja) z liczbą wywołań.

Uruchomienie (przy zamkniętym lub działającym programie — indeks jest
kopiowany backupem SQLite):
    python tools/audit_planning_io.py --out <katalog_roboczy> [fragment_DAT…]
Cel: „WYWOŁANIA NAS w planowaniu" = tylko pojedyncze odczyty konfiguracji;
każda pozycja z setkami/tysiącami wywołań to pętla do przeniesienia na indeks."""
import argparse
import builtins
import io
import os
import stat as S
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict

from pathlib import Path

_ap = argparse.ArgumentParser(description="Audyt I/O planowania naprawy")
_ap.add_argument("--out", required=True,
                 help="katalog roboczy: kopia indeksu i raporty")
_ap.add_argument("--exe", default=r"D:\Rom Helper\RomHelper.exe",
                 help="exe programu (ustawienia i indeks leżą obok)")
_ap.add_argument("only", nargs="*", help="fragmenty nazw DAT-ów (opcjonalnie)")
_args = _ap.parse_args()
SP = Path(_args.out)
SP.mkdir(parents=True, exist_ok=True)
ONLY = _args.only             # opcjonalnie: fragmenty nazw DAT-ów do audytu

sys.frozen = True                    # ustawienia/indeks jak w programie
sys.executable = _args.exe
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chd_buddy.core.settings import Settings
st = Settings.load()

# KOPIA indeksu backupem SQLite — żywa baza nie jest w WAL, długi odczyt
# blokowałby zapisy działającego programu
import sqlite3 as _sq
from chd_buddy.core.fileindex import default_db_path
_live = Path(st.index_db_path) if st.index_db_path else default_db_path()
_src = _sq.connect(f"file:{_live}?mode=ro", uri=True, timeout=30)
_dst = _sq.connect(str(SP / "audit_index.sqlite3"))
_src.backup(_dst)
_src.close()
_dst.close()

# 1) DAT-y — POZA liczeniem (w GUI są już w pamięci przy Napraw)
from chd_buddy.core.datstore import DatStore
from chd_buddy.core.dirrules import DirRules, apply_rule_targets
t0 = time.time()
ents = DatStore(Path(st.dat_root), Path(st.rom_root)).discover()
apply_rule_targets(ents, DirRules(Path(st.dat_root)), Path(st.rom_root))
print(f"DAT-y: {len(ents)} w {time.time()-t0:.0f}s", flush=True)
if ONLY:
    ents = [e for e in ents if any(o.lower() in e.name.lower() for o in ONLY)]

# 2) emulacja NAS z indeksu
import sqlite3
db = sqlite3.connect(str(SP / "audit_index.sqlite3"))
nc = os.path.normcase
FILES: dict = {}
CHILD: dict = defaultdict(dict)       # dir -> {name: is_dir}
for p, size, mt, lnk in db.execute(
        "SELECT path, size, mtime_ns, is_link FROM files WHERE missing=0"):
    FILES[nc(p)] = (size or 0, mt or 0, bool(lnk))
    d, name = os.path.split(p)
    CHILD[nc(d)][name] = False
    while True:
        pd, pn = os.path.split(d)
        if not pn or pd == d:
            break
        CHILD[nc(pd)][pn] = True
        d = pd
db.close()
print(f"indeks: {len(FILES)} plików", flush=True)

REAL = {n: getattr(os, n) for n in ("stat", "lstat", "scandir", "listdir")}
REALP = {n: getattr(os.path, n) for n in
         ("exists", "lexists", "isfile", "isdir", "islink", "getsize",
          "getmtime")}
REAL_OPEN = builtins.open
REAL_POPEN = subprocess.Popen.__init__
HITS: Counter = Counter()
SAMPLE: dict = {}
PER_DIR: Counter = Counter()
cur = {"kat": ""}
_tl = threading.local()


def _nas(p) -> bool:
    try:
        s = os.fspath(p)
    except TypeError:
        return False
    if isinstance(s, bytes):
        return False
    return s[:2].upper() == "Z:" or s.startswith("\\\\")


def _site() -> str:
    f = sys._getframe(2)
    chain = []
    while f is not None and len(chain) < 2:
        fn = f.f_code.co_filename.replace("\\", "/")
        if "/chd_buddy/" in fn:
            chain.append(f"{os.path.basename(fn)}:{f.f_lineno} "
                         f"{f.f_code.co_name}")
        f = f.f_back
    return " ← ".join(chain) or "(poza programem)"


def _hit(kind, p):
    if getattr(_tl, "busy", False):
        return
    _tl.busy = True
    try:
        k = (kind, _site())
        HITS[k] += 1
        SAMPLE.setdefault(k, str(p))
        PER_DIR[cur["kat"]] += 1
    finally:
        _tl.busy = False


def _isdir_idx(p):
    return nc(os.path.abspath(os.fspath(p))) in CHILD


def _row(p):
    return FILES.get(nc(os.path.abspath(os.fspath(p))))


def _mkstat(p, follow):
    r = _row(p)
    if r is not None:
        size, mt, lnk = r
        mode = (S.S_IFLNK | 0o777) if (lnk and not follow) else (S.S_IFREG | 0o666)
        return os.stat_result((mode, 1, 1, 1, 0, 0, size, mt // 10**9,
                               mt // 10**9, mt // 10**9))
    if _isdir_idx(p):
        return os.stat_result((S.S_IFDIR | 0o777, 1, 1, 1, 0, 0, 0, 0, 0, 0))
    raise FileNotFoundError(2, "brak (indeks)", os.fspath(p))


def f_stat(p, *a, **k):
    if _nas(p):
        _hit("stat", p)
        return _mkstat(p, k.get("follow_symlinks", True))
    return REAL["stat"](p, *a, **k)


def f_lstat(p, *a, **k):
    if _nas(p):
        _hit("lstat", p)
        return _mkstat(p, False)
    return REAL["lstat"](p, *a, **k)


class _DE:
    def __init__(self, d, name, isdir):
        self.name, self.path, self._d = name, os.path.join(d, name), isdir

    def is_dir(self, follow_symlinks=True):
        return self._d

    def is_file(self, follow_symlinks=True):
        return not self._d

    def is_symlink(self):
        r = _row(self.path)
        return bool(r and r[2])

    def stat(self, follow_symlinks=True):
        return _mkstat(self.path, follow_symlinks)

    def __fspath__(self):
        return self.path


class _SD:
    def __init__(self, items):
        self._it = items

    def __iter__(self):
        return iter(self._it)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass


def f_scandir(p="."):
    if _nas(p):
        _hit("scandir", p)
        d = os.path.abspath(os.fspath(p))
        ch = CHILD.get(nc(d))
        if ch is None:
            raise FileNotFoundError(2, "brak katalogu (indeks)", d)
        return _SD([_DE(d, n, isd) for n, isd in ch.items()])
    return REAL["scandir"](p)


def f_listdir(p="."):
    if _nas(p):
        _hit("listdir", p)
        ch = CHILD.get(nc(os.path.abspath(os.fspath(p))))
        if ch is None:
            raise FileNotFoundError(2, "brak katalogu (indeks)", os.fspath(p))
        return list(ch)
    return REAL["listdir"](p)


def _mkp(name, fn):
    def g(p, *a, **k):
        if _nas(p):
            _hit(name, p)
            return fn(p)
        return REALP[name](p, *a, **k)
    return g


def _exists(p):
    return _row(p) is not None or _isdir_idx(p)


def _getsize(p):
    r = _row(p)
    if r is None:
        raise FileNotFoundError(2, "brak (indeks)", os.fspath(p))
    return r[0]


def f_open(file, mode="r", *a, **k):
    if isinstance(file, (str, os.PathLike)) and _nas(file):
        _hit(f"open({mode})", file)
    return REAL_OPEN(file, mode, *a, **k)


def f_popen(self, args, *a, **k):
    flat = args if isinstance(args, (list, tuple)) else [args]
    if any(isinstance(x, (str, os.PathLike)) and _nas(x) for x in flat):
        _hit("subprocess", " ".join(map(str, flat))[:160])
    return REAL_POPEN(self, args, *a, **k)


os.stat, os.lstat = f_stat, f_lstat
os.scandir, os.listdir = f_scandir, f_listdir
os.path.exists = _mkp("exists", _exists)
os.path.lexists = _mkp("lexists", _exists)
os.path.isfile = _mkp("isfile", lambda p: _row(p) is not None)
os.path.isdir = _mkp("isdir", _isdir_idx)
os.path.islink = _mkp("islink", lambda p: bool((_row(p) or (0, 0, False))[2]))
os.path.getsize = _mkp("getsize", _getsize)
os.path.getmtime = _mkp("getmtime", lambda p: (_row(p) or (0, 0, 0))[1] / 1e9)
builtins.open = io.open = f_open
subprocess.Popen.__init__ = f_popen
# nagłówki CHD czytane chdmanem — liczymy, nie uruchamiamy
from chd_buddy.core import chdrebuild as _cr
_real_tracks = _cr._chd_cd_tracks


def _fake_tracks(chd, path):
    _hit("chdman info", path)
    return 0
_cr._chd_cd_tracks = _fake_tracks

# 3) pełny podgląd
from chd_buddy.core.fileindex import FileIndex
from chd_buddy.core.repair import RepairOptions, repair_collection

logf = REAL_OPEN(SP / "audit_fs_log.txt", "w", encoding="utf-8", buffering=1)
T0 = time.time()


def log(m):
    if m.startswith("══ KATALOG"):
        cur["kat"] = m[2:70]
    logf.write(f"{time.time()-T0:8.1f}  {m}\n")


opts = RepairOptions(
    dats=st.dat_root, roms=st.rom_root, tosort=st.tosort_dir,
    tosorts=list(st.tosort_dirs), clean=True,
    only_complete=not st.fix_incomplete, dedup=st.fix_dedup,
    del_tosort=st.fix_del_tosort, convert=True, make_links=True, dry=True)
with FileIndex(SP / "audit_index.sqlite3") as idx:
    stats = repair_collection(opts, st, ents, idx, log=log,
                              progress=lambda d, t, s: None,
                              cancel=threading.Event())
logf.close()

with REAL_OPEN(SP / "audit_fs.txt", "w", encoding="utf-8") as out:
    out.write(f"czas podglądu: {time.time()-T0:.0f}s; wynik: "
              f"{stats.summary() if stats else None}\n")
    out.write(f"WYWOŁANIA NAS w planowaniu: {sum(HITS.values())}\n\n")
    for (kind, site), n in HITS.most_common(60):
        out.write(f"{n:8d}  {kind:12s} {site}\n          np. "
                  f"{SAMPLE[(kind, site)][:150]}\n")
    out.write("\n== najwięcej wywołań per katalog ==\n")
    for k, n in PER_DIR.most_common(25):
        out.write(f"{n:8d}  {k}\n")
print("gotowe", flush=True)
