"""Kolejność katalogów DAT-ów = priorytet rodzic → dzieci.

Użytkownik układa katalogi w drzewie DAT-ów (przesuwa wyżej/niżej): katalog
WYŻEJ ma pierwszeństwo nad niższymi. Jego DAT-y są przetwarzane pierwsze, więc
to one trzymają pliki fizycznie, a identyczne pliki w niższych katalogach
dostają symlinki. Przykład: ROMS → No-intro → 1G1R.

Plik ``_kolejnosc.json`` w katalogu DAT-ów (obok ``_reguly.json``)::

    {"version": 1, "order": {"": ["ROMS", "No-intro", "1G1R"],
                             "ROMS": ["Sony", "Nintendo"]}}

Klucz = ścieżka katalogu-rodzica względem dat_root („" = korzeń, separator
„/"), wartość = kolejność jego podkatalogów. Katalogi spoza listy stoją za
wymienionymi — najpierw oznaczone jako rodzice (reguła ``parent_priority``,
dotychczasowy mechanizm), potem alfabetycznie. Dzięki temu bez zapisanej
kolejności wszystko działa jak dawniej, a pierwsze przesunięcie startuje od
kolejności, którą użytkownik widzi. Porównanie nazw bez wielkości liter.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ORDER_FILENAME = "_kolejnosc.json"


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def load_order(dat_root) -> dict:
    """{ścieżka_rodzica_lower: [nazwa_lower, …]} — pusty słownik gdy brak pliku."""
    p = Path(dat_root) / ORDER_FILENAME
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = data.get("order") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {_norm(k): [_norm(x) for x in v if isinstance(x, str)]
            for k, v in raw.items() if isinstance(v, list)}


def _load_raw(dat_root) -> dict:
    p = Path(dat_root) / ORDER_FILENAME
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        raw = data.get("order") if isinstance(data, dict) else None
        return dict(raw) if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def save_order(dat_root, order: dict) -> Path:
    p = Path(dat_root) / ORDER_FILENAME
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": 1, "order": order},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return p


def sibling_index(order: dict, parent_key: str, name: str, is_parent=None):
    """Klucz sortowania podkatalogu `name` wśród rodzeństwa.

    Wymienione w kolejności: (pozycja,); pozostałe: za nimi, rodzice
    (`is_parent(ścieżka)`) przed resztą, dalej alfabetycznie."""
    lst = order.get(_norm(parent_key), [])
    n = _norm(name)
    if n in lst:
        return (lst.index(n), 0, "")
    path = f"{parent_key}/{name}" if parent_key else name
    flag = 0 if (is_parent is not None and is_parent(path)) else 1
    return (len(lst), flag, n)


def folder_rank(dat_path, dat_root, order: dict, is_parent=None) -> tuple:
    """Klucz sortowania DAT-a wg kolejności jego katalogów (od korzenia w dół).

    Dłuższa ścieżka nie przegrywa z krótszą tylko przez długość — porównanie
    idzie poziom po poziomie, a DAT leżący wprost w katalogu stoi przed jego
    podkatalogami (pusta krotka < niepusta)."""
    try:
        parts = Path(dat_path).parent.relative_to(Path(dat_root)).parts
    except ValueError:
        parts = ()
    out = []
    parent = ""
    for part in parts:
        out.append(sibling_index(order, parent, part, is_parent))
        parent = f"{parent}/{part}" if parent else part
    return tuple(out)


def move_folder(dat_root, folder_key: str, delta: int, siblings,
                is_parent=None) -> bool:
    """Przesuwa katalog `folder_key` („ROMS" albo „ROMS/Sony") o `delta` pozycji
    wśród rodzeństwa. `siblings` = nazwy podkatalogów tego samego rodzica
    OBECNE w drzewie (do uzupełnienia listy). Zwraca True gdy coś się zmieniło.

    Zapisywana jest PEŁNA kolejność rodzeństwa (z dotychczasową kolejnością
    i nowymi katalogami alfabetycznie na końcu), żeby pozycje pozostałych
    katalogów nie skakały. Wielkość liter nazw zostaje taka jak w drzewie."""
    parts = [p for p in str(folder_key).replace("\\", "/").split("/") if p]
    if not parts:
        return False
    name = parts[-1]
    parent = "/".join(parts[:-1])
    order = load_order(dat_root)
    names = {_norm(s): s for s in siblings}
    names.setdefault(_norm(name), name)
    current = sorted(names, key=lambda n: sibling_index(
        order, parent, names[n], is_parent))
    i = current.index(_norm(name))
    j = i + int(delta)
    if not 0 <= j < len(current):
        return False
    current[i], current[j] = current[j], current[i]
    raw = _load_raw(dat_root)
    raw = {k: v for k, v in raw.items() if _norm(k) != _norm(parent)}
    raw[parent] = [names[n] for n in current]
    save_order(dat_root, raw)
    return True


def position_label(dat_root, folder_key: str, siblings, order: dict | None = None,
                   is_parent=None) -> int:
    """Numer pozycji (od 1) katalogu wśród rodzeństwa — do etykiety w drzewie."""
    parts = [p for p in str(folder_key).replace("\\", "/").split("/") if p]
    if not parts:
        return 0
    order = load_order(dat_root) if order is None else order
    parent = "/".join(parts[:-1])
    names = {_norm(s): s for s in siblings}
    names.setdefault(_norm(parts[-1]), parts[-1])
    current = sorted(names, key=lambda n: sibling_index(
        order, parent, names[n], is_parent))
    return current.index(_norm(parts[-1])) + 1
