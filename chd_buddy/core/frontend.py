"""Pliki FRONTENDU (EmulationStation/RetroBat/Batocera) — nie są grami.

DAT-y dir2dat zrobione z folderu frontendu (Arcade1TB z RetroBata) zawierają
„gry" z każdego podfolderu i pliku: `images`, `videos`, `manuals`, `mixart`,
`gamelist.xml`… Program nie może ich konwertować, pakować, przenosić, kasować
ani wynosić do ToSort (0.6.94: images.chd, manuals.zip z kasowaniem źródeł,
gamelist.xml do ToSort). JEDNA reguła dla wczytania DAT-u i sprzątania.
"""
from __future__ import annotations

from pathlib import Path, PurePath

# foldery mediów/scrapera frontendów (+ kopie edytora) — nazwy DOKŁADNE
FRONTEND_DIRS = frozenset({
    "images", "videos", "manuals", "mixart", "wheel", "snap", "snaps",
    "marquee", "marquees", "thumbnails", "screenshots", "fanart", "boxart",
    "titles", "box2dfront", "box3d", "boxback", "bezel", "bezels", "map",
    "maps", "downloaded_images", "downloaded_videos", "downloaded_media",
    "nppbackup",
})


def is_frontend_name(name: str) -> bool:
    """Nazwa „gry" z DAT-u dir2dat albo pliku: folder frontendu albo
    `gamelist*` (gamelist.xml, gamelist.xml.backup1, gamelist.xml.old…)."""
    n = (name or "").strip().lower()
    return n in FRONTEND_DIRS or n.startswith("gamelist")


def is_frontend_rel(rel) -> bool:
    """Ścieżka WZGLĘDNA (od katalogu DAT-u / folderu systemu): leży w folderze
    frontendu albo jest plikiem `gamelist*`."""
    parts = PurePath(str(rel)).parts
    if not parts:
        return False
    if any(p.lower() in FRONTEND_DIRS for p in parts[:-1]):
        return True
    return parts[-1].lower().startswith("gamelist")


def is_frontend_under(path, base) -> bool:
    """`path` pod `base` jest plikiem frontendu (False, gdy nie leży pod)."""
    try:
        rel = Path(str(path)).relative_to(Path(str(base)))
    except ValueError:
        return False
    return is_frontend_rel(rel)


# Rozszerzenia plików, które NIE są obrazem gry (DAT-y dir2dat opisują każdy
# plik folderu frontendu): media, opisy, konfiguracje, łatki, porty/silniki.
# Konwersja formatu (zip/chd/rvz) ich nie dotyka (0.7.07: naprawa spakowała
# `halflife\extras.pak`, `valve\config.cfg`, `.ips`, `Settings.ini`,
# `anarch.libretro`, `framework.singe`, `__ia_thumb.jpg`).
NOT_ROM_EXTS = frozenset({
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "ico",
    "mp4", "mkv", "avi", "webm", "mov",
    "pdf", "txt", "nfo", "doc", "docx", "htm", "html", "rtf",
    "cfg", "ini", "conf", "json", "xml", "yml", "yaml", "lua", "singe",
    "log", "bak", "old", "lnk", "url",
    "ips", "bps", "ups", "xdelta", "ppf", "aps",
    "exe", "dll", "so", "bat", "cmd", "sh", "libretro", "pak", "pk3", "wad",
    "ttf", "otf", "keys", "m3u", "sav", "srm", "state", "cht", "pad",
})

# Obrazy PŁYT i kontenery konsol — nigdy do zipa (emulatory nie czytają
# płyty z zipa; 0.7.07: `triforce\Mario Kart Arcade GP.iso` → zip).
DISC_IMAGE_EXTS = frozenset({
    "iso", "cue", "gdi", "toc", "ccd", "mds", "mdf", "nrg", "cdi", "img",
    "chd", "rvz", "gcm", "gcz", "wbfs", "wia", "cso", "pbp", "nsp", "xci",
    "pkg", "xex",
})


def is_not_rom_file(name: str) -> bool:
    """Plik o rozszerzeniu spoza obrazów gier (patrz NOT_ROM_EXTS)."""
    n = str(name or "").lower()
    return "." in n and n.rsplit(".", 1)[-1] in NOT_ROM_EXTS


def is_disc_image(name: str) -> bool:
    """Obraz płyty / kontener konsoli (patrz DISC_IMAGE_EXTS)."""
    n = str(name or "").lower()
    return "." in n and n.rsplit(".", 1)[-1] in DISC_IMAGE_EXTS


def drop_frontend_games(games) -> list:
    """Gry DAT-u bez „gier" frontendu (foldery mediów, gamelist*)."""
    return [g for g in games if not is_frontend_name(getattr(g, "name", ""))]
