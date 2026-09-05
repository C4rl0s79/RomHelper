# Changelog — ROM Kombajn (chd_buddy)

Format: [semver](https://semver.org). Najnowsze na górze.

## [0.5.0] — 2026-09-05

### Dodane
- **Format ClrMamePro** obsługiwany obok Logiqx XML — `parse_dat` auto-wykrywa
  format (po pierwszym znaku) i parsuje tekstowe `game ( … rom ( … ) )`
  (`datfile._parse_cmpro` + `_cmpro_header`; test
  `test_discover_reads_clrmamepro_dat`). Realny przypadek: libretro
  `BIOS\System.dat` (396 BIOS-ów) teraz się wczytuje.
- **Sidecar-JSON RomVaulta** (opcjonalny — nie każdy DAT go ma): przy skanie
  wczytujemy metadane obok `.dat` (dopasowanie po `datName`), zapisane w
  `DatEntry.meta` (group/system/version/datROMsSize; `datstore._sidecar_meta`).
- **Auto-wykrycie kolekcji tłumaczeń**: DAT z grupą/nazwą `[T-…]` (np.
  „[T-En]Collection") staje się pulą wariantów BEZ ręcznego ustawiania roli;
  język czytany też z grupy/systemu JSON (`translations.is_translation_collection`,
  `build_variant_index`).

### Naprawione
- **Uszkodzony/pusty/nie-DAT plik nie wywala już skanu.** Twardy błąd parsowania
  (`ElementTree.ParseError: line 1, column 0`) jest łapany, a plik bez gier
  (pusty/nieczytelny) pomijany z komunikatem „POMIJAM …" — reszta kolekcji
  wczytuje się normalnie (`datstore.discover`; test
  `test_discover_skips_corrupt_dat`).
- **Sprzątanie ToSort po CHD:** wspólne tory (filler GD-ROM) redukowane do 1
  kopii w przebiegu, puste podkatalogi usuwane
  (`convert._purge_redundant_tosort_tracks`).

## [0.4.0] — 2026-09-04

### Dodane — wsparcie dla Linuksa (paczka źródłowa, bez binarki)
- **Skróty do gier `.desktop`** zamiast `.lnk`. Argumenty są cytowane wg
  specyfikacji Desktop Entry (spacje, `"`, `` ` ``, `$`, a literalny `%` jako
  `%%`), plik powstaje atomowo i z bitem wykonywalnym — bez `chmod +x` GNOME
  i KDE pokazują skrót jako plik tekstowy. (`shortcuts._write_desktop_batch`)
- **Wykrywanie emulatorów na Linuksie**: katalog emulatorów (także pliki
  `.AppImage`), potem `PATH`, na końcu Flatpak — wtedy skrót uruchamia
  `flatpak run <appid> …`, więc model skrótu (target + argumenty) zostaje bez
  zmian. Rejestr `EMULATORS` dostał `nix_globs` / `nix_bins` / `nix_flatpak`.
  Xenia świadomie bez wpisu — brak wydania natywnego.
- **Rdzenie RetroArch** szukane też w `~/.config/retroarch/cores`, katalogu
  Flatpaka i `/usr/lib/libretro`; w skrócie ląduje pełna ścieżka do `.so`
  (na Windows bez zmian: `cores\<core>_libretro.dll`).
- **Ikony gier jako `.png`** (256 px) na Linuksie — tego wymaga klucz `Icon=`
  w `.desktop`. Na Windows dalej wielorozmiarowe `.ico`. (`icons.ICON_EXT`)
- **Paczka `chd_buddy-<wersja>-linux.zip`**: źródła + `install.sh` (venv,
  zależności, sprawdzenie `chdman`/7z/Qt, opcjonalny wpis w menu przez
  `--desktop`), `run.sh`, `cli.sh`, `requirements-linux.txt` i `DEPS.md`
  z komendami per dystrybucja (apt/dnf/pacman/zypper + Steam Deck).
  Buduje `build_linux.ps1` — skrypty trafiają do archiwum z LF i trybem 0755.

### Zmienione
- `symlink_status()` na Linuksie nie straszy już trybem dewelopera — symlinki
  są tam zwykłą operacją użytkownika; komunikat wskazuje realną przyczynę
  odmowy (system plików bez symlinków, katalog tylko do odczytu).
- `_find_7z()` zna `7zz` i `7za` (7-Zip i p7zip na Linuksie).
- Etykiety GUI i pomoc CLI mówią `.desktop` zamiast `.lnk` tam, gdzie to
  właściwe dla systemu.

## [0.3.2] — 2026-08-30

### Naprawione — sprzątanie ToSort po konwersji na CHD
- Po zrobieniu gry na CHD jej źródło w ToSort jest sprzątane porządnie:
  **wspólne tory** (np. filler GD-ROM „Track 2" identyczny w setkach gier,
  chroniony przez nieposiadane gry z DAT) nie zostają już w dziesiątkach kopii —
  **redukcja do JEDNEJ kopii** w całym przebiegu (`kept_shared`); nadmiarowe
  kasowane. **Puste podkatalogi** ToSort po skasowanych torach są usuwane.
  (`convert._purge_redundant_tosort_tracks`; test
  `test_purge_shared_track_reduced_to_single_copy`.)

### Utrzymanie (jednorazowo, na danych użytkownika)
- Usunięto zalegające resztki źródeł z `to sort` gier będących już CHD
  (Dreamcast — 11 podkatalogów; naomi2 — 3 zipy + zbłąkany tor).
- Wyczyszczono indeks z **5763** martwych wpisów (pliki nieistniejące na
  dostępnych dyskach) + **1055** osieroconych rekordów członków archiwów.

## [0.3.1] — 2026-08-21

### Zmienione
- **Zmiana nazwy: CHD Buddy → ROM Helper** (branding). Tytuł okna to teraz
  „ROM Helper"; repozytorium przemianowane na `RomHelper`. Pakiet i CLI pozostają
  bez zmian (`chd_buddy` / `chd-buddy`) — zero zmian w importach/skryptach.
- **Ikona aplikacji** — własna `.ico` (`assets/icon.ico`, kartridż + zębatka)
  wpięta w build (`chd_buddy.spec`); `.exe` nazywa się teraz `ROM Helper.exe`.

### Dokumentacja
- README: sekcja **„Wymagane narzędzia zewnętrzne"** (chdman/MAME wymagane,
  7-Zip opcjonalnie, DolphinTool dla RVZ).

## [0.3.0] — 2026-08-09

### Dodane — Tłumaczenia (V1, gry jednoplikowe)
- **Rola DAT‑u `translations`** (obok collection parent/child) w `dirrules` — DAT
  oznaczony jako pula fanowskich tłumaczeń, nie cel podstawowy. Wybór w:
  ustawieniach pojedynczego DAT‑a, ustawieniach **całego katalogu** (kaskada na
  wszystkie DAT‑y w środku) oraz w zbiorczej edycji zaznaczonych DAT‑ów.
- **Indeks wariantów tłumaczeń** (`core/translations.py`): parsowanie języka z
  nazwy (`[T-En]`, `[T-Fr]`, `(En,Fr,De)`, `[T+Eng]`, `(T-Eng)`) + etykiety;
  mapa `tytuł_bazowy → [warianty]` z DAT‑ów o roli `translations`.
- **Poprawione wykrywanie języka:**
  - język **dziedziczony z nazwy DAT‑u**, gdy gry mają czyste nazwy (kolekcje
    „… [T-En] Collection" — wcześniej filtr języka był pusty);
  - **wnioskowanie z regionu** jako fallback: (Japan)→ja, (USA)/(Europe)→en,
    (Korea)→ko, (Hong Kong)→zh itd.; jawne „(En)"/„English"/`[T-Fr]` ma
    pierwszeństwo nad regionem;
  - dla wariantu tłumaczenia priorytet: jawny tag gry → język z nazwy DAT‑u →
    region gry (więc „Cool Game (Japan)" w „[T-En] Collection" = en, nie ja);
  - parser odrzuca nie‑języki (grupy/wersje) — koniec śmieciowych kodów; listy
    `(En,Fr,De)` akceptowane tylko gdy WSZYSTKIE tokeny to znane języki
    (np. „De Blob" nie daje już fałszywego „de").
- **Trwały wybór podmian** (`translations.json` w katalogu kolekcji): gra →
  tożsamość wybranego wariantu po SHA‑1. Jest ŹRÓDŁEM PRAWDY dla matchera.
- **Matcher honoruje podmiany**: gra z zapisaną podmianą jest SPEŁNIONA przez
  wybrane tłumaczenie (nie „zła treść"/MISSING) — skan nie cofa wyboru.
- **Przepływ podmiany** (rebuilder): oryginał kolekcji → `to sort\translated\
  <system>\` (zachowanie do odtworzenia i walidacji setu), potem symlink pod
  NAZWĄ KANONICZNĄ gry → plik wybranego tłumaczenia. Bez dwóch plików o tej
  samej nazwie w katalogu.
- **GUI**: filtr języka w liście gier; menu gry „Podmień na tłumaczenie…"
  (dropdown wariantów, filtrowalny językiem) oraz „Podmień plik ręcznie…";
  znacznik 🌐 przy podmienionym/dostępnym tłumaczeniu.

### Uproszczenie
- **Jeden launcher GUI.** `chd_buddy.suite` i `chd_buddy.main` uruchamiały to
  samo okno (ROM Kombajn / `SuiteWindow`), ale `suite` pomijał auto‑UAC
  (symlinki!) i część inicjalizacji. `suite` deleguje teraz do `main` — jedna
  ścieżka startu. `main_window` („CHD Buddy") to NIE osobna aplikacja, tylko
  klasyczne narzędzie CHD wbudowane w kombajn (menu Narzędzia).
- Numer wersji w tytule okna (łatwo sprawdzić, że działa nowy build).

### Zasada
Nazwa na dysku pozostaje kanoniczna (set waliduje się wg podstawowego DAT‑u),
a tłumaczenie jest widoczne w GUI. Oryginały nigdy nie kasowane — przenoszone do
`to sort\translated` do odtworzenia.

## [0.2.0]
- Wersja bazowa przed changelogiem: skanowanie z trwałym indeksem, multi‑DAT,
  dedup (parent fizyczny / child linki), konwersja CHD/RVZ/ZIP, ToSort,
  aktualizacja gry do nowszej wersji, świadomość MAME, strażnik treści CHD
  (deep_identify == game_profile), składanie płyt z rozproszonych torów +
  synteza cue.
