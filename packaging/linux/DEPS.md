# chd_buddy na Linuksie — zależności systemowe

`install.sh` stawia środowisko Pythona (`.venv`) i instaluje biblioteki z
`requirements-linux.txt`. Tego, co poniżej, skrypt **nie** zainstaluje sam —
wymaga to `sudo` i różni się między dystrybucjami.

## Minimum

| Co | Po co | Bez tego |
|---|---|---|
| Python 3.11+ z modułem `venv` | całość | nic nie ruszy |
| `chdman` (z MAME) | audyt, konwersja, naprawa CHD | zostaje sam skan plików |
| biblioteki Qt (dla PySide6) | GUI | działa tylko `./cli.sh` |
| `7z` | aktualizacja emulatorów z archiwów `.7z` | ta jedna funkcja |

## Instalacja

### Debian / Ubuntu / Linux Mint / Pop!\_OS

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip mame-tools p7zip-full libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 libegl1
```

### Fedora / RHEL / Nobara

```bash
sudo dnf install -y python3 python3-pip mame-tools p7zip xcb-util-cursor libxkbcommon-x11 mesa-libEGL
```

### Arch / Manjaro / EndeavourOS

```bash
sudo pacman -S --needed python python-pip mame-tools p7zip xcb-util-cursor libxkbcommon-x11
```

### openSUSE

```bash
sudo zypper install python311 python311-pip mame-tools p7zip-full xcb-util-cursor libxkbcommon-x11-0
```

### Steam Deck (SteamOS)

System plików jest tylko do odczytu, więc `pacman` odpada bez `steamos-readonly
disable`. Zamiast tego:

- **chdman** — z Flatpaka `org.mamedev.MAME` (`flatpak install flathub
  org.mamedev.MAME`), a potem wskaż ścieżkę do `chdman` w ustawieniach programu;
- **biblioteki Qt** — są już w systemie, PySide6 z pipa działa;
- ROM-y i skróty trzymaj na karcie SD sformatowanej w **ext4** albo **btrfs** —
  na exFAT nie da się tworzyć symlinków, których program używa do współdzielenia
  torów (patrz niżej).

## Weryfikacja

```bash
./install.sh --check
```

Wypisze, czego brakuje, bez ruszania środowiska.

## Rzeczy specyficzne dla Linuksa

**Symlinki.** Na Windows wymagają trybu dewelopera lub admina; na Linuksie są
zwykłą operacją użytkownika — program nie prosi o żadne podniesienie uprawnień.
Jedyny realny problem to system plików bez ich obsługi (FAT32/exFAT, NTFS
zamontowany bez `-o symlinks`). Zakładka z ustawieniami pokazuje status.

**Skróty do gier.** Zamiast `.lnk` powstają pliki `.desktop` (freedesktop) z
bitem wykonywalnym. Emulator jest szukany po kolei w: katalogu emulatorów
(także pliki `.AppImage`), `PATH`, na końcu we Flatpaku — wtedy skrót uruchamia
`flatpak run <appid> …`.

**Ikony gier.** Zamiast `.ico` zapisywane są pliki `.png` (256 px) — tego chce
klucz `Icon=` w `.desktop`.

**Rdzenie RetroArch.** Szukane w: katalogu obok binarki, `~/.config/retroarch/
cores`, `~/.var/app/org.libretro.RetroArch/config/retroarch/cores` oraz
`/usr/lib/libretro`. W skrócie zapisywana jest pełna ścieżka do `.so`.

**Wielkość liter.** Linuksowe systemy plików rozróżniają wielkość liter, a DAT-y
Redump/No-Intro bywają niekonsekwentne. Jeśli ROM-y trzymasz na wspólnym dysku
z Windowsem, dopasowanie nazw może dać inne wyniki niż tam.
