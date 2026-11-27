# ROM Helper

> Formerly **CHD Buddy**. The Python package and CLI keep the names `chd_buddy` / `chd-buddy`.

**ROM Helper** audits, organizes and repairs ROM and disc-image collections against **DAT files** (Redump, No-Intro, 1G1R/Retool, FinalBurn Neo, MAME…). It works like RomVault, with native support for **CHD, RVZ, ZIP and 7z**. Each game is stored once, with **hardlinks** for other sets, and the program stays fast on a **NAS**, even one reached over the internet.

📖 **User guide (wiki): https://github.com/C4rl0s79/RomHelper/wiki**

⬇️ **Download:** [Releases](https://github.com/C4rl0s79/RomHelper/releases): `ROM Helper.exe` (Windows, portable) and a Linux source package.

---

## ⚠️ Required programs

ROM Helper **does not include** these tools; it calls them. Details: [Required programs](https://github.com/C4rl0s79/RomHelper/wiki#required-programs).

| Program | Needed for | Without it |
|---|---|---|
| **chdman** (from [MAME](https://www.mamedev.org/release.html)) | **Every disc system**: identifying, converting and repairing CHD | Disc games stored as CHD cannot be recognized; no CHD conversion or repair |
| **DolphinTool** (ships with [Dolphin](https://dolphin-emu.org/download/)) | **GameCube / Wii** as RVZ | No conversion to RVZ and no RVZ verification |
| **ImDisk** ([Toolkit](https://sourceforge.net/projects/imdisk-toolkit/)) | Optional RAM disk for temporary CHD work | Temporary files go to a physical disk |
| **7-Zip** | Optional, only for emulator updates delivered as `.7z` | Those updates fail (`.7z` files in your collection are still supported) |

Put `chdman.exe` next to `ROM Helper.exe` or in your PATH. DolphinTool is found in your emulators folder. **No Python, Qt or .NET runtime is needed, and no administrator rights.**

---

## What it does

- **Scan once, remember everything.** A local index keeps the checksum of every file, including archive members and the data inside each CHD, so later scans only read new or changed files.
- **Report per DAT and per game:** complete / to fix / missing, with colours as in RomVault.
- **Preview, then fix.** *Find fixes* shows the complete plan without touching a file. *Fix* then renames, moves, extracts, links, converts and rebuilds. You can cancel at any time and resume later.
- **Safe conversions:** cartridge → ZIP, disc → CHD, GameCube/Wii → RVZ. Each is verified (SHA-1, CHD round-trip, DolphinTool verify) before the source is removed. Nothing is overwritten, and unknown files go to **ToSort**.
- **One physical copy per game.** The order of your DAT folders (e.g. `ROMS` → `No-Intro` → `1G1R`) decides where the file lives. Lower sets get hardlinks.
- **CHD repair:** detects DVD games packed as CD, and CHDs whose track layout does not match the DAT, and rebuilds them (Redump cue sheets supported).
- **Arcade sets** in split / non-merged / merged format, with BIOS sets kept separate.
- **Fan translations** can be swapped into the slot of the original game. Originals are kept in ToSort and the swap can be undone.
- **Extras:** update a game to a newer dump, box-art icons, `.lnk` shortcuts with the right emulator command line, `.m3u` playlists, BIOS installer, emulator updater.

## Quick start

1. Download `ROM Helper.exe` into its own folder and add `chdman.exe` (see above).
2. Start it. To switch the interface language, use *Tools → Language / Język…* → **English** and restart.
3. Set the **DAT folder**, **ROM folder** and **ToSort** folder on the *Collection (DAT)* tab.
4. **📋 Load DATs** → **🔍 Scan and report** → **🔎 Find fixes** (preview) → **🔧 Fix (apply)**.

Full walkthrough: [Quick Start](https://github.com/C4rl0s79/RomHelper/wiki/Quick-Start).

## Documentation

| Topic | Wiki page |
|---|---|
| Installation (Windows, Linux, from source) | [Installation](https://github.com/C4rl0s79/RomHelper/wiki/Installation) |
| DAT tree, ToSort, index, hierarchy, formats | [Core Concepts](https://github.com/C4rl0s79/RomHelper/wiki/Core-Concepts) |
| Every button and option | [The Main Window](https://github.com/C4rl0s79/RomHelper/wiki/The-Main-Window) |
| Scan → find fixes → fix, in detail | [Scanning and Fixing](https://github.com/C4rl0s79/RomHelper/wiki/Scanning-and-Fixing) |
| Formats, folder names, priorities, arcade sets | [DAT Settings and Hierarchy](https://github.com/C4rl0s79/RomHelper/wiki/DAT-Settings-and-Hierarchy) |
| Fan translations, newer dumps | [Translations and Game Updates](https://github.com/C4rl0s79/RomHelper/wiki/Translations-and-Game-Updates) |
| NAS, RAM disk, compression | [Performance, NAS and RAM Disk](https://github.com/C4rl0s79/RomHelper/wiki/Performance-NAS-and-RAM-Disk) |
| Index, icons & shortcuts, BIOS, updates, CLI | [Other Tabs and Tools](https://github.com/C4rl0s79/RomHelper/wiki/Other-Tabs-and-Tools) |
| Files the program stores, backups | [Files and Settings](https://github.com/C4rl0s79/RomHelper/wiki/Files-and-Settings) |
| Problems and answers | [Troubleshooting and FAQ](https://github.com/C4rl0s79/RomHelper/wiki/Troubleshooting-and-FAQ) |

Changes per version: [CHANGELOG.md](CHANGELOG.md).

## Running from source

```bash
pip install -e .[gui,archives,icons]   # GUI + .7z support + icon generation
chd-buddy-suite                        # start the program
chd-buddy --help                       # command-line interface
```

On Linux, use the `chd_buddy-<version>-linux.zip` package from the releases. It contains `install.sh`, `run.sh` and `cli.sh`, and the system packages you need are listed on the [Installation](https://github.com/C4rl0s79/RomHelper/wiki/Installation) page.

Build the Windows executable:

```bash
pyinstaller --noconfirm chd_buddy.spec   # → dist/ROM Helper.exe
```

## Reporting problems

Open an [issue](https://github.com/C4rl0s79/RomHelper/issues) with the program version, the relevant log from the `logs\` folder next to the exe and, if present, `chd_buddy_crash.log`.
