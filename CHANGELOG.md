# Changelog — ROM Kombajn (chd_buddy)

Format: [semver](https://semver.org). Najnowsze na górze.

## [0.7.10] — 2026-10-05

### Konfiguracja usera (nie kod): reguła BIOS
- `BIOS\\System.dat` (libretro) to JEDNA „gra" „System" z 396 plikami BIOS
  wszystkich systemów (91 w podfolderach, np. `bk/…`); w kolekcji 279, brak
  117 → przy „tylko kompletne" cała gra pomijana, `Z:\\ROMS\\BIOS\\System`
  pusty; `format: zip` dałby jeden `System.zip`, którego rdzenie libretro nie
  czytają. Za zgodą usera reguła `BIOS` w `DatRoot\\_reguly.json`:
  `format: keep`, `only_complete: false`, `subdir_per_game: false` (kopia
  `_reguly.json.bak-2026-10-05`, zapis atomowy).

### Naprawa ma być kompletna: „Znajdź naprawy" tuż po naprawie = nic do zrobienia
- DZIAŁANIE: naprawa 05.10 12:49–17:26 (0.7.09, bez błędów), zaraz potem
  „Znajdź naprawy" (user: „nie powinno znaleźć jakichkolwiek napraw"):
  12 × REPACK ZIP (fbneo: 720g, apb… — przeniesione w tej naprawie), 1 ×
  KASUJ zbędną kopię (sierota) `No-intro\\FinalBurn Neo - Arcade Games\\
  redearth.zip`, 2 × „KASUJ z ToSort (już na miejscu)" pustych zipów
  Splinter Cell (Disc 2), 1 × „KASUJ z ToSort (zawartość już w kolekcji)"
  `nieznane\\ports\\anarch.zip`.
- ANALIZA — trzy błędy ogólne:
  1. PUSTA treść traktowana jak tożsamość: każdy plik 0 B ma te same sumy;
     dedup uznał puste zipy Splinter Cell za kopie pustego znacznika
     TeknoParrot „Missing in Action" (utworzonego w tej naprawie);
     `_purge_redundant_tosort_archives` pomija puste członki, więc zip z
     SAMYMI pustymi (`anarch.libretro` 0 B) był „zawartością w kolekcji"
     bez żadnego sprawdzenia. Matcher ma tę zasadę od dawna
     (`_is_empty_rom`), reszta programu — nie.
  2. Archiwum PRZENIESIONE na miejsce (etap 1) nie dostaje formatu katalogu:
     przepakowanie TorrentZip w etapie 2 decyduje ze statusów sprzed
     naprawy (status „gdzie indziej" nie ma flagi złego zipa) → kolejna
     naprawa.
  3. Sierota chroniona tylko dlatego, że matcher wybrał ją jako źródło
     (alfabetycznie pierwsza z równych archiwów), choć gra dostała hardlink
     do kopii w DAT-cie wyżej — `sweep_orphans` pomija każde „źródło".
- MIEJSCA: `core/content.py` (`content_sets`), `rebuilder`:
  `_content_placed_outside`, dedup w `_finalize_global`,
  `_purge_redundant_tosort_archives`, `_place_archive` (+`_pending_tz`,
  `run`), `sweep_orphans`.
- ZMIANA:
  1. Treść pusta (rozmiar 0 / sumy pustego pliku) nie jest „tą samą treścią"
     ani „treścią w kolekcji"; archiwum bez niepustych członków nie jest
     zbędne.
  2. Zip położony przez naprawę (przeniesienie/kopia) w katalogu z metodą
     deflate, nie-TorrentZip → przepakowanie w TEJ naprawie (etap 2 tego
     katalogu; widoczne w podglądzie).
  3. Plik w sierocie, którego treść leży na swoim miejscu w kolekcji →
     KASUJ zbędną kopię także wtedy, gdy był wybrany jako źródło.
- WPŁYW: druga naprawa po pełnej naprawie — bez tych operacji. Puste pliki
  zostają tam, gdzie są (w ToSort/nieznane), nie są kasowane jako „kopie".
- WERYFIKACJA: testy — pusty plik w ToSort i pusty znacznik w kolekcji: brak
  KASUJ; zip z samymi pustymi członkami: nie „zbędny"; zip nie-TorrentZip
  przeniesiony z ToSort/sieroty → TorrentZip w tej samej naprawie, druga
  naprawa: nic; sierota-źródło z treścią w DAT-cie wyżej → skasowana.

### Log „KASUJ luźny w dziecku" mówi, gdzie jest treść (nie zawsze „gra na CHD")
- DZIAŁANIE: naprawa 05.10 (0.7.09): „KASUJ luźny w dziecku (gra na CHD):
  Z:\\Arcade2\\RetroBat\\roms\\snes\\Batman Returns (USA).sfc" — user: „jak
  może być sfc w chd? SNES nie ma gier na płytach".
- ANALIZA: decyzja poprawna (0.7.07: gra = zip z ROMS\\snes, hardlink
  utworzony w etapie 1 o 12:52, luźny `.sfc` skasowany w etapie 2 o 13:48 —
  treść jest w zipie). Błędny tylko komunikat: `_purge_child_loose_duplicates`
  powstało dla gier na CHD i od 0.7.07 obsługuje też gry zaspokojone
  archiwum — tekst się nie zmienił.
- MIEJSCA: `convert._purge_child_loose_duplicates` (+`held_in`) i jego 3
  wywołania.
- ZMIANA: log/podgląd: „KASUJ luźny w dziecku (treść jest w <ścieżka zipa
  albo CHD>)".
- WPŁYW: tylko tekst logu; decyzje bez zmian.
- WERYFIKACJA: test naprawy RetroBat-snes: brak „na CHD", jest ścieżka zipa.

## [0.7.09] — 2026-10-05

### Audyt: tożsamość plików i gier wyłącznie po sumach (nie po nazwach)
- DZIAŁANIE: user 05.10: „pliki od początku miały być sprawdzane po sumach,
  a nie po nazwie; poprawki dla pojedynczych instancji zamiast całej metody
  zostawiają śmieci — wyszukaj tego typu błędy i je napraw".
- ANALIZA (przegląd `matcher`, `rebuilder`, `convert`, `chdrebuild`,
  `hierarchy`, `fileindex`, `linker`): zasada — CZYM jest plik/gra
  rozstrzygają SUMY (matcher, indeks); nazwa z DAT-u wyznacza tylko MIEJSCE
  (ścieżka kanoniczna, nazwy członków). Odstępstwa:
  1. `convert._game_physical_files` (konwersja w miejscu): pliki gry =
     pliki o NAZWACH z DAT-u, a dla gry wieloplikowej — WSZYSTKO z
     podfolderu `<gra>\\`; treść niesprawdzona → spakowane `halflife\\valve`,
     możliwy zip z plikiem o złej treści pod dobrą nazwą.
  2. `chdrebuild.rebuild_bad_chds`: CHD gry w katalogu docelowym =
     `<gra>.chd` PO NAZWIE (gałąź ToSort tej samej funkcji — po treści,
     `identified_chds_under`): CHD o innej treści pod nazwą gry szedłby do
     odbudowy wg cue tej gry.
  3. `matcher._match_game_archive` `_other_game` (0.7.04): „zip nazwany jak
     INNA gra tego DAT-u = plik tamtej gry" — po nazwie.
  4. `convert._identical_above` (0.7.07): hardlink do tej samej treści
     wyżej, ale PO zbudowaniu zipa — łatka na skutek; przyczynę usuwa matcher
     (0.7.07: archiwum gry wyżej przed konwersją).
  Pozostałe użycia nazw = miejsce/wyświetlanie (kanoniczna ścieżka, nazwy
  członków jak w DAT-cie, wielkość liter, tłumaczenia — świadomie po nazwie),
  albo klasyfikacja typu pliku po rozszerzeniu (płyta/kartridż/nie-gra).
- MIEJSCA: `convert._game_physical_files`/`convert_reports`,
  `chdrebuild.rebuild_bad_chds`, `matcher._match_game_archive`,
  `convert._convert_one` (usunięte `_identical_above`).
- ZMIANA:
  1. Pliki gry do konwersji = dla KAŻDEGO niepustego ROM-u plik w miejscu
     kanonicznym, którego SUMY z indeksu = ROM z DAT-u (`_row_full_match`);
     brak/inna treść któregokolwiek → gra nie jest konwertowana; nic spoza
     ROM-ów gry (podfolder).
  2. CHD do sprawdzenia kontenera w katalogu docelowym = CHD o odcisku
     treści gry (`data_sha1` = profil), jak w gałęzi ToSort — niezależnie od
     nazwy (nazwę poprawia NAZWA rebuildera).
  3. Archiwum „innej gry" = archiwum, którego członkowie (sumy) to KOMPLET
     tamtej gry — nie sama nazwa pliku.
  4. `_identical_above` usunięte.
  5. Jedno miejsce porównania treści: nowe `core/content.py`
     (`content_sets`/`has_item`/`holds_roms` — SHA-1, bez niego
     CRC32+rozmiar, plik + członkowie archiwum); używają go
     `matcher._archive_holds_game`, `rebuilder._occupant_is_other` (gałąź
     indeksu), `rebuilder._same_game_copy` (dotąd trzy osobne odmiany tego
     samego porównania).
- WPŁYW: konwersja w miejscu pakuje wyłącznie zweryfikowane ROM-y gry;
  odbudowa CHD widzi CHD gry pod dowolną nazwą i pomija obce pod nazwą gry;
  arcade: zip nazwany jak inna gra, ale z inną treścią, jest „złą nazwą".
- WERYFIKACJA: testy (każdy pada na 0.7.08): plik pod nazwą ROM-u z INNĄ
  treścią nie trafia do zipa; podfolder gry z plikiem spoza DAT-u — zip
  tylko z ROM-ami; CHD gry pod inną nazwą — w odbudowie; CHD obcy pod nazwą
  gry — pominięty; zip nazwany jak inna gra z treścią tej gry → NAZWA;
  obcy CHD pod nazwą gry: treść innej gry → NAZWA na nią, treść nieznana →
  ToSort (user 05.10).
  A/B podglądu 0.7.08 → 0.7.09 (ta sama kopia indeksu): +28 PRZENIEŚ w
  `ROMS\\fbneo` — zipy z treścią INNEGO zestawu pod złą nazwą (np.
  `720g.zip` = 7 ROM-ów zestawu 720gr1, bez 3 ROM-ów 720g; `apb.zip` = 2
  pliki zestawu apbf) dostają właściwe nazwy, a prawdziwe zestawy (z
  `No-intro\\FinalBurn Neo - Arcade Games`, dotąd sieroty) trafiają na swoje
  miejsca — każdy przeniesiony zip ma KOMPLET gry, której nazwę dostaje
  (sprawdzone po sumach: 28/28). Regresja z 0.7.04 „720g→720gr1" była w
  rzeczywistości złą treścią pod nazwą — reguła po nazwie ją ukrywała.
  `alienaru.zip`/`indytemp2.zip` (nazwy spoza DAT-u, treść w kolekcji) →
  ToSort. Reszta identyczna; czas 750 → 683 s.

## [0.7.08] — 2026-10-05

### Płyta w ToSort (CHD/RVZ) rozpoznawana po treści, nie po sumie pliku
- DZIAŁANIE: podgląd 05.10 11:37 (0.7.07): „NIEZNANE w ToSort → nieznane:
  `ToSort\\3do\\Mad Dog II - The Lost Gold (USA) (Arcade CD-ROM).chd`" — ta
  sama płyta (odcisk treści `data_sha1`) leży w
  `ROMS\\REDUMP\\Panasonic - 3DO …\\Mad Dog II … .chd`.
- ANALIZA: tożsamość płyty CHD/RVZ = odcisk TREŚCI (`data_sha1`, z sondy);
  suma PLIKU zależy od kompresji/wersji CHD — dwa CHD tej samej gry mają
  różne SHA-1 pliku. Sprzątanie ToSort (`_purge_redundant_tosort_archives`:
  „zawartość już w kolekcji") i „nieznane" (`sort_tosort_unknown`,
  `_wholly_unknown`, 0.7.05: znane DAT-om po CRC+rozmiar) patrzyły tylko na
  sumę pliku → kopia płyty z kolekcji szła do `nieznane` zamiast być
  skasowana; płyta zidentyfikowana jako gra DAT-u, ale nieobecna w kolekcji —
  też do `nieznane`. Płyty z NIEUDANĄ identyfikacją (`deep_fail`: Mega Man X3
  (Europe), Pro Racer (Europe) — treść spoza DAT-ów) → `nieznane` słusznie.
- MIEJSCA: `rebuilder`: `_purge_redundant_tosort_archives` (luźny plik),
  `sort_tosort_unknown`, `_wholly_unknown`; nowe `_dat_profile_known`
  (odciski gier płytowych wszystkich DAT-ów, budowane raz, jak `_dat_known`).
- ZMIANA: plik z `data_sha1`: treść w kolekcji = plik w katalogu DAT-u o tym
  samym odcisku (`find_sha1(…, include_chd_content=True)`) → zbędna kopia
  (KASUJ); odcisk = odcisk gry któregoś DAT-u → znana DAT-om (zostaje w
  ToSort); inaczej jak dotąd.
- WPŁYW: reguła ogólna (kopia płyty z kolekcji o innej kompresji → KASUJ;
  płyta gry DAT-u spoza kolekcji → zostaje w ToSort). U usera BEZ zmian w
  planie (A/B podglądu 0.7.07 → 0.7.08: 27 796 identycznych linii): Mad Dog
  II „(Arcade CD-ROM)" nie jest w żadnym DAT-cie (jest tylko „Mad Dog II -
  The Lost Gold (USA)"), a kopia w `ROMS\REDUMP\…3DO` sama jest sierotą
  wynoszoną do `nieznane` — obie kopie do `nieznane` słusznie (zasada usera);
  2 CHD z `deep_fail` i 1 RVZ (uszkodzony, 17 MB) też.
- WERYFIKACJA: test — CHD w ToSort z odciskiem jak CHD w katalogu DAT-u
  (inna suma pliku) → KASUJ, nie `nieznane`; CHD z odciskiem gry DAT-u,
  której nie ma w kolekcji → zostaje w ToSort; CHD bez dopasowania → nieznane.

## [0.7.07] — 2026-10-04

### Duży zip (poza RAM) czytany z NAS raz; kolejka przepakowań nie czeka na największy
- DZIAŁANIE: naprawa 0.7.06, 03/04.10: SNESMSU1 (zipy MSU-1 0,3–1,2 GB, 42
  zostało, 17 GB) +10 zipów / 15 min; po przepakowaniu `Demon's Crest
  (MSU1).zip` 20 s do przepięcia hardlinku. Przy `kof2k4se.zip` (41 MB)
  „20 s bez postępu" w `_repack_collect`.
- ANALIZA: zip > `RAM_REPACK_MAX` (256 MB) idzie drogą strumieniową, która
  czytała źródło z NAS DWA razy (przebieg sum SHA-1 członków, potem
  przepakowanie), a wynik bez sum → `_repack_finish` czytał NOWY plik trzeci
  raz (`hash_file`). Kolejka puli przy zapełnieniu czekała na NAJSTARSZE
  zadanie — jeden duży zip wstrzymywał dokładanie, choć 3 wątki stały.
- MIEJSCA: `torrentzip.repack_to_torrentzip` (konsument: `convert.repack_zip`
  — RAM i strumień), `torrentzip._copy_out` (też `write_torrentzip`),
  `convert.repack_zip` (droga strumieniowa deflate), `rebuilder._repack_collect`.
- ZMIANA: SHA-1 członków liczone w tym samym odczycie co kompresja
  (`verify_read`), weryfikacja na lokalnej kopii jak dotąd; sumy pliku liczone
  przy wysyłce z lokalnej kopii → wynik niesie `sums`/`tz`. Kolejka: czekanie
  na PIERWSZE zakończone przepakowanie.
- WPŁYW: te same bajty (RAM = strumień, 15 losowych zipów); duży zip: 1 odczyt
  + 1 zapis zamiast 3 odczytów + 1 zapisu (SNESMSU1: ~34 GB mniej pobierania).
  Uszkodzony odczyt źródła wykrywa CRC członka (zipfile) i weryfikacja wyniku.
- WERYFIKACJA: test — zip „duży" (limit RAM = 0): bajtów przeczytanych ze
  źródła < 1,3× rozmiar, sumy z wyniku = sumy pliku, tz=1, treść członków
  bez zmian.

### Konwersja w miejscu: tylko obrazy gier, hardlink do tej samej treści wyżej, widoczna w podglądzie
- DZIAŁANIE: naprawa 05.10 (katalogi RetroBata, `Arcade1TB`): 72 ×
  „KONWERSJA→ZIP" w `Z:\Arcade2\RetroBat\roms\…`: 45 gier SNES `.sfc`→zip
  (37 = bajt w bajt kopie zipów z ROMS\snes — FIZYCZNE kopie zamiast
  hardlinków), ale też `halflife\extras.pak`, `halflife\valve\*.cfg`,
  `singe\Framework\*`, `ports\anarch.libretro`, łatki `.ips`,
  `model3\__ia_thumb.jpg`, `sonicmania\Settings.ini`. W podglądzie 03.10:
  0 takich linii. User: SNES ma być zipem jako hardlink z wyższych DAT-ów;
  halflife/singe/ports niepotrzebne.
- ANALIZA:
  - `convert_reports` (konwersja w miejscu) pakował KAŻDĄ „grę" DAT-u z
    luźnym plikiem — DAT-y dir2dat opisują każdy plik folderu frontendu, więc
    też porty, konfiguracje, łatki i obrazki.
  - Zip zbudowany z luźnego ROM-u (TorrentZip — powtarzalne bajty) był zawsze
    wysyłany jako nowa kopia, bez sprawdzenia, czy identyczny plik leży już w
    DAT-cie wyżej (gałąź konwersji ze źródła to robi — LINK(dziecko)).
  - Konwersja w miejscu idzie jako `after_place` rebuildera, który w
    podglądzie jej NIE woła (`not self.dry_run`), a `repair` nie podawał jej
    `dry_run` — podgląd ≠ wykonanie.
  - Źródło problemu (user: „masz sumy w DAT-ach — porównaj i linkuj"):
    `matcher._match_game_roms` przy luźnym pliku już pod nazwą z DAT-u
    zwracał „jest" OD RAZU, przed szukaniem archiwów — gra w formacie zip,
    której ROM (po sumach) jest w zipie DAT-u wyżej, nie dostawała linku do
    tego zipa, tylko pakowanie w miejscu (a hardlink co najwyżej później, z
    deduplikacji w finale — przerwanej w naprawie 05.10).
- MIEJSCA: `frontend` (nowe `NOT_ROM_EXTS`/`is_not_rom_file`),
  `convert.convert_reports` (filtr; podgląd bez NAS; `hierarchy`),
  `convert._convert_one` (nowe `_identical_above`: hardlink zamiast wysyłki,
  wpis indeksu `record_hardlink`), `rebuilder.run` (`after_place` także w
  podglądzie), `repair` (`dry_run` i `hierarchy` dla `convert_reports`).
- ZMIANA: format zip/7z i komplet luźnych plików gry na miejscu → najpierw
  archiwum tej gry gdzie indziej (sumy, nazwy członków jak w DAT-cie, bez
  nadmiaru) — jest → gra = to archiwum (link wg hierarchii / przeniesienie),
  luźne pliki zbędne; brak → konwersja w miejscu jak dotąd (`matcher`).
  Gra zaspokojona całym archiwum (link) nie trafia do konwersji w miejscu
  (także w podglądzie). Obraz płyty (iso/cue/gdi/chd/rvz/cso/wbfs…, nowe
  `frontend.DISC_IMAGE_EXTS`) NIGDY nie jest pakowany do zipa (user 05.10:
  kartridż → zip, płyta → CHD, bez obsługi CHD → bez zmian). Format „auto"
  dla systemu NIEZNANEGO z plikami płytowymi (np. „triforce") = „keep"
  (dotąd zip) — `dirrules.resolve_format`; wykryte w A/B:
  `triforce\\Mario Kart Arcade GP.iso` → zip, `windows\\…bat.keys` → zip.
  Zmiana „auto" dotyczy u usera 11 DAT-ów (zip → keep): TeknoParrot,
  TOSEC Amiga CD32 ISO, [T-En] PC-9801, MD+/MSU-MD/Mode 1 CD (5),
  Arcade1TB fpinball/switch/triforce — w planie naprawy jedyny skutek:
  pusty plik-znacznik TeknoParrot „Missing in Action".
  Plik stanu (`collection_state.pkl`) — wersja 2: pierwszy start po
  aktualizacji wczytuje DAT-y (z lokalnego cache) i liczy formaty od nowa.
- A/B podglądu całej kolekcji (0.7.05 → 0.7.07, ta sama kopia indeksu):
  +38 LINK (37 gier SNES RetroBata → ROMS\\snes, redearth → fbneo), +26
  KONWERSJA→ZIP (gry bez odpowiednika wyżej: SNES 8, Naomi 9, NES 5, MD 3,
  MSU 1 — dotąd ukryte w podglądzie), +60 KASUJ zbędnych luźnych kopii
  (redearth), reszta identyczna; czas 1046 → 744 s.
  Gra z plikiem spoza obrazów gier (media, opisy, konfiguracje,
  łatki, porty/silniki) — bez zmiany formatu. Gotowy zip = te same bajty
  (SHA-1+rozmiar) co fizyczny plik, do którego hierarchia pozwala linkować →
  hardlink. Konwersja w miejscu widoczna w podglądzie („KONWERSJA→…").
- WPŁYW: RetroBat: ROM-y dalej pakowane (format „auto" katalogu), kopie gier
  z wyższych DAT-ów jako hardlinki; pliki portów/konfiguracji/łatek/mediów
  nietknięte. Podgląd pokazuje konwersje w miejscu dla wszystkich DAT-ów.
- WERYFIKACJA: testy — `.pak`/`.ips`/`.ini` obok `.sfc`: zip tylko z `.sfc`;
  zip = bajty zipa wyżej → hardlink; podgląd: „KONWERSJA→ZIP" bez zmian na
  dysku; rebuilder woła `after_place` w podglądzie.
- NAPRAWA DANYCH 05.10: 67 plików przywróconych z zipów pod oryginalne nazwy
  (CRC sprawdzone), zipy przeniesione do
  `Z:\RomVault\_przywrocone_zipy_2026-10-05`, indeks zaktualizowany;
  halflife/singe/ports — do skasowania przez usera. Kolejna naprawa spakuje
  ROM-y ponownie, tym razem z hardlinkami.

### Plik „tylko do odczytu" w kolekcji: atrybut zdejmowany przy podmianie/kasowaniu
- DZIAŁANIE: naprawa 05.10: 4 × „BŁĄD repack … [WinError 5] Odmowa dostępu"
  (`Z:\Arcade2\RetroBat\roms\nes\Super Mario Bros. (World).zip`, SMB 2 i 3,
  TMNT). User: „A, zdejmuj atrybut i przepakuj".
- ANALIZA: pliki mają atrybut ReadOnly (z 2023 r.); Windows nie pozwala
  nadpisać (`os.replace` tmp → plik) ani skasować takiego pliku. Przepakowanie
  zostawiło oryginał nietknięty, plik tymczasowy sprzątnięty. Ta sama blokada
  dotyczy każdej podmiany w miejscu (przepakowanie, przepięcie hardlinku,
  odbudowa CHD, zmiana nazwy na istniejący plik) i każdego kasowania.
- MIEJSCA: nowe `fileops.replace_rw` / `fileops.unlink_rw`; wszystkie
  `os.replace`/`os.unlink` na plikach kolekcji i ToSort: `convert`,
  `rebuilder`, `chdrebuild`, `fixer`, `linker`, `fileindex.unlink_tracked`,
  `update_game`, `translations`, `prune`, `bios`, `fileops.move_with_progress`.
  Pliki programu (ustawienia, cache, snapshot, ramdisk, skróty) bez zmian.
- ZMIANA: operacja odrzucona z PermissionError, a cel ma atrybut tylko do
  odczytu → atrybut zdejmowany i operacja ponawiana RAZ; inaczej błąd jak
  dotąd. Atrybut nie jest przywracany (plik i tak jest zastępowany/kasowany).
- WPŁYW: pliki ReadOnly w katalogach DAT-ów i ToSort są naprawiane jak
  pozostałe; bez atrybutu — zachowanie bez zmian (jedna próba, jak dotąd).
- WERYFIKACJA: test — przepakowanie zipa ReadOnly: TorrentZip, bez błędu;
  skasowanie pliku ReadOnly przez `unlink_tracked`; przepięcie hardlinku na
  pliku ReadOnly.

### „nie skasowano źródła … [WinError 3]" przy dzieciach — plik już skasowany to nie błąd
- DZIAŁANIE: naprawa 0.7.06, 04/05.10: 692 linie „nie skasowano źródła
  Z:\RomVault\ToSort\psp\…\…iso: [WinError 3] System nie może odnaleźć
  określonej ścieżki" (REDUMP PSP 534, PSN 132+2, 1G1R PSP 11, Saturn 24 —
  Sonic R (USA, Brazil)).
- ANALIZA: gra skonwertowana w katalogu RODZICA (ROMS\psp) kasuje swoje
  źródła w ToSort od razu. Dzieci (REDUMP, 1G1R) mają statusy z dopasowania na
  starcie naprawy — wskazują te same pliki ToSort; po LINK(dziecko) do CHD
  rodzica `_defer_or_purge_game_sources` próbuje skasować je drugi raz, a pliku
  (i katalogu gry) już nie ma → WinError 3/2. Link powstaje poprawnie, nic nie
  ginie — to tylko fałszywy błąd w logu. Ten sam wzorzec (kasowanie pliku,
  który mógł zniknąć wcześniej w tym przebiegu) w innych miejscach kasowania.
- MIEJSCA: `convert`: `_defer_or_purge_game_sources`,
  `_purge_redundant_tosort_tracks` (luźne + archiwa),
  `_purge_child_loose_duplicates`, kasowanie redundantnego archiwum gry na
  CHD, `purge_source_files`; `rebuilder`: kasowanie zbędnych kopii w ToSort
  (dwa miejsca) i starego archiwum po przepakowaniu; `update_game`.
- ZMIANA: wspólne `fileindex.unlink_tracked(path, index)`: brak pliku
  (FileNotFoundError, WinError 2/3) = już skasowany → tylko wpis indeksu
  usuwany, bez logu „nie skasowano" i bez liczenia jako skasowany teraz.
  Inne błędy jak dotąd.
- WPŁYW: log bez fałszywych błędów; liczniki skasowanych = realnie
  skasowane. Pliki i linki bez zmian.
- WERYFIKACJA: test — rodzic kasuje źródło, dziecko po linku do rodzica: brak
  „nie skasowano" w logu, wpis indeksu źródła usunięty.

### Pasek konwersji: ile gier do konwersji, a nie numer gry w DAT-ach katalogu
- DZIAŁANIE: user 04.10 (zrzut): „konwersja (ze źródła): Crush (USA)
  (650/3545)" — „ponad 3000 gier PSP do zrobienia, a nie powinno być tyle".
- ANALIZA: `convert_from_source` liczył postęp jako pozycję w pętli po
  WSZYSTKICH grach DAT-ów katalogu (3545), z których większość jest tylko
  sprawdzana i pomijana; realnych konwersji w podglądzie: 534 (ToSort\psp).
  Pasek był szybki na pominięciach, a po nim nie dało się ocenić, ile zostało.
- MIEJSCA: `convert.convert_from_source` (etykieta i wartości `on_progress`;
  konsument: pasek etapu w oknie i StallWatch — tylko wyświetlanie).
- ZMIANA: przed pętlą liczba gier-kandydatów do konwersji — te same warunki
  ze statusów, które w pętli prowadzą do konwersji (komplet poza opisem płyty,
  źródło luźne / w archiwum, nie CHD/całe archiwum, nie już w formacie, nie
  wszystko „jest" poza luźną płytą na CHD). Pasek: „konwersja X/Y: gra ·
  sprawdzono G/N"; wartość paska = X/Y.
- WPŁYW: tylko wyświetlanie; decyzje konwersji bez zmian. Y to górna granica:
  gra pominięta po sprawdzeniu indeksu (już na zweryfikowanym CHD po
  wznowieniu) jest w Y, ale X do niej nie dochodzi; dziecko dostające tylko
  hardlink do CHD rodzica liczy się jak konwersja (szybka).
- WERYFIKACJA: test — dwie gry do konwersji w DAT-cie z wieloma grami bez
  źródła: ostatni postęp „konwersja 2/2", N = liczba gier DAT-u.

## [0.7.06] — 2026-10-03

### Przepakowanie do TorrentZip: jeden odczyt i jeden zapis na NAS, kilka zipów naraz
- DZIAŁANIE: naprawa 03.10 13:15: po 8,5 h przepakowane 7175 z 27 566 zipów
  (4,25 s/zip, średnio 0,4 MB → 0,1 MB/s); prognoza: jeszcze ~24 h.
- ANALIZA: py-spy na działającej naprawie (5 min): 100% wątku naprawy w
  `_repack_bad_zip`, z tego ~5% kompresja (CPU), ~95% czekanie na operacje
  plikowe na NAS (jedna ≈ 0,3–0,5 s przez Tailscale). Na jeden zip ~15 takich
  operacji: zip otwierany 5× (metoda, status TZ, sumy członków, źródło
  przepakowania, weryfikacja nowego) + ponowny odczyt całego nowego pliku dla
  sum indeksu (`hash_file`) i statusu TZ; zapis TorrentZipa z `seek` po
  każdym członku (każdy = osobna runda SMB); `mkstemp` + ponowne otwarcie;
  `same_file` = 2× stat na kandydata; przepięcie hardlinku = lexists + link +
  replace. Wszystko szeregowo.
- MIEJSCA: `torrentzip.write_torrentzip` (wszyscy wołający: przepakowanie,
  pakowanie z wypakowania, BIOS-y, `convert`), `torrentzip_status`,
  `convert.repack_zip` (+ `ConvertResult.sums/tz`), `rebuilder._repack_bad_zip`
  i `_normalize_target_zip_compression` (ponowny `hash_file` po
  przepakowaniu), `linker.replace_with_hardlink`, `fileindex.record_file`.
- ZMIANA:
  - TorrentZip powstaje w pamięci (duże: lokalny plik tymczasowy), na NAS
    trafia jednym ciągłym zapisem — dotyczy KAŻDEGO zapisu TorrentZipa.
  - `repack_zip` (deflate): zip ≤ 256 MB wczytany RAZ; metoda, status TZ,
    sumy członków, przepakowanie, weryfikacja i sumy nowego pliku liczone w
    pamięci; wynik niesie sumy → wołający nie czyta pliku ponownie. Większe
    — dotychczasową drogą strumieniową.
  - Naprawa: przepakowania w miejscu idą w puli 4 wątków (tylko system
    plików: odczyt, zapis, podmiana, przepięcie hardlinków); indeks, licznik
    i log — wątek właściciela, jak przy linkach równoległych (0.6.97).
    Kolejność względem reszty naprawy zachowana: operacja na zipie w trakcie
    przepakowania (link do niego, użycie jako źródła) czeka na jego koniec;
    pula domykana na końcu każdego DAT-u i przy przerwaniu.
- WPŁYW: wynik na dysku i w indeksie bez zmian (te same bajty TorrentZipa,
  ta sama weryfikacja SHA-1 członków przed podmianą, podmiana atomowa,
  hardlinki przepinane). Pamięć: do ~4 zipów naraz w RAM (≤ 256 MB każdy;
  większe przetwarzane pojedynczo). Kolejność wierszy w logu przepakowań może
  się różnić (równoległość). Podgląd bez zmian.
- WERYFIKACJA: testy — bajty TorrentZipa z pamięci = jak dotąd; przepakowanie
  w RAM: te same bajty, sumy z wyniku = sumy pliku, zip uszkodzony → błąd i
  plik nietknięty; naprawa z pulą: hardlinki przepięte, indeks z sumami
  nowego pliku i tz=1, link do zipa w trakcie przepakowania wskazuje NOWY
  plik. Bajty TorrentZipa 0.7.05 = 0.7.06 (25 losowych zipów: przepakowanie
  i zapis). Pomiar na NAS usera (12 zipów fbneo ~0,5 MB, kopie w
  `Z:\_rh_perftest`): 0.7.05 3,24 s/zip; 0.7.06 jeden wątek 1,62 s/zip,
  4 wątki 0,62 s/zip (8 wątków 0,58 — zostaje 4). Podgląd całej kolekcji
  0.7.05 vs 0.7.06 na kopii indeksu: 56 536 identycznych linii; czas
  1012 → 768 s.

### Dopasowanie: współdzielony plik w setkach gier, gry z tysiącami plików
- DZIAŁANIE: podgląd 03.10: „dopasowanie" DSi (CDN) 15 s ×2, TeknoParrot
  18 s; sonda CHD: „20 s bez postępu — all_under".
- ANALIZA (cProfile na kopii indeksu):
  - DSi: `titlePass.txt` (8 B, ta sama treść w 1678 grach) leży w 5730
    archiwach — `_archives_with_game` przeglądał je dla KAŻDEJ gry: 19 mln
    porównań, choć gra pasuje tylko do archiwum, które ma WSZYSTKIE jej pliki.
  - TeknoParrot: 3,18 mln plików w 852 grach; `DatGame.data_roms` (lista bez
    .cue/.gdi) liczony przez `pathlib` od nowa przy każdym użyciu.
  - `all_under`/`count_under`/`identified_chds_under`/`mark_missing`: warunek
    `substr(path, 1, n) = ?` = przegląd całej tabeli (~55 ms), wołane per
    katalog (sonda CHD: ~430 katalogów; naprawa: per DAT).
  - Po pierwszej poprawce (pomiar): DSi dalej 6 s — `match_rom` filtrował
    WSZYSTKIE 5730 wierszy `titlePass.txt` dla każdej gry, choć bierze
    pierwszy pasujący; TeknoParrot dalej 17 s — każdy z 3,18 mln ROM-ów
    (prawie wszystkie nieobecne) przechodził 5 wyszukiwań z kopiowaniem list,
    a `_archives_with_game` szukał wszystkich ROM-ów gry, choć pierwszy
    nieobecny przesądza, że żadne archiwum nie ma kompletu.
- MIEJSCA: `matcher._archives_with_game` (jedyny konsument:
  `_match_game_archive`, używa wyłącznie archiwów z kompletem niepustych
  ROM-ów), `matcher.match_rom` (trafienie w archiwum: używany tylko pierwszy
  pełny wiersz), `datfile.DatGame.data_roms` (konsumenci: odcisk gry, CHD,
  konwersja, hierarchia), `fileindex` (4 zapytania, nowe `rom_absent`).
- ZMIANA: archiwa kandydaci = zawierające NAJRZADSZY niepusty ROM gry;
  pozostałe ROM-y sprawdzane tylko w nich; ROM nieobecny w żadnym archiwum →
  od razu brak archiwum z kompletem (wynik `full` identyczny). `match_rom`:
  ROM, którego żadnej sumy (SHA-1, MD5, CRC+rozmiar) nie ma w cache
  dopasowania ani wśród plików, ani członków → „brak" bez wyszukiwań;
  trafienie w archiwum = pierwszy pełny wiersz (jak dotąd `[0]`). `data_roms`
  — rozszerzenie z nazwy bez `pathlib` (te same reguły co `Path.suffix` w
  Pythonie 3.14). Zapytania „pod katalogiem" — zakres na indeksie ścieżki
  (`path >= prefiks AND path < prefiks+1`), ta sama semantyka co `substr`.
- WPŁYW: wyniki dopasowania i zapytań bez zmian (kopia indeksu usera:
  statusy TeknoParrot 3 183 707 i DSi 7392 — identyczny odcisk 0.7.05 i
  0.7.06). Czas: DSi (CDN) 15,0 → 1,3 s (każdy z dwóch DAT-ów), TeknoParrot
  21,3 → 13,3 s, `all_under` dla 430 katalogów 21,6 → 0,4 s.
- WERYFIKACJA: testy — gra z plikiem wspólnym dla wielu archiwów: ten sam
  wynik co dotąd, archiwum częściowe pomijane; ROM nieobecny → brak bez
  wyszukiwań, ROM tylko w archiwum → dalej „gdzie indziej"; `data_roms` =
  dawna definicja na nazwach brzegowych; `all_under` = `substr` (w tym
  ścieżki z podobnym prefiksem: `…\psx` vs `…\psx2`). Porównanie podglądu
  przed/po; pomiar czasu dopasowania.

## [0.7.05] — 2026-10-03

### „Nieznane" = treść, której nie zna ŻADEN DAT (po sumach), nie „nie widać jej w kolekcji"
- DZIAŁANIE: podgląd 03.10 12:19 (0.7.04): w „NIEZNANE w ToSort → nieznane"
  tory Saturna/Dreamcasta (`Sonic R (Europe) (Track 02).bin`…), BIOS-y
  (`128p-1.rom`, `pcfxbios.bin`), `fbneo\gforce2ja.zip` (46/46 plików znanych
  FBNeo), PSP Minis.
- ANALIZA (indeks + cache DAT-ów usera): z 5760 „nieznanych" 387 ma treść
  znaną DAT-om; wszystkie 366 „PRZEPAKUJ (tylko nieznane)" też. 0.7.02
  (`_wholly_unknown`, `sort_tosort_unknown`) uznawało za nieznane wszystko,
  czego nie widać jako pliku/członka w katalogach DAT-ów — a tory gier na CHD
  w indeksie nie występują osobno, treść potrzebna do braków też nie. Zasada
  usera: do nieznane trafia treść, „której nie ma gdziekolwiek w DAT".
- MIEJSCA: `rebuilder`: `set_hierarchy` (zapamiętuje wszystkie wpisy DAT-ów),
  nowe `_dat_known` (zbiór CRC+rozmiar ROM-ów WSZYSTKICH DAT-ów, budowany raz,
  zwalniany po finale), `_wholly_unknown` i `sort_tosort_unknown`;
  `convert._purge_redundant_tosort_tracks` (kasowanie archiwów ToSort z torami
  gier już na CHD: archiwum z członkiem NIEZNANYM żadnemu DAT-owi nie jest
  kasowane — trafi do nieznane w finale; dotąd 0 takich u usera, ta sama
  zasada w całym programie) — `repair` podaje `rb._dat_known`.
- ZMIANA: członek/plik „nieznany" = brak w kolekcji I brak w każdym DAT-cie
  (CRC+rozmiar). `sort_tosort_unknown`: całość do nieznane tylko gdy WSZYSTKO
  nieznane; zip mieszany → przepakowanie wyrzuca TYLKO członków leżących w
  katalogach DAT-ów, a gdy zostają członkowie znani DAT-om — archiwum zostaje
  w ToSort (nie w nieznane); znana treść nie w kolekcji → bez zmian.
  `_wholly_unknown` (sieroty / sprzątanie): znane DAT-om → ToSort (nie
  nieznane).
- WPŁYW: podgląd: „NIEZNANE w ToSort → nieznane" ↓ ~387, „PRZEPAKUJ (tylko
  nieznane)" → tylko zipy bez członków znanych DAT-om poza kolekcją. Pamięć:
  ~3 mln kluczy na czas finału.
- WERYFIKACJA: test — tor gry (znany DAT-owi, w kolekcji tylko w CHD) w ToSort
  nie trafia do nieznane; plik nieznany — trafia; zip z członkiem znanym DAT-owi
  i nieznanym — zostaje w ToSort. Porównanie podglądu przed/po.

## [0.7.04] — 2026-10-03

### Nazwa pliku = jak w DAT-cie, co do litery (także wielkość liter); plik rozpoznany po sumach
- DZIAŁANIE: user 03.10: „jak index może o czymś nie wiedzieć? jak może się
  okazać, że miejsce zajęte, skoro był nowy skan?"; „nazwa pliku nie powinna
  być brana pod uwagę, jak mam sumy"; „zmiana nazwy pliku to też naprawa —
  jeśli w DAT jest SEED, plik Seed trzeba zmienić"; „dla wszystkich platform".
- ANALIZA: plik `…Gundam Seed (Japan).zip`, DAT: `…Gundam SEED (Japan)`.
  Windows/NAS nie rozróżniają wielkości liter, program — tak: indeks
  (`lookup`/`members_of`: `path=?`) nie widział pliku pod nazwą z DAT-u
  („nie ma") → podgląd: nowy link; wykonanie: miejsce zajęte → KONFLIKT co
  naprawę. Odwrotnie matcher (`_same_path` = normcase): plik o nazwie różnej
  tylko wielkością liter = „na miejscu" → nazwa NIGDY nie poprawiana (12 plików
  u usera: PS1 4, PS2 3, Saturn 2, GBA 2, WSC 1 — np. „WipEout (USA).chd" →
  „Wipeout (USA)"). Gorzej: zip w katalogu DAT-u z dokładnym zestawem gry był
  „na miejscu" NIEZALEŻNIE od nazwy pliku (`_match_game_archive`, gałąź
  w katalogu) — zip pod złą nazwą zostawał. Do tego `link_of` (Amiga 1000):
  wpis „to hardlink X" zostawał po podmianie X (przepakowanie) — fałszywe
  „już zlinkowane".
- MIEJSCA: `fileindex`: `lookup`/`members_of` (bez rozróżniania wielkości
  liter, indeks `path COLLATE NOCASE`), `rename`/`record_file`/
  `reindex_archive`/`_persist_hashed` (link_of wskazujące na zmieniony plik:
  przeniesione/wyczyszczone); `matcher`: `_pick`, gra CHD, archiwum w
  katalogu (HAVE tylko przy nazwie co do litery = DAT; inaczej „zła nazwa");
  `rebuilder`: nowe `_case_rename` (zmiana samej wielkości liter: przez nazwę
  tymczasową) w ścieżkach: NAZWA, `_place_archive` (to samo miejsce), link do
  rodzica (`_same_game_copy`), konflikt przy wykonaniu (0.7.03).
- ZMIANA: plik rozpoznany po SUMACH, a jego nazwa (pliku; w środku zipa —
  już było) ≠ DAT co do litery → NAZWA na dokładną nazwę z DAT-u; indeks
  znajduje plik niezależnie od wielkości liter (jak system plików). WYJĄTEK
  (wykryty w porównaniu podglądów): zip nazwany jak INNA gra tego DAT-u to plik
  tamtej gry (arcade: zip rodzica `720g.zip` zawiera ROM-y klona `720gr1`) —
  nie jest „złą nazwą" klona; w DAT-ach arcade tylko różnica wielkości liter.
- WPŁYW: podgląd/naprawa: nowe „NAZWA" (12 u usera + zipy pod złymi nazwami
  w katalogach DAT-ów, dotąd „na miejscu"); znika 5 KONFLIKT. Linki/treść bez
  zmian.
- WERYFIKACJA: testy — plik i CHD różniące się wielkością liter → NAZWA,
  podgląd = wykonanie; zip w katalogu DAT-u pod złą nazwą → NAZWA; dziecko
  „Seed" z rodzicem „SEED" → hardlink pod nazwą z DAT-u, bez KONFLIKT;
  `lookup` bez rozróżniania wielkości liter; `link_of` czyszczony po podmianie
  celu.

### Pod nazwą gry leży INNA treść (po sumach) → do ToSort, na miejsce właściwy plik
- DZIAŁANIE: naprawa 03.10 11:16: „KONFLIKT: No-intro\…SNES\Blackthorne (USA)
  (Beta).zip zajęte zwykłym plikiem" — co naprawę.
- ANALIZA: zip w No-intro to STARY zrzut bety (CRC b39af3fa) — aktualny DAT
  No-intro chce cffaaa21 (leży w ROMS). Plik o nazwie gry, ale NIE ta gra.
  Gałąź linku (i układania, i „własnego pliku" 0.6.98) kończy KONFLIKT-em,
  a sprzątanie omija ścieżkę (jest kanoniczna) → stan na zawsze.
- MIEJSCA: `rebuilder`: gałąź linku do rodzica (podgląd: zajęte w indeksie;
  naprawa: `_resolve_link_conflict`), układanie (`_clear_dest` → KONFLIKT),
  „własny plik" (0.6.98) — wspólne `_evict_occupant`.
- ZMIANA: gdy pod ścieżką gry leży plik, którego treść (po sumach; zip:
  CRC+rozmiar członków z dysku przy naprawie) NIE zawiera ROM-ów gry z DAT-u →
  przeniesienie do ToSort (`nieznane`, gdy żaden DAT go nie zna — 0.7.02), a
  potem zwykła operacja (link / ułożenie). Gdy treści nie da się sprawdzić
  (nie-zip przy naprawie) albo plik JEST tą grą → jak dotąd.
- WPŁYW: KONFLIKT → „TOSORT (inna treść pod nazwą z DAT-u)" + LINK; nic nie
  jest kasowane (przeniesienie).
- WERYFIKACJA: test — pod nazwą gry stary zrzut: podgląd i naprawa → stary
  plik w ToSort\nieznane, na miejscu hardlink rodzica, bez KONFLIKT.

## [0.7.03] — 2026-10-03

### Zajęte miejsce linku przy wykonaniu: ta sama treść (z dysku) → hardlink
- DZIAŁANIE: naprawa 03.10 11:15: 5× „KONFLIKT: … zajęte zwykłym plikiem"
  (Gundam SEED WSC/GBA ×3, [BIOS] Amiga 1000 Bootstrap 8k/64k) — te same w
  KAŻDEJ realnej naprawie od 02.10 (22:53, 22:55, 05:58, 11:15), nigdy w
  podglądzie.
- ANALIZA: podgląd rozstrzyga z INDEKSU, a indeks się myli: (1) Gundam —
  plik leży na dysku, indeks go nie zna → podgląd „LINK (tworzę)", wykonanie:
  os.link → FileExistsError → inne bajty → KONFLIKT; (2) Amiga — indeks ma
  `link_of` = plik ROMS (hardlink), na dysku osobny plik (nlink 1; nieaktualny
  wpis) → podgląd „już zlinkowane", wykonanie → KONFLIKT. Rozstrzygnięcie z
  0.7.01 (`_same_game_copy`) działa tylko na indeksie.
- MIEJSCA: `rebuilder._link_finish` (wynik „conflict" z puli linków) — nowe
  `_resolve_link_conflict` (wątek właściciela).
- ZMIANA: przy konflikcie: oba pliki to zipy → spis członków Z DYSKU (central
  directory: CRC + rozmiar, bez dekompresji); KAŻDY niepusty członek pliku w
  miejscu linku jest w pliku docelowym → atomowa podmiana na hardlink
  (`replace_with_hardlink`, „POPRAW LINK (ta sama treść)") + wpis w indeksie;
  inaczej KONFLIKT jak dotąd (nic nie nadpisujemy).
- WPŁYW: tylko realna naprawa, tylko przy konflikcie (rzadkie) — 2 krótkie
  odczyty NAS na konflikt. Podgląd bez zmian.
- WERYFIKACJA: test — plik w miejscu linku nieznany indeksowi / z
  nieaktualnym `link_of`, ta sama treść → hardlink; inna treść → KONFLIKT.

## [0.7.02] — 2026-10-03

### ToSort: treść z katalogów DAT-ów kasowana, nieznana → ToSort\nieznane
- DZIAŁANIE: zasada usera 03.10: „jeśli jakakolwiek treść jest fizycznie
  gdziekolwiek w katalogach DAT, usuwamy wszystkie jej wystąpienia z ToSort;
  treść, której nie ma w żadnym DAT-cie → ToSort\nieznane". Decyzje usera:
  nieznane pliki, które JUŻ leżą w ToSort → też do ToSort\nieznane; archiwum
  mieszane (część znana, część nie) → przepakować, zostawić tylko nieznane.
- ANALIZA: (1) kasowanie z ToSort (`_purge_redundant_tosort_archives` →
  `_content_placed_outside`) liczyło kopię GDZIEKOLWIEK poza ToSort — także w
  katalogu-sierocie (bez DAT-u), który sam idzie do ToSort/kasowania.
  (2) nieznane z katalogów kolekcji szły do `ToSort\<katalog>\…`
  (`sweep_orphans` „NIEZNANY→ToSort", `_clean_dir` „TOSORT"), nie do
  `ToSort\nieznane`. (3) nieznane w ToSort zostawały na miejscu. (4) archiwum
  mieszane zostawało w całości. Uwaga: źródła gier NIEKOMPLETNYCH (pomijane
  przez „tylko kompletne") nie trafiały do `_placed_sources` — nie wolno ich
  uznać za nieznane.
- MIEJSCA: `rebuilder`: `set_hierarchy` (prefiksy katalogów WSZYSTKICH DAT-ów,
  także wyłączonych), `run` (nowy zbiór `_known_sources`: źródło KAŻDEGO
  dopasowanego statusu, także gier pominiętych), `_content_placed_outside`
  (tylko kopie w katalogach DAT-ów), `sweep_orphans` i `_clean_dir` (cel
  nieznanych = `ToSort\nieznane\…`; znane źródła — jak dotąd do ToSort),
  nowe `sort_tosort_unknown` (finał); `repair` (wywołanie w finale, te same
  warunki co sprzątanie sierot: sprzątanie włączone, bez przerwania, wszystkie
  DAT-y wczytane).
- ZMIANA: finał: każdy plik ToSort (poza `nieznane`, biblioteką `cues` i
  plikami przeniesionymi w tym przebiegu), którego NIE używa jako źródła żaden
  DAT: luzem → `ToSort\nieznane\<ścieżka>`; archiwum bez członków znanych z
  katalogów DAT-ów → całe do `nieznane`; archiwum mieszane (zip) → TorrentZip
  tylko z członkami SPOZA katalogów DAT-ów do `nieznane`, oryginał kasowany
  (członkowie znani są potwierdzeni w katalogach DAT-ów); 7z mieszane — bez
  zmian (nie umiemy przepakować 7z). Kolizja nazw w `nieznane` → sufiks `_N`.
- WPŁYW: podgląd/naprawa: „NIEZNANY→ToSort" i „TOSORT" nieznanych wskazują
  `ToSort\nieznane\…`; nowe „NIEZNANE w ToSort → nieznane" i „PRZEPAKUJ
  (tylko nieznane)"; „KASUJ z ToSort (zawartość już w kolekcji)" może SPAŚĆ
  (kopie tylko w sierotach już się nie liczą — sieroty same trafiają do
  nieznane albo są kasowane jako zbędne). Skan ToSort obejmuje `nieznane`
  (podkatalog) — po włączeniu DAT-u znane pliki zostaną z niego ułożone.
- WERYFIKACJA: testy — nieznany plik z sieroty → `ToSort\nieznane`; nieznany
  plik w ToSort → `nieznane`; źródło gry niekompletnej zostaje; plik ToSort,
  którego kopia jest tylko w sierocie, NIE jest kasowany jako „w kolekcji";
  zip mieszany → w `nieznane` tylko nieznani członkowie, oryginał skasowany;
  podgląd przed/po na danych usera.

## [0.7.01] — 2026-10-03

### Ta sama gra pod złymi nazwami w miejscu linku → hardlink (nie KONFLIKT)
- DZIAŁANIE: user 03.10 (podgląd 07:01): „KONFLIKT: No-intro\SNK - NeoGeo
  Pocket Color\[BIOS] … (En,Ja).zip zajęte zwykłym plikiem" — w każdym
  podglądzie od dni; user: „masz DAT, masz sumy, masz zły plik — czemu nie
  zmieniasz nazwy i nie linkujesz? to cały sens programu".
- ANALIZA: oba DAT-y (ROMS i No-intro) chcą `[BIOS] … (En,Ja).bin`. ROMS ma
  poprawny zip; zip w No-intro ma w środku STARĄ nazwę `.ngp` — ten sam ROM
  (SHA-1 edc1319205…), inne bajty zipa. Matcher dobrze: gra po sumach,
  „złe nazwy". Rebuilder: treść ma kopię w DAT-cie wyżej → gałąź LINKU
  (dziecko → rodzic); miejsce zajęte zwykłym plikiem, a test „już
  zlinkowane" porównuje BAJTY (podgląd: `_linked_to`, naprawa: os.link →
  FileExistsError → same_file) → KONFLIKT. Ta sama gra pod złymi nazwami
  nie jest rozpoznawana jako „ta sama treść".
- MIEJSCA: `rebuilder._process`, gałąź linku do rodzica (przed pulą linków
  i przed sprawdzeniem zajętego miejsca); nowy `_same_game_copy` (indeks,
  bez NAS).
- ZMIANA: gdy w miejscu linku leży (wg indeksu) zwykły plik o innych bajtach,
  ale TEJ SAMEJ treści co plik rodzica — archiwum: każdy niepusty członek
  (SHA-1, bez SHA-1: CRC+rozmiar) jest w rodzicu (członek albo cały plik);
  CHD: ten sam `data_sha1` — atomowa podmiana na hardlink rodzica
  (`_link_over_copy`, „POPRAW LINK"). Inna treść → KONFLIKT jak dotąd (nic
  nie nadpisujemy).
- WPŁYW: podgląd/naprawa: takie KONFLIKT → POPRAW LINK (u usera 1). Zwykłe
  linki bez zmian (sprawdzenie tylko z indeksu, bez dodatkowych rund NAS).
- WERYFIKACJA: test — zip rodzica `.bin`, zip dziecka `.ngp` z tym samym ROM-em:
  podgląd POPRAW LINK bez KONFLIKT, naprawa → ten sam plik (hardlink);
  dziecko z INNĄ treścią → KONFLIKT.

## [0.7.00] — 2026-10-03

### Źródło gry: dokładny plik zamiast wypakowania z większego zipa; kopia między DAT-ami = hardlink
- DZIAŁANIE: user 02/03.10: naprawa stała 19 min w etapie 1 na „PRZEPAKUJ
  …DSi (Digital) (CDN) (Decrypted) (Retool)\X.zip -> No-intro\…DSi
  (Digital)\X.zip (wypakuj ROM-y gry z nadzbioru: 1 z 4 plików)" — ~4 s na
  grę (pobranie + wysyłka przez NAS), ~900 gier.
- ANALIZA (indeks usera, „Shapo (USA)"): ta sama gra leży DOKŁADNIE jako
  `1G1R\…DSi (Digital) (Retool)\Shapo (USA).zip` (1 plik `00000000`, ta sama
  suma). (1) matcher (`_match_game_archive`) wybiera archiwum spoza katalogu
  DAT-u po „nazwy w środku OK", potem ALFABETYCZNIE — „(CDN) (Decrypted)"
  wygrywa z „(Retool)", nadzbiór przed dokładnym plikiem. (2) Nawet dokładny
  plik innego DAT-u (który go potrzebuje) był KOPIOWANY (`_copy_keep`:
  pobranie + wysyłka), choć na tym samym udziale hardlink daje to samo
  natychmiast (hardlink = równorzędna kopia, zasada z 0.6.50/0.6.93).
  (3) Przepakowanie z cudzego archiwum (transfer) szło w etapie 1 („szybkie").
- MIEJSCA: `matcher._match_game_archive` (wybór archiwum: w katalogu i poza
  nim); `rebuilder._copy_keep` (3 wywołania: plik/archiwum innego DAT-u,
  który zostaje u właściciela) + gałąź „KOPIA (dedup w kolekcji → fizyczna)"
  w `_process` (treść już w kolekcji, DAT wyżej nie linkuje w dół — dziś
  `_copy_file` przez NAS, teraz ten sam `_copy_keep`); `rebuilder._process` gałąź archiwum
  (przepakowanie z innego miejsca w etapie 1 → etap 2, jak repack zipów).
- ZMIANA: (1) kolejność kandydatów: poprawne nazwy → DOKŁADNY zestaw przed
  nadzbiorem → ścieżka. (2) `_copy_keep`: hardlink, gdy oba końce to dane
  tylko do odczytu (`linkable`), DAT docelowy nie wymusza kopii fizycznych
  (`physical_only`), linki włączone; nieudany `os.link` (inny wolumin) →
  kopia jak dotąd. (3) etap 1: przepakowanie archiwum z INNEGO miejsca
  (nadzbiór / złe nazwy) czeka na etap 2.
- WPŁYW: podgląd/naprawa: „PRZEPAKUJ (wypakuj z nadzbioru)" ↓ tam, gdzie
  dokładna kopia istnieje; „KOPIA (plik innego DAT-u zostaje)" → „LINK
  (hardlink…)" (liczone jako połączone, nie kopie); transfer NAS ↓.
  Przepakowanie z nadzbioru, gdy dokładnej kopii brak — dalej, w etapie 2.
  Zip nie-TorrentZip zlinkowany tak dalej idzie do repacku TZ w etapie 2
  (relink_twins przepina linki). Treść bez zmian (te same sumy).
- WERYFIKACJA: testy — dokładny zip innego katalogu wybrany przed nadzbiorem
  (stara kolejność alfabetyczna wybierała nadzbiór); `_copy_keep` tworzy
  hardlink (ten sam plik), dla `physical_only` kopię; etap 1 nie przepakowuje
  z innego miejsca, etap 2 tak. Podgląd na danych usera: liczby przed/po.

### Koniec operacji bez 24 s pauzy odśmiecacza
- DZIAŁANIE: log podglądu 02.10 22:39: „[24 s bez postępu] trwa:
  long_operation (gcpause.py:48)" — na końcu każdej operacji okno stało
  (pełne GC trzyma GIL: stoją wszystkie wątki, też okno).
- ANALIZA: `gcpause.long_operation` na końcu: `gc.unfreeze()` + pełne
  `gc.collect()` po WSZYSTKICH obiektach (miliony: DAT-y, raporty, stany) —
  24 s. Odmrożone obiekty były potem przeglądane przy każdym kolejnym pełnym GC.
- MIEJSCA: `core/gcpause.py` (`long_operation`).
- ZMIANA: na końcu ostatniej operacji tylko zebranie MŁODYCH pokoleń
  (`gc.collect(1)`, ułamki sekundy) i ponowne zamrożenie (`gc.freeze()`) —
  bez odmrażania i pełnego przeglądu.
- WPŁYW: brak pauzy na końcu operacji i rzadszych pauz później. Koszt: śmieci
  CYKLICZNE sprzed zamrożenia nie są odzyskiwane do końca programu (zwykłe
  obiekty zwalnia licznik referencji jak dotąd).
- WERYFIKACJA: test — po `long_operation` brak pełnego `gc.collect()`,
  obiekty zamrożone.

## [0.6.99] — 2026-10-03

### Start bez liczenia: drzewo z liczbami z zapisanego stanu (model RomVaulta, krok 1/3)
- DZIAŁANIE: user 03.10: „czemu w RomVault wszystko jest szybciej — startuję
  program, mam od razu listę DAT-ów z liczbami"; RomVault: jeden plik cache
  wczytany do RAM, nic nie liczone na starcie, „nic się nie zmieniło, dopóki
  użytkownik sam nie odpali etapu".
- ANALIZA (pomiar na danych usera, 03.10): start robi pełne „Wczytaj DAT-y":
  przegląd całego DatRoot na NAS (z `cues`, 18 593 pliki), `stat` 1214 DAT-ów,
  sidecary JSON z NAS, odczyt `dat_parse_cache` (697 plików, 955 MB, 7 s),
  `report_states` (959 plików, 515 MB, ~990 tys. gier: 12 s z budową
  obiektów), liczby gier (1,5 s), reguły i lista ToSort z NAS, a w wątku okna
  dodatkowo `is_dir` DatRoot na NAS. Drzewo potrzebuje z tego tylko: listy
  DAT-ów (nazwa, ścieżka, katalog, liczba gier), liczb per DAT, reguły skip,
  kolejności katalogów i liczników ToSort.
- MIEJSCA: nowy `core/snapshot.py` (plik stanu kolekcji obok exe: wpisy DAT-ów
  bez gier + skip + ToSort + kolejność katalogów + DAT-y nieudane);
  `core/datcache.py` (indeks liczb `report_states/_counts.pkl` zapisywany
  RAZEM ze stanem DAT-u w `save_report_states`; `load_report_state` jednego
  DAT-u; `LazyStates` — stan DAT-u wczytywany przy pierwszym użyciu);
  `core/datstore.py` (`DatEntry`: `n_games`/`n_roms`/`cache_sig`, `load()` z
  lokalnego cache po zapamiętanej sygnaturze, bez NAS; `discover` zapisuje
  sygnaturę); `core/viewdata.py` (`prepare_view`: liczby z indeksu liczb +
  świeże raporty, stan leniwy, zapis pliku stanu); `ui/suite_window.py`
  (start z pliku stanu; gry DAT-ów doczytywane w tle z lokalnego cache;
  zadania czekają na koniec doczytywania; wszystkie pełne `load_report_states`
  w oknie → `LazyStates`; `len(e.games)` → `game_count`; kolejność katalogów
  z pamięci; zmiana skip aktualizuje plik stanu).
- ZMIANA: start = odczyt jednego małego pliku stanu + indeksu liczb (lokalnie,
  bez NAS) → drzewo z liczbami od razu. Gry DAT-ów doczytują się w tle z
  `dat_parse_cache` (bez NAS). DatRoot przeglądamy tylko przyciskiem „Wczytaj
  DAT-y" (jak „Update DATs") i przy „Skanuj i raportuj" (jak dotąd). Brak pliku
  stanu / inne DatRoot albo rom_root w ustawieniach → stary pełny start (i
  zapis pliku stanu). Plik stanu zapisywany po: wczytaniu DAT-ów, skanie,
  podglądzie, naprawie, zmianie zaznaczenia DAT-u.
- WPŁYW: zmiany DAT-ów w DatRoot (nowy/zmieniony plik .dat, ręczna edycja
  `_reguly.json`/`_kolejnosc.json` poza programem) widać po „Wczytaj DAT-y",
  nie po samym restarcie — świadomie, jak w RomVault. Liczby/kolory bez zmian
  (ten sam stan, inne źródło odczytu). Koniec operacji szybszy: bez
  wczytywania stanu wszystkich DAT-ów (24 s „bez postępu" na końcu podglądu).
  Plan naprawy bez zmian (krok 2 osobno).
- WERYFIKACJA: testy — plik stanu: zapis/odczyt wpisów (wszystkie pola reguł),
  inne DatRoot → brak; `DatEntry.load()` z cache bez dotykania pliku DAT-u;
  indeks liczb = liczby z pełnego stanu; `LazyStates` wczytuje tylko pytany
  DAT; start okna z pliku stanu bez `discover`/NAS. Pomiar czasu startu.

## [0.6.98] — 2026-10-03

### Sprzątanie: zbędna kopia ARCHIWUM rozpoznawana po treści (członkach), nie po bajtach zipa
- DZIAŁANIE: user 02.10 (podgląd 22:09): 1552 pliki z No-intro → ToSort,
  np. „Asteroids (USA) (Atari Anthology).zip"; user: „co mają nazwy? szukasz
  po sumach, najwyżej naprawiasz nazwy".
- ANALIZA: 1484 z nich to zipy, których CAŁA treść (ROM-y w środku) jest już
  w kolekcji pod właściwą nazwą („Asteroids (USA).zip" obok). Sprzątanie
  (`_clean_dir` → `_redundant_copy`) porównuje sumę CAŁEGO pliku zip — a
  zip o innej nazwie wewnętrznej/starszy ma inne bajty, więc „treść nieznana"
  → ToSort, a dopiero KOLEJNA naprawa kasuje go z ToSort („zawartość już w
  kolekcji", ta sama reguła patrzy na członków). Dwa przebiegi, ruch po NAS,
  ToSort zapchany duplikatami.
- MIEJSCA: `rebuilder._redundant_copy` (jedyny wywołujący: `_clean_dir`;
  kasowanie z ToSort ma własną, członkową regułę — bez zmian).
- ZMIANA: gdy suma całego pliku nie ma kanonicznego „trzymacza", a plik to
  archiwum z członkami w indeksie — zbędne, gdy KAŻDY niepusty członek (SHA-1,
  bez SHA-1: CRC+rozmiar) leży w kanonicznej, fizycznej ścieżce tego
  przebiegu (plik luzem albo członek innego archiwum), poza ToSort i poza
  samym plikiem. Te same warunki co dla całego pliku (kanoniczny, nie link,
  realna naprawa potwierdza istnienie na dysku). Działa jak dotąd tylko przy
  włączonym kasowaniu ułożonych kopii z ToSort.
- WPŁYW: podgląd: TOSORT z katalogów kolekcji ↓ (~1484 u usera), „KASUJ
  zbędną kopię" ↑ o tyle samo; finałowe „KASUJ z ToSort (zawartość już w
  kolekcji)" w następnym przebiegu ↓. Archiwum z choć jednym członkiem bez
  kopii w kolekcji → dalej ToSort (nic nie ginie). Planowanie: zapytania do
  indeksu (bez NAS) dla plików niekanonicznych.
- WERYFIKACJA: test — zip pod starą nazwą z ROM-em obecnym pod właściwą
  nazwą → KASUJ zbędną kopię (nie TOSORT); zip z jednym członkiem spoza
  kolekcji → TOSORT; porównanie liczb podglądu przed/po. Ta sama funkcja
  obsługuje sieroty (katalogi bez DAT-u: „NIEZNANY→ToSort" → „KASUJ zbędną
  kopię (sierota)", gdy zipa treść jest w kolekcji).

### Kopia fizyczna gry „już OK" tylko przy zgodnych SUMACH (nie nazwa+rozmiar)
- DZIAŁANIE: user 03.10: „sprawdź, czy wszędzie masz sprawdzanie sum — nazwa
  się zmienia w nowych DAT-ach, sumy zostają; te same gry w różnych DAT-ach
  mają różne nazwy, te same sumy".
- ANALIZA (przegląd wszystkich miejsc „ta sama treść"): matcher — wszystkie
  sumy z DAT-u (`_row_full_match`), nazwa tylko jako preferencja wśród
  trafień; claim/hierarchia — klucz treści; dedup finału — identyczne bajty
  (hardlink); kasowanie z ToSort — członkowie po sumach; sprzątanie — patrz
  wyżej (0.6.98). WYJĄTEK: `rebuilder._process`, gałąź „własna kopia
  fizyczna" (treść jest gdzie indziej, ten DAT jej nie linkuje): plik pod
  kanoniczną ścieżką uznawany za „już OK" po NAZWIE + ROZMIARZE
  (`_physical_ok`) i ZGŁASZANY jako kopia fizyczna gry (`_claim`). Inna
  rewizja o tym samym rozmiarze (częste przy ROM-ach) = „OK", a dzieci
  linkowałyby do złej treści. (Matcher dał tu „gdzie indziej", więc plik pod
  tą ścieżką NIE ma sum gry.)
- MIEJSCA: `rebuilder._process` (jedyne wywołanie `_physical_ok`).
- ZMIANA: „już OK" tylko gdy wpis indeksu pod kanoniczną ścieżką ma sumy
  zgodne z ROM-em DAT-u (wszystkie podane po obu stronach, jak matcher; brak
  porównywalnej sumy = nie wiadomo → nie OK); realna naprawa dodatkowo
  potwierdza plik na dysku. Inaczej — jak w głównej ścieżce: kopia, a
  zajęte miejsce zwykłym plikiem = KONFLIKT (nic nie nadpisujemy).
  Zgłoszenie `_claim` dopiero dla potwierdzonej treści.
- WPŁYW: podgląd/naprawa: plik o złej treści pod nazwą gry → KONFLIKT
  zamiast cichego „już OK" (liczba KONFLIKT może wzrosnąć o takie pliki).
  Pliki z poprawnymi sumami — bez zmian.
- WERYFIKACJA: test — pod kanoniczną ścieżką inna rewizja o tym samym
  rozmiarze, poprawna treść w innym katalogu → nie „już OK", KONFLIKT; ten
  sam plik z poprawnymi sumami → „już OK".

## [0.6.97] — 2026-10-02

### Podgląd: fałszywe „POPRAW LINK" dla hardlinków dzieci przy przepakowaniu TorrentZip
- DZIAŁANIE: user 02.10 (zrzut podglądu, 28 min, „niby 100% a dalej szuka
  napraw"): tysiące „POPRAW LINK Z:\ROMS\1G1R\…(Retool)\X.zip ->
  Z:\ROMS\No-intro\…\X.zip"; podgląd 21:31 → 20 337 takich linii, naprawa
  01.10 → 12 576 (te same pliki).
- ANALIZA: plik w 1G1R JEST hardlinkiem do No-intro (indeks: `link_of` =
  plik No-intro, te same sumy), ale oba mają `tz=0` (nie TorrentZip). W
  etapie 2 dziecko idzie ścieżką „zła metoda/nie-TZ" → rodzic wyżej →
  `_link_over_copy`, które w PODGLĄDZIE od razu wołało `_relink_if_stale`.
  Tam `os.readlink` działa tylko dla symlinku — na hardlinku rzuca, więc
  KAŻDY poprawny hardlink wychodził jako „POPRAW LINK", a do tego 1 runda
  SMB na plik w planowaniu (stąd ~15 plików/s). W realnej naprawie (0.6.95+)
  ta sama ścieżka sprawdza `same_file` → OK, a przepakowanie rodzica i tak
  przepina hardlinki dzieci (`relink_twins`) — więc to szum podglądu i strata
  czasu, nie operacja. (0.6.94 w realnej naprawie kasował i odtwarzał te
  hardlinki — stąd 12 576 w logu z 01.10.)
- MIEJSCA: `rebuilder._link_over_copy` (jedyne wywołanie `_relink_if_stale`
  na zwykłym pliku; drugie — gałąź HAVE — jest za `_link_or_absent`, które
  przepuszcza tylko symlink/brak).
- ZMIANA: podgląd: zwykły plik wg indeksu → `_linked_to` (indeks: `link_of`
  albo te same sumy) = „już OK"; własna kopia innej treści → „POPRAW LINK"
  jak w realnej naprawie. `_relink_if_stale` tylko dla symlinku/braku.
- WPŁYW: tylko podgląd (liczba POPRAW LINK/„połączone" w podsumowaniu
  spada o hardlinki już poprawne; REPACK rodziców bez zmian). Realna naprawa
  bez zmian. Planowanie bez `readlink` na NAS dla tych plików.
- WERYFIKACJA: test — dziecko-hardlink (`link_of`) nie-TZ w podglądzie
  etapu 2: brak „POPRAW LINK", `readlink` nie wołany; własna kopia innej
  treści → dalej „POPRAW LINK".

### Postęp: pasek ogólny = cały etap, dolny = gra w bieżącym DAT-cie
- DZIAŁANIE: user 02.10: „dlaczego nie ma paska postępu dla całości stage
  2?"; dolny pasek stał na „xbox360: 32/32 100%", gdy szły inne DAT-y.
- ANALIZA: `repair` ustawia „katalog i/N" na pasku ogólnym, ale ten sam
  `progress` dostają podfazy (licznik plików naprawy `naprawa: …` w
  `rb.run`, konwersja, odbudowa CHD, sprzątanie) i natychmiast go
  nadpisują — widać „81/1214 (pliki)" jednego DAT-u, nie etap. Dolnego
  paska w pętli po grach nikt nie ustawia → zostaje wartość z poprzedniej
  fazy.
- MIEJSCA: `repair.repair_collection` — etap 1 i etap 2 (wywołania
  `rb.run`, `convert_from_source`, `convert_reports`, `rebuild_bad_chds`,
  kasowanie źródeł); `rebuilder.run` (pętla po grach).
- ZMIANA: podfazy dostają opakowany `progress`: pasek ogólny = (katalog +
  ułamek podfazy) / liczba katalogów, tekst „etap X/2 — katalog i/N: DAT ·
  podfaza (k/m)". `rb.run` przy zmianie gry (co ≥0,25 s) ustawia dolny pasek
  „DAT: gra g/G — nazwa"; start każdego DAT-u czyści dolny pasek.
- WPŁYW: tylko wyświetlanie postępu; żadnych zmian operacji ani logu.
- WERYFIKACJA: test — wartości paska ogólnego w etapie 2 rosną
  monotonicznie z katalogami mimo podfaz; dolny pasek dostaje grę.

## [0.6.96] — 2026-10-02

### Koniec operacji bez „Brak odpowiedzi": liczby drzewa liczone w tle
- DZIAŁANIE: user 02.10 (zrzut: „Naprawa kolekcji (brak odpowiedzi)", białe
  okno): „po zakończeniu każdego etapu — skanowanie, DAT-y, znajdź naprawy,
  napraw — dość długo tak wygląda na końcu".
- ANALIZA: po zakończeniu zadania wątek OKNA robi ciężką pracę: po naprawie
  `load_report_states` (959 plików, ~990 tys. gier: 11 s na danych usera) +
  liczby gier dla drzewa (1,4 s) + odczyty NAS (lista ToSort, reguły); po
  skanie/podglądzie dodatkowo `save_report_states` całego raportu (miliony
  statusów), ponowny odczyt, indeks wariantów tłumaczeń i podsumowanie —
  dziesiątki sekund „Brak odpowiedzi".
- MIEJSCA: nowy `core/viewdata.py` (`prepare_view`, `live_view`,
  `dat_counts`, `tree_extras` — bez Qt, wątek roboczy); zadania w
  `suite_window`: wczytanie DAT-ów, skan, znajdź naprawy / napraw, a także
  odświeżenie na żywo po etapie 1 naprawy (`on_reload` liczył liczby w oknie);
  odbiorcy: `_fill_dats_loaded`, `_fill_reports`, `done` naprawy,
  `_on_live_reload`; `_fill_dats(view=)` (gotowe liczby/reguły/ToSort zamiast
  liczenia w oknie; bez `view` — po staremu, np. przerwany skan, zmiana
  kolejności katalogów).
- ZMIANA: zapis/odczyt stanu, liczby per DAT, mapa wyłączonych DAT-ów,
  liczniki ToSort, warianty tłumaczeń i podsumowanie liczone NA KOŃCU
  ZADANIA w wątku roboczym (z paskiem „przygotowuję widok…"); okno tylko
  podstawia dane i rysuje drzewo.
- WPŁYW: tylko moment po zakończeniu operacji (GUI). Te same liczby, kolory i
  pliki stanu co dotąd; żadnych zmian w skanie/naprawie/indeksie.
- WERYFIKACJA: `tests/test_view_in_worker.py` — liczby `prepare_view` /
  `live_view` = dotychczasowe liczenie w oknie (też DAT-y spoza bieżącego
  raportu z zapamiętanym stanem); `_fill_reports`, `_fill_dats_loaded` i
  `_on_live_reload` z widokiem NIE wołają w oknie odczytu/zapisu stanu,
  liczenia gier, `DirRules` ani listowania ToSort (wywołanie = błąd testu).
  Pełne testy: 519 OK. Planowanie naprawy bez zmian (kod core nietknięty).

## [0.6.95] — 2026-10-02

### „Przerwij" w potoku: żadnego NOWEGO pobierania, rozpoczęte dokończone
- DZIAŁANIE: user 02.10 (odbudowa CHD): „od kliknięcia Przerwij pobierany
  jest kolejny plik do przerobienia — to już drugi po kliknięciu".
- ANALIZA: potok ma kolejkę zleconych, jeszcze nierozpoczętych zadań (do 2).
  Odbudowa CHD tworzy potok BEZ przerwania (`cancel=None`) — przerwanie
  wstrzymuje tylko zlecanie, a zlecone dalej się pobierają (minuty przez
  Tailscale każde). Konwersja odwrotnie: przekazuje przerwanie jako „anuluj
  wszystko" — gra już przerobiona, a niewysłana, jest porzucana (wbrew
  zasadzie „dokończ to, co w toku").
- MIEJSCA: `convert_pipeline.StagePipeline` (nowy `stop_new`),
  `chdrebuild` i `convert` (tworzenie potoku).
- ZMIANA: `stop_new` = przerwanie: zadanie, którego pobieranie jeszcze się
  NIE zaczęło (w kolejce albo czeka na RAM), jest pomijane; rozpoczęte
  pobieranie, przeróbka i wysyłka dokańczają się. Oba potoki tak samo.
- WPŁYW: po „Przerwij" kończą się tylko gry w toku (zwykle 1–3), żadne nowe
  pobranie; w konwersji gra przerobiona zostaje wysłana zamiast porzucona.
- WERYFIKACJA: test potoku (przerwanie po starcie 1. pobrania → kolejne nie
  ruszają, rozpoczęte przechodzą wysyłkę).

### Zip ze złą metodą: kopia dziecka → hardlink (bez „BŁĄD linku" i fałszywego KONFLIKT)
- DZIAŁANIE: podgląd A/B 02.10 (0.6.94 vs 0.6.95): +8 „KONFLIKT: …G1R\Sega -
  Mega Drive - Genesis (Retool)\…(Mega Drive Mini…).zip zajęte zwykłym
  plikiem"; test na prawdziwych plikach: „POPRAW LINK … BŁĄD linku … WinError
  183" (także w 0.6.94).
- ANALIZA: (1) odłożone do etapu 2 przepakowanie (0.6.95) — zip pod właściwą
  ścieżką szedł w etapie 1 drogą linkowania („zła nazwa" z matchera) →
  fałszywy KONFLIKT dla własnej kopii dziecka. (2) dziecko z WŁASNĄ kopią
  zipa (nie hardlink rodzica): po przepakowaniu rodzica „popraw link" usuwa
  tylko linki → zwykły plik zostaje → tworzenie linku pada (plik istnieje).
- MIEJSCA: `rebuilder._process` (gałąź złej metody / odłożenie),
  `rebuilder._link_over_copy` (nowe).
- ZMIANA: odłożony zip w etapie 1 = „jest"; kopia dziecka o tej samej treści
  podmieniana ATOMOWO na hardlink pliku rodzica (`replace_with_hardlink`),
  symlink/link — jak dotąd.
- WPŁYW: tylko zipy ze złą metodą / nie-TorrentZip z osobną kopią w DAT-cie
  niżej: hardlink zamiast błędu; mniej miejsca. Reszta bez zmian.
- WERYFIKACJA: test (ZSTD w ROMS + osobna kopia w 1G1R → bez KONFLIKT,
  hardlink, rodzic TorrentZip/deflate).

### Odbudowa CHD: RAM oddawany po przeróbce (więcej kroków na zakładkę)
- DZIAŁANIE: user 02.10 (zrzut odbudowy CD→DVD 302/479): „mamy pasek
  przenoszenia i rozpakowania, ale nie kompresji — wygląda, jakby tylko dwie
  rzeczy naraz były robione". Log: zawsze „trwa 1 kompresji naraz"; gra
  pobrana o 19:55 czekała na przeróbkę do 20:14; każde nowe pobieranie
  startuje dokładnie po „kontener podmieniony" (końcu wysyłki).
- ANALIZA: potok ma do 4 przeróbek, ale budżet RAM (23,9 GB) rezerwuje
  `rozmiar CHD × 3,2` (kopia + obraz + nowy CHD) od startu pobierania do
  KOŃCA WYSYŁKI. Wysyłka przez Tailscale trwa minuty, a do niej potrzebny
  jest tylko nowy CHD — obraz ISO/tory leżą w RAM bez potrzeby. Efekt: w
  RAM mieszczą się 2–3 gry (wysyłana + przerabiana + ew. pobrana), nowe
  pobranie czeka, przeróbki idą pojedynczo. Kompresja (8 wątków) trwa ~1
  min z ~5,5 min przeróbki, więc jej pasek rzadko widać — pasek slotu
  pokazuje kolejno rozpakowanie → kompresję → weryfikację.
- MIEJSCA: `convert_pipeline.StagePipeline` (opcjonalne zmniejszenie
  rezerwacji po etapie build + zgłaszanie czekania na RAM),
  `chdrebuild._rb_build` (sprzątanie źródeł po weryfikacji), `chdrebuild`
  (konfiguracja potoku: callbacki).
- ZMIANA: po udanej przeróbce (create + weryfikacja round-trip) w scratchu
  zostaje tylko nowy CHD; rezerwacja RAM zadania zmniejszana do jego
  rozmiaru → następne pobieranie/przeróbka ruszają w trakcie wysyłki.
  Pasek pobierania pokazuje „czeka na RAM: zajęte X / Y GB", gdy budżet
  wstrzymuje start.
- WPŁYW: tylko odbudowa CHD w potoku (konwersja ze źródła — bez zmian,
  callbacki opcjonalne). Bezpieczeństwo bez zmian: źródła kasowane dopiero
  po weryfikacji round-trip; stary CHD na NAS podmieniany jak dotąd.
- WERYFIKACJA: test potoku (drugie zadanie startuje po zmniejszeniu
  rezerwacji pierwszego, przed jego „wysyłką").

### RVZ: parametry kompresji z nazwy DAT-u (bitowa zgodność z DAT-em)
- DZIAŁANIE: user 02.10: „RVZ z nazwy DAT". DAT-y „Nintendo - GameCube /
  Wii - NKit RVZ [zstd-19-128k]" zawierają sumy SAMYCH plików RVZ; kolekcja
  (630 GC + 1266 Wii) zgodna z nimi bajtowo, a ustawienie programu to
  zstd 22 / 128 KB → RVZ zrobiony przez RomHelper nie pasowałby do DAT-u.
- ANALIZA: konwersja ISO→RVZ (`iso_to_rvz`, DolphinTool) bierze poziom i
  blok wyłącznie z ustawień (2 miejsca: potok i seryjnie).
- MIEJSCA: `convert.rvz_params` (nowe), `convert._conv_build_run`,
  `convert._convert_one` (+ wywołanie z `convert_reports`).
- ZMIANA: znacznik `[zstd-<poziom>-<blok>k]` w nazwie DAT-u (nagłówek albo
  nazwa pliku DAT) wyznacza poziom i blok RVZ tego DAT-u; bez znacznika —
  ustawienie programu jak dotąd. Log konwersji podaje użyte parametry.
- WPŁYW: tylko konwersje do RVZ dla DAT-ów ze znacznikiem (u usera: NKit RVZ
  GC/Wii): wynik bitowo zgodny z DAT-em (DolphinTool deterministyczny przy
  tych samych parametrach). Inne formaty i DAT-y — bez zmian.
- WERYFIKACJA: test odczytu parametrów (znacznik / brak → ustawienia).

### ZIP zawsze jako TorrentZip (bitowo powtarzalny, jak RomVault)
- DZIAŁANIE: user 02.10: „czy możemy zrobić, aby pliki zip były zawsze
  pakowane jak TorrentZip… istniejące trzeba przepakować, pomoże to w
  deduplikacji". Próbka 40 z 148 260 zipów kolekcji: TorrentZip 19,
  RVZSTD (zstd RomVaulta, emulatory nie czytają) 12, bez znacznika 9
  (głównie zapisane przez RomHelper).
- ANALIZA: program pisze zipy biblioteką `zipfile` (data bieżąca, kolejność
  z DAT-u, flagi) — ta sama treść = różne bajty → brak hardlinków między
  takimi zipami, RomVault widzi „nie TorrentZip". Sam format TorrentZip
  (posortowane nazwy, deflate 9, stała data 1996-12-24 23:32, brak extra,
  komentarz `TORRENTZIPPED-<CRC katalogu>`) to za mało: Python 3.14 ma
  zlib-ng (`1.3.1.zlib-ng`), który kompresuje INACZEJ niż klasyczny zlib.
  Test na 10 członkach TorrentZipów RomVaulta: klasyczny zlib 1.2.11 /
  1.3.1 / 1.3.2 → 10/10 strumieni IDENTYCZNYCH; zlib-ng → 0/10.
- MIEJSCA: nowy `core/torrentzip.py` (zapis + rozpoznanie + przepakowanie;
  klasyczny zlib przez ctypes z dołączonej `chd_zlib1.dll` (zlib 1.3.2;
  unikalna nazwa modułu, by nie podstawiła się inna zlib1.dll), zależna tylko
  od kernel32/msvcrt; awaryjnie zlib Pythona z ostrzeżeniem), zapisy zipów:
  `rebuilder._rebuild_zip`, `convert.pack_zip`, `convert.repack_zip`,
  `bios` (zipy BIOS-ów); indeks: kolumna `tz` (wypełniana przy indeksowaniu
  zipa + jednorazowe sprawdzenie istniejących zipów w skanie, równolegle);
  matcher/rebuilder: zip nie-TorrentZip = do przepakowania (ta sama droga co
  „zła metoda ZIP": w miejscu, przepięcie hardlinków); `chd_buddy.spec`
  (dołączenie DLL).
- ZMIANA: każdy zip zapisywany przez program (deflate) to TorrentZip
  identyczny bajtowo z RomVaultem. Istniejące zipy: nie-TorrentZip
  (także RVZSTD) przepakowywane w miejscu do TorrentZip; członkowie bez
  zmian (weryfikacja CRC i SHA-1), hardlinki przepięte na nowy plik.
  WYJĄTEK: zip, którego sumę CAŁEGO pliku zna jakiś DAT (dir2dat Arcade1TB
  opisuje zipy jako pliki) — nie ruszany (inna suma = niezgodność z DAT-em).
  Ustawienie `zip_method=zstd` — bez TorrentZip (jak dotąd).
- WPŁYW: zipy zapisywane przez program; istniejące nie-TorrentZipy (rzędu
  kilkudziesięciu tysięcy, przepakowanie przez NAS — etap 2, przerywalne);
  ta sama gra w kilku DAT-ach po przepakowaniu = jeden plik (hardlink).
  Skan: jednorazowo odczyt końcówki każdego zipa bez oznaczenia
  (równolegle). Treść ROM-ów, nazwy, układ — bez zmian.
- WERYFIKACJA: test bitowej zgodności z TorrentZipem RomVaulta (próbka z
  kolekcji); testy zapisu/rozpoznania/przepakowania; wyjątek dir2dat;
  pełny podgląd A/B.

## [0.6.94] — 2026-10-01

### dir2dat: tory i opisy płyty jednej gry = jedna gra (bez CHD z pojedynczych torów)
- DZIAŁANIE: podgląd A/B 01.10 (także 0.6.93): „KONWERSJA(ze źródła)→CHD
  …\RetroBat
oms\psx\Castlevania - Rondo of the Night (v1.7) (USA)
  (Track 1).bin → …(Track 1).chd", „…\psx\Marvel Super Heroes vs. Street
  Fighter (USA).cue → ….cue.chd" — CHD z POJEDYNCZYCH torów/opisu, a potem
  kasowanie źródeł (gra w RetroBacie zniszczona).
- ANALIZA: dir2dat zapisuje KAŻDY plik luzem jako osobną „grę": `X (Track
  1)`, `X (Track 2)`, a przy kolizji nazw `X.cue` obok `X` (z `X.bin`).
  Parser łączył tylko `x.zip`/`x.7z` z `x`. DAT-y Redump/No-Intro nie mają
  gier o takich nazwach (tory to ROM-y jednej gry).
- MIEJSCA: `datfile.parse_dat` (łączenie), `datcache.CACHE_VERSION` (wynik
  parsowania się zmienia — cache DAT-ów przeliczany raz).
- ZMIANA: „gra" `X.cue`/`.gdi`/`.toc`/`.ccd`/`.mds` oraz `X (Track N)` →
  ROM-y dołączone do gry `X` (tak jak `x.zip`).
- WPŁYW: tylko DAT-y dir2dat z luźnymi płytami (Arcade1TB psx, ps2,
  ports…): gra wielościeżkowa jest JEDNĄ grą (odcisk całości → link do CHD
  w ROMS albo konwersja całości); zero CHD z pojedynczych torów. Pierwsze
  uruchomienie: wszystkie DAT-y parsowane od nowa (jednorazowo).

### DAT z samymi plikami frontendu = pusty, poprawny DAT
- DZIAŁANIE: podgląd A/B 01.10: „POMIJAM DAT bez gier: …\Arcade1TB  fpinball.dat / switch.dat" → „POMIJAM sprzątanie sierot: nie wczytano 2
  DAT-ów" (bezpiecznik z 0.6.93 wyłączył całe sprzątanie sierot).
- ANALIZA: po odrzuceniu „gier" frontendu (0.6.94) DAT bez prawdziwych gier
  był liczony jak niewczytany (pusty/uszkodzony).
- MIEJSCA: `datstore.discover`.
- ZMIANA: DAT, który MA wpisy, ale same frontendowe — wczytany jako pusty
  DAT (katalog dalej należy do DAT-u, nie jest sierotą); niewczytany tylko
  DAT naprawdę pusty/nieczytelny.
- WPŁYW: fpinball/switch (Arcade1TB) — wczytane bez gier; sprzątanie sierot
  działa jak dotąd.

### Format „auto" z JSON-a DAT-u (Redump = CHD/ISO, No-Intro = zip) + pierwszeństwo CHD
- DZIAŁANIE: user 01.10 (wgrywa nowe DAT-y z plikami JSON): „wszystkie DAT-y
  w Redump to CHD albo ISO, w No-Intro zip; gry z nośnika fizycznego bywają
  też w No-Intro (dystrybucja cyfrowa) z TYMI SAMYMI sumami — wtedy
  pierwszeństwo ma CHD". Podgląd 17:41: nowy DAT „3DO Interactive
  Multiplayer" dostawał format zip.
- ANALIZA: (1) format „auto" zgadywany z NAZWY systemu (tabela skrótów);
  nieznana nazwa → zip, także dla DAT-ów Redump. JSON RomVaulta przy DAT-cie
  mówi wprost: `"group": "ReDump"` / `"NoIntro"` (wczytywany do
  `DatEntry.meta`, ale nieużywany do formatu). (2) Matcher szuka CHD gry
  (odcisk całej gry) TYLKO dla DAT-ów płytowych (chd/rvz); DAT zipowy z
  obrazem płyty (No-Intro, wydanie cyfrowe) nie widzi istniejącego CHD
  z Redump → osobna kopia w zipie (te same dane drugi raz).
- MIEJSCA: `dirrules.resolve_format` (jedno miejsce formatu „auto"),
  `matcher.match_game` / `_match_game_roms` (krok CHD).
- ZMIANA: (1) „auto": GameCube/Wii → rvz; PS3/Xbox/X360 → obraz bez zmian;
  `group` ReDump → CHD dla systemów z obsługą CHD, inaczej obraz bez zmian
  (ISO); `group` NoIntro → zip; bez JSON-a — jak dotąd (po nazwie systemu).
  (2) gra z obrazem płyty (iso/bin/img/cue/gdi/cdi) w DAT-cie zipowym/„keep"
  — gdy w kolekcji jest CHD z odciskiem tej gry, gra = ten CHD (hardlink
  `<gra>.chd`), nie zip.
- WPŁYW: (1) DAT-y z JSON-em, których system nie był rozpoznany po nazwie
  albo grupa przeczy zgadywaniu (lista w raporcie A/B); DAT-y bez JSON-a —
  bez zmian. Format per platforma jak dotąd (pierwszy DAT platformy).
  (2) tylko gry płytowe w DAT-ach niepłytowych z istniejącym CHD tej gry:
  link do CHD zamiast zipa; ich dotychczasowe zipy w katalogu DAT-u stają
  się zbędne (sprzątanie jak dla innych nadmiarowych plików). Gry
  kartridżowe — bez zmian (CHD nie jest szukany).
- WERYFIKACJA: testy (format z group; gra PSN w No-Intro z CHD w Redump →
  link do CHD, nie zip); pełny podgląd A/B po zakończeniu wgrywania DAT-ów.

### Pliki frontendu (media RetroBata, gamelist.xml) nie są grami
- DZIAŁANIE: podgląd 01.10 17:41 (i już 0.6.92 o 11:24) — DAT-y dir2dat
  Arcade1TB obejmują CAŁY folder RetroBata: „KONWERSJA(ze źródła)→CHD
  …\dreamcast\images\… (+65 plików) → dreamcast\images.chd" (28× CHD:
  images/videos/manuals/mixart/snap/wheel, gamelist.xml.backup1 →
  gamelist.xml.chd), „→ZIP atomiswave\manuals.zip/mixart.zip/wheel.zip"
  (źródła po konwersji kasowane!), „TOSORT …\gamelist.xml" (26 systemów),
  „KASUJ zbędną kopię: fpinball\gamelist.xml (jest w gamelist.xml.backup1)",
  „NAZWA ps3\manuals\…-manual.pdf → ps3\…-manual.pdf".
- ANALIZA: dir2dat robi „grę" z każdego podfolderu i pliku: `images`,
  `manuals`, `mixart`, `snap`, `videos`, `wheel`, `nppBackup`,
  `gamelist.xml*`. Program traktuje je jak ROM-y: format DAT-u (CHD/zip)
  → konwersja i kasowanie źródeł; `gamelist.xml` zmienia EmulationStation,
  więc nie pasuje do DAT-u → sprzątanie wynosi go do ToSort. Żadna
  prawdziwa naprawa jeszcze tego nie wykonała (11:30 przerwana w etapie 1).
- MIEJSCA: nowy `core/frontend.py` (jedna reguła), `datstore.discover` i
  `DatEntry.load` (gry frontendu poza DAT-em), `rebuilder._clean_dir`
  i `rebuilder.sweep_orphans` (pliki frontendu nietykalne).
- ZMIANA: „gra" o nazwie folderu frontendu (images, videos, manuals,
  mixart, wheel, snap, marquee, thumbnails, screenshots, fanart, boxart,
  titles, box2dfront, box3d, boxback, bezel, map, downloaded_images,
  downloaded_videos, downloaded_media, nppbackup) albo zaczynająca się od
  „gamelist" — pomijana przy wczytaniu DAT-u. Plik w takim folderze albo
  `gamelist*` w katalogu DAT-u / folderze-sierocie — sprzątanie go nie
  rusza (ani ToSort, ani kasowanie).
- WPŁYW: tylko DAT-y z takimi „grami" (Arcade1TB) i pliki frontendu w
  katalogach DAT-ów. Liczby gier w tych DAT-ach spadają o te pozycje.
  Prawdziwe gry (także z regionem w nazwie, np. „Snap (USA)") bez zmian.
  Cache DAT-ów bez zmian (filtr po wczytaniu).

### Zły kontener CHD nie blokuje zmiany nazwy ani linków
- DZIAŁANIE: podgląd 01.10 17:41 — 9× „TOSORT Z:\ROMS\ROMS\ps2\Disney-Pixar
  Cars - Mater-National Championship (USA).chd" (nowy DAT PS2 11844: „(USA,
  Canada)"); linki w No-intro/1G1R do CHD ze złym kontenerem czekały na
  odbudowę (466 CHD, ~doba przez Tailscale).
- ANALIZA: matcher degraduje grę ze złym kontenerem do „zła nazwa" (także
  gdy plik leży pod właściwą ścieżką), a rebuilder dla `bad_container`
  kończył obsługę gry: bez zmiany nazwy, bez rezerwacji (dzieci nie
  linkują), bez ochrony realnej ścieżki → po zmianie nazwy w DAT-cie plik
  wyglądał na obcy i szedł do ToSort. Odbudowa CD→DVD od 0.6.85 i tak
  przepina hardlinki (`relink_twins`), więc czekanie nie jest potrzebne.
- MIEJSCA: `rebuilder._process` (gałąź złego kontenera).
- ZMIANA: zły kontener liczony jak dotąd (licznik, odbudowa w etapie 2 /
  „Odbuduj CHD"), ale gra przechodzi zwykłą ścieżkę: plik pod właściwą
  ścieżką = „jest" (rezerwacja → dzieci linkują), inna nazwa = NAZWA,
  gdzie indziej = link/przeniesienie; realna ścieżka chroniona przed
  sprzątaniem.
- WPŁYW: CHD ze złym kontenerem: zmiany nazw wg DAT-u i hardlinki od razu;
  odbudowa później podmienia plik i przepina wszystkie hardlinki. Nic nie
  idzie do ToSort z powodu złego kontenera.

### Nazwy katalogów ES jak w RetroBacie dla kolejnych systemów
- DZIAŁANIE: podgląd 01.10 17:41 — „PRZENIEŚ Z:\ROMS\ROMS\3do\… ->
  Z:\ROMS\ROMS\3DO Interactive Multiplayer\…" (617 CHD); nowe DAT-y w ROMS
  dostają katalogi „Bandai - WonderSwan", „SNK - NeoGeo Pocket Color",
  „Sinclair - ZX Spectrum +3", „NEC - PC-88 (Flux)", „Sharp - X68000
  (Flux)", „Nintendo - Nintendo 64DD".
- ANALIZA: nazwa ES pochodzi z tabeli `SYSTEM_ALIASES` → `ES_FOLDER`. Nowy
  DAT 3DO nazywa się „3DO Interactive Multiplayer" (bez „Panasonic -"), a
  powyższych systemów w tabeli nie ma → nazwa DAT-u jako katalog.
- MIEJSCA: `shortcuts.SYSTEM_ALIASES`, `dirrules.ES_FOLDER`.
- ZMIANA: nazwy jak w RetroBacie usera: 3do (także „3DO Interactive
  Multiplayer"), wswan, wswanc, ngp, ngpc, zxspectrum, pc88 („NEC - PC-88"),
  x68000, n64dd, gamepock. Uzupełnienie (lista DAT-ów ROMS bez mapowania,
  JSON `system` = ta sama nazwa, więc nazwy wg folderów RetroBata usera):
  archimedes („Acorn - Archimedes & Risc PC"), amigacdtv, fmtowns („Fujitsu -
  FM Towns series"), pc98 („NEC - PC-98 series"), pcenginecd („NEC - PC
  Engine CD & TurboGrafx CD"), cdi („Philips - CD-i"), ps4, ps5, xboxone
  („Microsoft - Xbox One" i „(Digital) (ExtractedFiles)"), xboxseriesx.
  Bez zmian: „Commodore - Amiga CD" (RetroBat nie ma osobnego systemu),
  SNESMSU1 i TeknoParrot Collection (własne katalogi usera).
  Format: PC Engine CD i CD-i → płyty z obsługą CHD (MAME/emulatory czytają
  CHD); PS4/PS5/Xbox One/Series → obraz bez zmian.
- WPŁYW: tylko DAT-y z naming=es tych systemów (ROMS): katalog docelowy
  zmienia się na nazwę ES; 3DO zostaje w `ROMS\3do` (brak przenosin 617
  CHD); `ROMS\Epoch - Game Pocket Computer` → `ROMS\gamepock` (gdy DAT
  wróci). No-intro/1G1R (naming=dat) bez zmian.
- WERYFIKACJA (całość 0.6.94): testy (media/gamelist z DAT-u dir2dat
  pominięte i nietykalne; zły kontener + zmiana nazwy → NAZWA + link, nie
  ToSort; nazwy ES); pełny podgląd A/B na kopii bieżącego indeksu.

## [0.6.93] — 2026-10-01

### ToSort\cues = biblioteka cue tylko do odczytu (nigdy kasowana ani zabierana)
- DZIAŁANIE: user 01.10: „nie kasować plików cue z ToSort\cues — czasem jest
  pojedynczy bin bez cue i trzeba go wziąć stamtąd". W ToSort\cues leży 80
  paczek cuesheetów Redump (zip, 01.10 13:24); mogą tam trafić też luźne .cue.
- ANALIZA: ToSort jest dla naprawy źródłem do ZUŻYCIA. Ścieżki, które
  ruszyłyby bibliotekę: (1) „zbędne archiwa w ToSort" — paczka cue, której
  wszystkie cue są już w kolekcji, byłaby skasowana; (2) „opisy ścieżek bez
  torów" — luźne .cue bez binów obok (cały katalog cues) skasowane; (3)
  przeniesienie z ToSort do kolekcji (cue pasujący do DAT-u zabrany z
  biblioteki); (4) finał kopie→linki kasuje kopie w ToSort potwierdzone w
  kolekcji; (5) konwersja kasuje źródła z ToSort po zrobieniu CHD (tory,
  cue, archiwa, luźne duplikaty dziecka).
- MIEJSCA: `paths.protect` / `paths.is_protected` (jeden rejestr),
  `repair.repair_collection` (rejestracja `<ToSort>\cues` dla każdego
  ToSort); sprawdzenie w: `rebuilder._process` i `_place_archive`
  (przeniesienie → kopia), `rebuilder._dedup_confirmed`,
  `rebuilder._purge_redundant_tosort_archives`,
  `prune.purge_orphan_descriptors`, `convert._purge_redundant_tosort_tracks`,
  `convert._purge_child_loose_duplicates`,
  `convert._defer_or_purge_game_sources`, `convert.purge_source_files`.
- ZMIANA: plik w chronionym katalogu jest źródłem tylko do ODCZYTU: naprawa
  bierze z niego KOPIĘ (wypakowanie z paczki jak dotąd), nigdy go nie
  przenosi, nie kasuje i nie przepakowuje w miejscu; podgląd nie pokazuje
  dla niego KASUJ.
- WPŁYW: tylko pliki pod `<ToSort>\cues`. Reszta ToSort — bez zmian
  (zużywana i sprzątana jak dotąd). Kolekcja i katalogi DAT-ów — bez zmian.
- WERYFIKACJA: testy (luźny .cue w ToSort\cues pasujący do DAT-u → kopia,
  źródło zostaje; paczka cue z całą treścią w kolekcji → nie kasowana;
  .cue bez binów → nie kasowany; stary kod: skasowane/przeniesione); pełny
  podgląd A/B.

### DAT, który się nie wczytał, nie może zrobić z katalogu „sieroty"
- DZIAŁANIE: podgląd próbny 01.10 (dwa procesy naraz na tym samym cache
  DAT-ów): „POMIJAM uszkodzony DAT (nie sparsowano): …1G1R\FinalBurn
  Neo-ColecoVision … — PermissionError: [WinError 32] … dat_parse_cache\
  1e7d….pkl.tmp" dla 12 DAT-ów 1G1R, a w finale 1608× „NIEZNANY→ToSort
  (brak DAT-a)" (np. 1G1R\FinalBurn Neo - ColecoVision Games\2010.zip) i
  2439× „KASUJ zbędną kopię (sierota)" w ich katalogach.
- ANALIZA: (1) zapis cache DAT-u jest „przy okazji", ale przy błędzie
  sprzątanie `tmp.unlink()` samo rzucało wyjątek (plik trzymany przez drugi
  proces) → poprawnie SPARSOWANY DAT uznany za uszkodzony i pominięty.
  Nazwa pliku tymczasowego jest wspólna dla wszystkich procesów
  (`<hash>.pkl.tmp`). (2) Pominięty DAT znika z listy, więc jego katalog
  docelowy wygląda na sierotę (`stray_dirs`) i finał wynosi jego pliki do
  ToSort albo kasuje „zbędne kopie". To samo zrobiłby każdy chwilowy błąd
  odczytu DAT-u z NAS.
- MIEJSCA: `datcache.DatParseCache._write`, `datcache._write_report_file`,
  `datstore._save_sha1_cache` (te same wzorce zapisu), `datstore.discover`
  (rejestr niewczytanych DAT-ów), `repair.repair_collection` (finał:
  sprzątanie sierot).
- ZMIANA: pliki tymczasowe cache z numerem procesu, sprzątanie po błędzie
  nie rzuca wyjątku (zapis cache nigdy nie psuje wczytania DAT-u). Discover
  zapamiętuje DAT-y, których NIE wczytano (`datstore.failed_dats()`); gdy
  jest choć jeden — finał POMIJA sprzątanie sierot z komunikatem „nie
  wczytano N DAT-ów — ich katalogi wyglądałyby na sieroty". DAT pusty (bez
  gier) liczy się tak samo.
- WPŁYW: tylko sytuacja z błędem wczytania DAT-u — wtedy brak „NIEZNANY→
  ToSort" i „KASUJ zbędną kopię (sierota)" w tym przebiegu (reszta naprawy
  bez zmian). Normalny przebieg (wszystkie DAT-y wczytane) — identyczny.
  Cache: te same pliki docelowe, inna tylko nazwa tymczasowa.
- WERYFIKACJA: testy (błąd zapisu cache przy zajętym tmp → DAT wczytany;
  niewczytany DAT → brak sprzątania sierot, stary kod: pliki do ToSort);
  podgląd A/B bez równoległych procesów.

### Ten sam plik opisany różnie (zip jako gra vs zip jako plik) = jedna treść
- DZIAŁANIE: podgląd A/B 01.10 — „PRZENIEŚ archiwum Z:\Arcade2\RetroBat\
  roms\nes\Teenage Mutant Ninja Turtles III … (USA).zip -> Z:\ROMS\1G1R\
  FinalBurn Neo - NES Games\tmntiii.zip", a DAT Arcade1TB „nes" (dir2dat)
  bez linku do nowego miejsca. Próba na prawdziwej naprawie (0.6.92 i
  nowy kod tak samo): naprawa 1 przenosi zip do FBNeo, naprawa 2 zabiera go
  z powrotem do „nes" — ping-pong, hardlink nigdy nie powstaje.
- ANALIZA: te same bajty, dwa opisy: FBNeo zna sumy ROM-u W ŚRODKU zipa
  (gra-archiwum), dir2dat zna sumę CAŁEGO pliku zip (zip jako ROM). (1)
  Hierarchia pyta „czy DAT ma tę treść" tylko sumą z DAT-u pytającego →
  FBNeo „nie ma" pliku opisanego sumą zipa i odwrotnie → każdy uznaje plik
  drugiego za niczyj i go zabiera. (2) Rezerwacja przeniesionego pliku jest
  pod kluczem opisu FBNeo (`arcset:`), a „nes" szuka pod `sums:` zipa → w
  tym samym przebiegu nie wie, że jego plik się przeniósł (do następnej
  naprawy brak pliku).
- MIEJSCA: `rebuilder._hier_rom` (o co pyta hierarchia), `hierarchy.
  owned_above` / `must_keep_source` (wiele sum naraz), `rebuilder._process`
  + `_claim` (rezerwacja także po sumie CAŁEGO pliku przy przeniesieniu/
  linku całego pliku tymi samymi bajtami).
- ZMIANA: tożsamość pliku fizycznego = wszystko, co indeks o nim wie: suma
  ROM-u z DAT-u, suma całego pliku, odcisk gry (`data_sha1`), nagłówek CHD
  (`chd_sha1`), sumy członków archiwum; DAT „ma treść", gdy zna KTÓRĄKOLWIEK.
  Rezerwacja całego pliku (te same bajty — nie przepakowanie, nie
  wypakowanie członka) także pod kluczem `file:<sha1 pliku>`; DAT z innym
  opisem tego pliku znajduje ją i robi hardlink w tym samym przebiegu.
- WPŁYW: pary DAT-ów opisujące ten sam plik różnie (dir2dat Arcade1TB z
  zipami jako plikami ↔ No-intro/FBNeo z grami-archiwami; DAT dysków ↔ DAT
  torów — wcześniej obsłużone osobno przez `data_sha1`, teraz w tej samej
  regule): przeniesienie raz + hardlink, bez ping-pongu. Przepakowanie
  (inne bajty) nie dostaje klucza `file:` → bez zmian. Koszt: odczyty z
  lokalnego SQLite (bez NAS).
- WERYFIKACJA: test (FBNeo zip-gra + dir2dat zip-plik: naprawa 1 = przeniesienie
  + hardlink, naprawa 2 = zero operacji; stary kod: ping-pong); pełny podgląd
  A/B na kopii bieżącego indeksu.

### Te same dane w jednym katalogu (także w jednym DAT-cie) = hardlink; dyski MAME w folderze gry
- DZIAŁANIE: podgląd 01.10 — „KOPIA (dedup w kolekcji → fizyczna)
  Z:\Arcade2\RetroBat\roms\mame\simpbowl.chd <- …\mame\simpbowl\
  829uaa02.chd" i w finale „KASUJ zbędną kopię: …\mame\simpbowl\
  simpbowl.chd". User: te same dane = hardlink, dedup ma to wychwycić.
- ANALIZA: to JEDEN DAT (dir2dat „mame"): gra simpbowl ma zip z ROM-ami i
  DWA dyski („829uaa02", „simpbowl") o tej samej treści, oba w
  `mame\simpbowl\`. (1) Układ z 0.6.90: dysk nazwany jak gra → PŁASKO
  `mame\simpbowl.chd` — dobre dla dir2dat psx/ps2 (gra = jeden CHD), złe dla
  MAME (gra z zipem/kilkoma dyskami szuka dysków w `<set>\`) → kopia na
  płaską ścieżkę + kasowanie poprawnego pliku. (2) Hierarchia nie linkowała
  w obrębie jednego katalogu (`above` wymagał innego katalogu — reguła z
  czasów symlinków), więc duplikaty jednego DAT-u i DAT-ów dzielących
  katalog zostawały osobnymi plikami.
- MIEJSCA: `matcher.disk_path` / `match_disk` / `match_game` (układ),
  `hierarchy.above`, `hierarchy.should_link`, `hierarchy.must_keep_source`.
- ZMIANA: (1) dysk płasko tylko, gdy gra to JEDEN dysk bez ROM-ów i nazwa
  dysku = nazwa gry; inaczej `<katalog>\<set>\<dysk>.chd`. (2) „wyżej" =
  DAT o wyższej pozycji także we WSPÓLNYM katalogu; `should_link` pozwala
  też na link w obrębie własnego katalogu/DAT-u (duplikat treści) — POZA
  luźnymi plikami DAT-u konwertowanego do CHD/RVZ (konwersja je kasuje,
  link by wisiał — katastrofa D2). `must_keep_source` pyta wszystkie DAT-y
  katalogu źródła poza pytającym.
- WPŁYW: (1) tylko gry z `<disk>` mające ROM-y albo kilka dysków (MAME,
  Naomi, Atomiswave z dyskami w Arcade1TB) — dysk nazwany jak gra zostaje w
  folderze gry. (2) identyczne pliki w jednym katalogu (duplikaty w DAT-cie,
  DAT-y dzielące katalog) → hardlink zamiast kopii, także w finale
  (kopie→linki). Luźne pliki gier do konwersji — bez zmian.
- UZUPEŁNIENIE (podgląd B4): dir2dat-y RetroBata obejmują CAŁY folder, także
  pliki NADPISYWANE przez programy — nowa reguła łączyła `gamelist.xml` z
  `gamelist.xml.backup1` (fpinball, switch), `.m3u` z kopią Notepad++
  (`.bak`), `.png.tmp` z `.png`. Zapis w miejscu przez jedną nazwę zmienia
  wszystkie hardlinki (EmulationStation nadpisałby własną kopię zapasową).
  ZMIANA: `hierarchy.linkable(path)` — jedno miejsce, wołane przez
  `should_link` (naprawa, konwersja, finał kopie→linki): NIE łączymy plików
  konfiguracji/zapisów/kopii/tymczasowych (.xml .json .cfg .ini .txt .log
  .bak .tmp .old .m3u .lst .db .srm .sav .nvram .eep .rtc oraz nazwy z
  „.backup"/„.bak"/„.tmp"/„.state"). Zostają jak są (nic nie kasowane, nie
  przenoszone).
- WERYFIKACJA: testy (MAME: zip + 2 dyski o tej samej treści → oba w
  `<set>\`, jeden plik fizyczny + hardlink, bez kasowania; dwa DAT-y we
  wspólnym katalogu → hardlink; stary kod: KOPIA); pełny podgląd A/B.

### Linki = hierarchia katalogów + ta sama treść (bez warunku „platforma")
- DZIAŁANIE: naprawa 01.10 — „KOPIA (plik innego DAT-u zostaje)
  Z:\Arcade2\RetroBat\roms\xbox360\… -> Z:\ROMS\REDUMP\Microsoft - Xbox 360
  (Digital)\…" — 175 plików, ~37 GB kopii zamiast hardlinków, choć
  dopasowanie po sumach wie, że to te same dane (user: „te same dane w dwóch
  miejscach → hardlink").
- ANALIZA: link (dziecko → plik DAT-u wyżej) wymagał RÓWNEJ „platformy"
  (klucz z nazwy DAT-u). dir2dat nazywa się „xbox360", REDUMP „Microsoft -
  Xbox 360 (Digital)" → różne klucze → kopia. 0.6.90 łatało to aliasem po
  NAZWIE KATALOGU (psx → ROMS\psx) — działało tylko tam, gdzie DAT wyżej
  leży w katalogu o nazwie ES; Xbox 360 (tylko REDUMP, naming=dat) i każda
  inna taka para dalej kopiowały. Błąd FORMUŁY, nie platformy: o relacji
  decyduje hierarchia katalogów (_kolejnosc.json) i treść (sumy), nazwa
  platformy jest zbędna. Warunek siedział w 3 miejscach:
  `Hierarchy.above`/`owned_above`, klucz linków rebuildera
  (`platforma|treść`), klucz konwersji (`platforma, odcisk`).
- MIEJSCA: `hierarchy.py` (DatNode, add, above, owned_above, opis modułu;
  usunięty alias po nazwie katalogu z 0.6.90), `rebuilder._process` (klucz
  linków; `_plat_claims` scalone z `_claims` — po zmianie zawsze równe),
  `convert.convert_from_source` (`_plat_key` → `_dedup_key`, 4 użycia).
  Test ping-pongu FBNeo (`test_crc_only_dat_owns_its_files`) pokazał, że
  warunek platformy przypadkiem chronił też zipy z INNYMI nazwami wewn. →
  `must_keep_source(same_bytes=)`: przepakowanie = inny plik, hardlink
  niemożliwy → źródło zostaje u właściciela (wołane z `_place_archive`).
- ZMIANA: plik leżący w katalogu DAT-u WYŻEJ, którego treść ten DAT ma
  (sumy / odcisk gry) = rodzic → DAT niżej robi HARDLINK (albo rodzic
  dostaje plik przeniesiony z dołu, a dół hardlink). Bez porównywania nazw
  platform. Model (user 01.10): nie ma jednego katalogu głównego — punktem
  startowym pliku jest NAJWYŻSZY DAT, który go ma (ROMS, jak nie ma — REDUMP,
  jak nie ma — No-intro…); każde inne miejsce z tymi samymi danymi =
  hardlink (dedup), także w obrębie ROMS (ten sam dump MSX i SMS). Hardlink
  jest równorzędny z plikiem, więc „rodzic/dziecko" to tylko kolejność
  wyboru punktu startowego. Bez zmian: `dedup_copies=false` działa tylko,
  gdy ktoś go jawnie ustawi (u usera nie ma); zipy z innymi nazwami
  wewnętrznymi = inna treść (przepakowanie, nie link); ToSort bez linków;
  w kolekcji tylko hardlinki, symlinki wyłącznie do obrazu kolekcji na
  dysku lokalnym (mirror).
- WPŁYW: DAT-y niżej w hierarchii z treścią identyczną z plikiem DAT-u wyżej
  o innej nazwie platformy — Arcade1TB (xbox360 i inne dir2dat), 1G1R/
  [T-En]/BIOS z identycznym plikiem innego DAT-u wyżej, FBNeo Neo Geo Games
  (1G1R) ↔ FBNeo Arcade: kopie fizyczne → hardlinki (mniej miejsca na NAS,
  brak transferu). `must_keep_source` (ping-pong MSX/FBNeo) działa dalej —
  korzysta z tej samej `should_link`. Konwersja: CHD dziecka linkuje do CHD
  rodzica o tym samym odcisku także między „platformami". Skan,
  dopasowanie, formaty — bez zmian.
- WERYFIKACJA: testy (Xbox 360 REDUMP naming=dat + dir2dat „xbox360" →
  hardlink, stary kod: KOPIA; jawne dedup_copies=false dalej fizycznie);
  pełny podgląd A/B na kopii BIEŻĄCEGO indeksu, raport per DAT.

### Przepakowanie ZIP: w logu cel, powód i liczba plików + postęp w trakcie
- DZIAŁANIE: naprawa FBNeo — linie „PRZEPAKUJ Z:\Arcade2\RetroBat\roms\mame\
  mslug.zip -> mslug.zip (wypakuj ROM-y gry z nadzbioru) [źródło zostaje:
  plik innego DAT-u]" wyglądały jak przepakowanie istniejącego pliku; nie
  było widać, DOKĄD trafia wynik, DLACZEGO (gry nie ma w fbneo) ani ILE
  plików bierze. W trakcie składania zipa strażnik ciszy pokazywał
  „20 s bez postępu" w `_rebuild_zip` (czytanie z NAS bez postępu).
- ANALIZA: log składa tylko nazwę pliku celu i ogólny opis; `_rebuild_zip`
  czyta członków w całości (`zin.read`) i zapisuje bez żadnego wywołania
  paska szczegółowego (on resetuje strażnika ciszy), potem
  `reindex_archive` czyta nowy zip jeszcze raz (sumy pliku + członków) —
  też bez postępu. Ta sama klasa ciszy w `convert.repack_zip` (zła metoda
  ZIP → deflate, 3 odczyty każdego członka), wołanym z dwóch miejsc
  rebuildera.
- MIEJSCA: `rebuilder._place_archive` (linia logu PRZEPAKUJ),
  `rebuilder._rebuild_zip`, `fileindex.reindex_archive` /
  `_index_members` / `_hash_zip_members` (opcjonalny postęp),
  `convert.repack_zip` (opcjonalny postęp), `rebuilder._repack_bad_zip` i
  pętla „zła metoda ZIP" (przekazują postęp).
- ZMIANA:
  - log: `PRZEPAKUJ <źródło> -> <PEŁNA ścieżka celu> (<co>: N z M plików
    źródła; <powód>) [los źródła]`. Powód: „gry brak w <katalog celu>"
    (cel nieznany indeksowi), „plik w celu niekompletny/zły — zastępuję"
    (cel jest w indeksie), „złe nazwy wewn." (w miejscu). M = członkowie
    źródła z indeksu (bez odczytu NAS; brak w indeksie → bez „z M").
  - `_rebuild_zip`: kopiowanie członków STRUMIENIOWO porcjami (4 MB) z
    liczeniem SHA-1/CRC w locie i paskiem szczegółowym „przepakowuję
    <cel>: <ROM> (i/N)" w bajtach; weryfikacja sum przed podmianą jak
    dotąd (zła treść → tmp skasowany, nic nie powstaje).
  - `reindex_archive(..., on_progress)` i `repack_zip(..., on_progress)`:
    pasek „indeksuję/przepakowuję <plik>: <członek>"; domyślnie None
    (wywołania bez postępu — skan, konwersja, tłumaczenia — bez zmian).
- WPŁYW: tylko tekst linii PRZEPAKUJ (podgląd i naprawa) i pasek
  szczegółowy. Decyzje, liczby operacji, treść i nazwy wynikowych zipów,
  indeks — bez zmian. Pamięć: członek nie jest już trzymany w RAM w całości
  przy `_rebuild_zip` (MSU-1 .pcm po setki MB). Testy szukające
  `startswith("PRZEPAKUJ")` dalej działają (prefiks bez zmian).
- WERYFIKACJA: testy (nowy log z powodem i „N z M", postęp wołany w
  `_rebuild_zip`/`repack_zip`/`reindex_archive`, zła suma → brak celu);
  pełny podgląd A/B na kopii indeksu — liczby operacji identyczne.

## [0.6.92] — 2026-09-30

### Pusty plik (0 B) z DAT-u nigdy nie „pasuje" do cudzego pustego pliku
- DZIAŁANIE: TeknoParrot „Shining Force - Cross Exlesia" → „przenieś z
  ToSort\Tom Clancy's Splinter Cell - Chaos Theory (Disc 2).zip".
- ANALIZA: gra ma tylko zaślepkę „Missing in Action" 0 B z sumami PUSTEGO
  pliku (sha1 da39a3ee…, crc 00000000); zip w ToSort ma 0 B (przerwane
  pobranie) — każdy pusty plik ma te sumy. Reguła „pusty ROM = utworzyć
  pusty plik" (MSU-1) działała tylko, gdy DAT NIE podaje sum; przy sumach
  pustego pliku program szukał „tej treści" w całej kolekcji. W DAT-ach usera
  50 337 takich ROM-ów (TeknoParrot 48 684, DSi CDN 1 212, PSP PSN 281,
  Gizmondo 139…). Dwie niespójne reguły: pliki luzem (brak sum) vs archiwa
  (sam rozmiar 0 — także 39 ROM-ów BIOS „System" z PRAWDZIWYMI sumami przy 0 B
  uznawanych za puste po samej nazwie).
- MIEJSCA: `matcher.match_rom`, `_archives_with_game`, `_match_game_archive`.
- ZMIANA: jedna reguła `_is_empty_rom`: rozmiar 0 i sumy puste albo sumy
  PUSTEGO pliku (sha1/md5/crc) → znacznik: jest, gdy leży pusty plik pod
  nazwą z DAT-u, inaczej „do utworzenia"; nigdy nie szukany po sumach.
  Rozmiar 0 z prawdziwymi sumami → zwykłe dopasowanie po treści.
- WPŁYW: puste pliki 0 B w ToSort/kolekcji przestają być „źródłem" dla
  zaślepek (koniec fałszywych przenosin i wypakowań). Tworzenie pustych
  plików i pakowanie pustych wpisów do zipów bez zmian (jak dla MSU-1).
  39 ROM-ów BIOS (0 B, prawdziwe sumy) dopasowywane po treści także w
  archiwach.
- WERYFIKACJA (pełny podgląd A/B na kopii indeksu): operacje — tylko
  TeknoParrot −1 przeniesienie (Splinter Cell Disc 2.zip) i Arcade1TB ports
  −1 kopia pustego pliku; stany ROM-ów 0 B „gdzie indziej" → „do utworzenia"
  (obie „do naprawy") w TeknoParrot 48 684, PSP PSN 281, Evercade 6, Steam 5,
  DSi 4, ports 1; reszta DAT-ów identycznie.

## [0.6.91] — 2026-09-30

### Sonda CHD: jedna treść = jeden odczyt (hardlinki bez NAS)
- DZIAŁANIE: pierwszy skan na 0.6.90 czyta nagłówki >15 000 CHD, a nie
  ~5734 unikalnych (zapowiedziane).
- ANALIZA: `deep_probe_chds` przejmuje wiedzę od bliźniaków TYLKO na starcie
  (`fill_from_twins`) — przy pierwszym uruchomieniu żaden bliźniak nie ma
  jeszcze `chd_sha1`, więc każdy hardlink szedł do `chdman info` osobno.
  To samo dotyczy głębokiej identyfikacji (ekstrakcja) CHD bez odcisku.
  Symulacja przed 0.6.90 grupowała po treści sama — nie sprawdzała drogi
  programu.
- MIEJSCA: jedno — `matcher.deep_probe_chds` (kandydaci + koniec funkcji).
- ZMIANA: kandydaci grupowani po treści (suma pliku + rozmiar): do nagłówka
  i do ekstrakcji idzie JEDEN plik z grupy; po sondzie `fill_from_twins`
  przenosi wyniki (chd_sha1, data_sha1, kontener, porażka) na pozostałe.
- WPŁYW: tylko liczba odczytów/ekstrakcji w sondzie (15 269 → ~5734 przy
  pierwszym skanie; później tylko nowe pliki). Wyniki w indeksie identyczne
  (ta sama treść = ten sam nagłówek). Podgląd/naprawa/dopasowanie bez zmian.

### „Przerwij" w etapie 2 zatrzymuje też finał
- DZIAŁANIE: naprawa 30.09 03:29 — „Przerwij" o 14:50, zapis „PRZERWANO
  naprawę na katalogu 42/608" o 15:18, a mimo to do 16:13 kasowanie starych
  kopii w No-intro (finał), aż do drugiego przerwania.
- ANALIZA: pętla etapu 2 kończy się na `cancel` (zdarzenie przerwania), ale
  kroki finału `finalize_global` i `sweep_orphans` sprawdzały tylko
  `rb.cancelled` (flagę ustawianą w środku DAT-u) — przerwanie MIĘDZY DAT-ami
  jej nie ustawia.
- MIEJSCA: `repair.repair_collection` (finał); pozostałe kroki finału
  (opisy ścieżek, puste katalogi) już sprawdzają `cancel`.
- ZMIANA: po pętli etapu 2 przerwanie przez użytkownika ustawia też
  `rb.cancelled` → cały finał pominięty (jak przy przerwaniu w DAT-cie).
- WPŁYW: tylko zachowanie po „Przerwij" (finał robi następna pełna naprawa,
  jak dotąd przy przerwaniu w DAT-cie). Pełny przebieg bez zmian.

## [0.6.90] — 2026-09-30

### Dyski CHD z DAT-ów (`<disk>`): Arcade1TB, MAME/Naomi, [T-En]
- DZIAŁANIE: nowy katalog DAT-ów Arcade1TB (dir2dat) — gry PSX „nie
  znalezione", choć leżą w ROMS\psx. 84 gry-dyski w Arcade1TB (PS2 28,
  PSX 20, MAME 18, DC 12, Naomi 3, Naomi2 3) + ~700 w 12 DAT-ach [T-En]
  („Mega CD Hacks": „POMIJAM DAT bez gier").
- ANALIZA: parser czyta tylko `<rom>`; `<disk>` pomijany (XML i ClrMamePro).
  Suma dysku = SHA-1 z NAGŁÓWKA CHD (`chdman info` „SHA1"), której indeks nie
  zna (ma sumę pliku i własny odcisk treści gry `data_sha1`).
- MIEJSCA:
  - datfile: parser XML i CMPro → `DatGame.disks` (osobna lista, NIE w
    `roms`: pakowanie zipów, konwersje, profile gier i MAME bez zmian);
    dysk `nodump`/bez sumy albo z `merge` (klon MAME, dysk u rodzica) —
    pominięty; dir2dat: gra „x.zip” = archiwum gry „x” (łączona z grą „x”,
    np. naomi2 `beachspi.zip` + `beachspi\gds-0014.chd` = jedna gra);
  - datcache: `CACHE_VERSION` 3→4 (jednorazowo ponowne wczytanie DAT-ów);
  - fileindex: kolumna `chd_sha1` (+indeks), w `_CONTENT_COLS`/
    `_PROBE_COLS` (hardlinki/kopie/przeniesienia dostają ją od bliźniaka),
    zerowana przy zmianie pliku (`record_file`, nowe sumy), `find_chd_sha1`
    (+cache dopasowania), `set_chd_sha1`;
  - matcher: `match_game` dokłada status każdego dysku (`match_disk`):
    plik o `chd_sha1` = suma dysku; ścieżka: nazwa dysku = nazwa gry →
    `<katalog>\<gra>.chd` (psx/ps2/dc), inna → `<katalog>\<set>\<dysk>.chd`
    (MAME/Naomi); stany jak zwykły plik (jest / zła nazwa / gdzie indziej);
  - matcher.deep_probe_chds: odczyt nagłówka (równolegle, już istniejący
    krok sondy) zapisuje też `chd_sha1`; kandydaci = CHD bez `chd_sha1`;
  - hierarchy: (1) DAT nazwany jak katalog docelowy DAT-u wyżej (psx, ps2,
    dreamcast, naomi…) = ta sama platforma → hardlinki do ROMS (decyzja
    usera); (2) treść DAT-u obejmuje też odciski gier (`data_sha1`) i sumy
    dysków; rebuilder dla dysku podaje hierarchii odcisk treści pliku, bo
    DAT rodzica (bin/cue) nie zna sumy nagłówka — inaczej plik ROMS\psx
    uznany za niczyj zostałby PRZENIESIONY (ping-pong).
- WPŁYW:
  - najbliższy skan: jednorazowy odczyt nagłówków ~5734 unikalnych CHD
    (równolegle, kilka minut; hardlinki bez NAS);
  - start: jednorazowo ponowne wczytanie DAT-ów (nowa wersja cache);
  - nowe gry-dyski w DAT-ach z `<disk>`: liczone w „komplet/brak", układane
    (linki do rodzica tej samej platformy, przeniesienia z ToSort);
  - DAT-y bez `<disk>`: dopasowanie, podgląd, naprawa BEZ zmian (weryfikacja:
    pełny podgląd porównany z poprzednim — różnice tylko w DAT-ach z dyskami);
  - platforma: zmiana tylko dla DAT-ów o nazwie = nazwa katalogu docelowego
    innego DAT-u (Arcade1TB); format przechowywania i skan bez zmian.
- WERYFIKACJA (kopia indeksu usera; nagłówki 5734 CHD odczytane w 7,75 min,
  9535 od bliźniaków): pełny podgląd A (bez dysków) vs B (0.6.90) — różnice
  WYŁĄCZNIE w 7 DAT-ach Arcade1TB: psx +18 linków, ps2 +18 linków (6 kopii
  → linki), dreamcast 7 / gamecube 9 / wii 3 kopie → linki, mame −73 i naomi2
  −2 wypakowania (zip + katalog = jedna gra). Zero przeniesień z ROMS; ~600
  pozostałych DAT-ów identycznie. Test naprawy od końca: hardlink, plik
  ROMS zostaje, druga naprawa bez operacji (test łapie wariant bez poprawki).

## [0.6.89] — 2026-09-30

### Reguły zapisywane tylko po kliknięciu pola DAT-u (regresja 0.6.82)
- DZIAŁANIE: w naprawie okno „nie odpowiada" (REDUMP PS2, 303/2625); w logu
  „DAT Sony - PlayStation 2: włączony" bez klikania. To samo w naprawie
  29.09 19:24 (pierwsza na 0.6.82) — a o 20:57 `_reguly.json` = 0 B.
- ANALIZA: `_on_tree_item_changed` reaguje na KAŻDY `itemChanged` wiersza
  DAT-u (Qt nie mówi, co się zmieniło), nie tylko na pole zaznaczenia.
  „Liczby na żywo" (0.6.82) zmieniają tekst/kolor wiersza przy każdej
  naprawionej grze → za każdym razem zapis `_reguly.json` na NAS w wątku
  okna (zawieszenia; setki zapisów przez Tailscale — przerwany nieatomowy
  zapis wyzerował plik 29.09). Do tego sam handler po zapisie zmienia kolor
  wiersza → wywołuje się drugi raz → drugi zapis przy każdym kliknięciu.
- MIEJSCA (jedyne programowe zmiany drzewa bez osłony `_filling`):
  `_on_live_game` (setText + `_paint_dat_item`), `_on_tree_item_changed`
  (setForeground). Pozostałe zmiany drzewa są w `_fill_dats` (osłonięte).
  Sygnał `itemChanged` drzewa ma jednego odbiorcę.
- ZMIANA (tylko ui/suite_window.py):
  1. `_on_tree_item_changed` zapisuje regułę WYŁĄCZNIE, gdy stan pola
     zaznaczenia DAT-u różni się od zapamiętanego (`_dat_checked`,
     wypełniane w `_fill_dats`); zmiana tekstu/koloru — ignorowana.
  2. `_on_live_game` i zmiana koloru po zapisie w `_on_tree_item_changed`
     pod osłoną `_filling` (jak `_fill_dats`).
- WPŁYW: kliknięcie pola DAT-u — zapis reguły RAZ (dawniej 2×); liczby na
  żywo — bez zapisu reguł i bez zawieszania okna. Podgląd, naprawa, skan,
  indeks, rdzeń (core/) — bez zmian.

### Audyt prawdziwej naprawy: okno nie zamarza, każda długa pętla ma postęp
- DZIAŁANIE: przegląd wszystkich faz `repair_collection` w trybie realnym
  (podgląd ich nie wykonuje) przed kolejnym uruchomieniem naprawy.
- ANALIZA / MIEJSCA:
  1. po etapie 1 okno (wątek GUI) wczytywało zapisany stan wszystkich DAT-ów
     z dysku (`load_report_states`: 3,8 s na danych usera, 668 plików) i
     przebudowywało drzewo — Windows po ~5 s oznacza okno „nie odpowiada"
     (`_on_live_reload` w ui/suite_window.py, wołane z repair.py);
  2. `rebuilder.sweep_orphans` (finał: 7055 starych kopii w No-intro,
     ~3 rundy NAS na plik) zgłaszał postęp tylko raz na KATALOG — katalog PS2
     (2053 pliki) = minuty bez ruchu paska, jak zawieszenie.
  Pozostałe fazy sprawdzone bez zmian: sprzątanie ToSort (postęp co 100),
  `_clean_dir` (postęp per plik), `prune_empty_trees` (równolegle, co 50),
  odbudowa CHD i konwersje (paski per plik), zapis stanu (wątek naprawy).
- ZMIANA:
  1. `datcache.states_from_reports(reports)` — ten sam format co
     `load_report_states` (wspólna konwersja `_expand`); naprawa liczy go W
     SWOIM wątku i przekazuje `on_reload(states)`; okno tylko podstawia dane
     (`_saved_states.update`) i przerysowuje drzewo — bez czytania dysku.
  2. `sweep_orphans`: postęp z nazwą pliku co 25 plików.
- WPŁYW: tylko wyświetlanie; liczby po etapie 1 z tych samych danych, które
  właśnie zapisano na dysk (identyczne). Operacje naprawy, podgląd, skan,
  indeks — bez zmian. Stan DAT-ów wyłączonych w oknie zostaje (update, nie
  podmiana).

### Kopia `.bak` plików konfiguracyjnych też atomowa
- DZIAŁANIE: po zamknięciu programu w trakcie zapisu reguł (30.09 03:06)
  `_reguly.json` cały (atomowy zapis zadziałał), ale `_reguly.json.bak` =
  0 B i został `_reguly.json.tmp`.
- ANALIZA: `atomic_write_text` robił kopię `.bak` przez `shutil.copy2`
  prosto do `.bak` (czyści plik, potem pisze) — przerwanie = pusta kopia,
  czyli brak ratunku przy następnej awarii pliku głównego.
- MIEJSCA: jedno — `fileops.atomic_write_text` (używają go wszystkie zapisy
  konfiguracji; zmiana dotyczy tylko sposobu robienia `.bak`).
- ZMIANA: kopia do `<plik>.bak.tmp` + fsync + `os.replace` → `.bak`; pusta
  albo nieczytelna kopia NIE nadpisuje dobrej `.bak`.
- WPŁYW: treść zapisywanych plików i ich odczyt bez zmian; `.bak` zawsze
  pełna (albo poprzednia pełna). Podgląd/naprawa/skan — bez zmian.

## [0.6.88] — 2026-09-30

### Naprawa nie pyta NAS o każdą grę, która już jest na miejscu
- Etap 1 stawał na REDUMP GameCube („80 s bez postępu" w `is_link`): dla
  każdej gry „jest" u dziecka (hardlink do rodzica) naprawa sprawdzała na
  dysku, czy to link do przepięcia — 2 szeregowe rundy SMB przez Tailscale na
  grę. REGRESJA z 0.6.85: klucz gry CHD = treść (zamiast ścieżki) sprawił, że
  dzieci CHD (REDUMP/1G1R: PS1, PS2, 3DO, Saturn, DC) weszły w to sprawdzenie;
  REDUMP GameCube/Wii (hardlinki od 29.09) — też.
- `_link_or_absent` w naprawie: najpierw indeks — plik znany jako zwykły
  (albo hardlink) = nic do przepinania, bez NAS. Dysk tylko, gdy indeks nie
  wie albo zna link. Podgląd bez zmian (liczby jak w 0.6.87).

## [0.6.87] — 2026-09-29

### Podgląd pokazuje odbudowę złych CHD
- „Znajdź naprawy" pokazywał 0 CHD do odbudowy, choć indeks znał 503 złe
  kontenery PS2 (ROMS\ps2): podgląd rozstrzygał tylko z zapisanego typu
  nagłówka (CD/DVD), a u nich go nie było („574 bez zapisanego nagłówka").
  Zły kontener stwierdzony sondą CHD (`bad_container=1`) jest teraz
  werdyktem. Na indeksie usera: PS2 0 → 500 do odbudowy.
- Bez linii „Odbudowa CHD: 0 plików" dla DAT-ów bez żadnego CHD (608 linii
  szumu w podglądzie).
- Jeden plik = jedna odbudowa na cały przebieg: zły CHD w ToSort widzi każdy
  DAT tej platformy (ROMS/REDUMP/1G1R) — w podglądzie był po 2–3 razy (699
  linii dla 569 plików). Wspólny zbiór `seen` przebiegu naprawy.
- Porównanie pełnego podglądu z logiem 0.6.86: jedyna różnica = +569
  „ODBUDOWA CD→DVD" (500 ROMS\ps2 + 69 ToSort), reszta kategorii identyczna.
- Po „Aktualizuj z nowszej wersji" program nie każe skanować — indeks jest
  już zaktualizowany, wystarczy „Znajdź naprawy".
- Uzupełnienie brakującego wpisu: od 0.6.71 (24.09) podgląd nie czyta
  nagłówków CHD z NAS — przez to złe kontenery bez zapisanego nagłówka
  znikały z podglądu (prawdziwa naprawa odbudowywała je normalnie).

## [0.6.86] — 2026-09-29

### Podgląd: każda operacja raz
- „Znajdź naprawy" nie zmienia dysku ani indeksu, więc etap 2 i kolejne
  DAT-y widziały stan sprzed operacji już zaplanowanych: 134 × POPRAW LINK
  (etap 1 i znowu etap 2) i 37 × KASUJ z ToSort (dwa DAT-y) — zawyżone liczby.
- Wspólny stan podglądu: `_dry_linked` (ścieżka po naprawie będzie linkiem)
  i `_plan_delete` (kasowanie planowane raz) we wszystkich miejscach
  planowania linków i kasowania. Realna naprawa bez zmian.
- Poprawione przy okazji: zaplanowane już kasowanie „sieroty" nie może spaść
  do gałęzi „przenieś do ToSort".

## [0.6.85] — 2026-09-29

### Dziecko linkuje do rodzica także przy zipach i naprawach w miejscu
- Podgląd planował 598 FIZYCZNYCH kopii No-intro → 1G1R (ZX Spectrum,
  NeoGeo Pocket, Supervision, Zeebo, V.Smile…) zamiast hardlinków. Wspólna
  przyczyna (metoda, nie platformy):
  - `_whole_file` uznawał każdą grę-archiwum za „nie cały plik" (bo ma
    `member` = nazwa ROM-u w środku) → reguła „plik DAT-u wyżej = link" nie
    działała dla ŻADNEGO zipa;
  - naprawa w miejscu (przepakowanie złej metody ZIP) nie zgłaszała pliku
    rodzica jako kopii fizycznej → dziecko nie wiedziało, do czego linkować;
  - klucz gry-archiwum/CHD zawierał ŚCIEŻKĘ źródła, więc dziecko z własnym
    plikiem nie rozpoznawało tej samej gry u rodzica. Teraz klucz = treść
    gry (sumy ROM-ów; dla archiwum także nazwy w środku).
- Podmiana pliku W MIEJSCU (przepakowanie ZIP, odbudowa CHD CD→DVD) tworzy
  nowy plik na dysku — jego dawne hardlinki zostawały ze starą treścią i
  każdy był potem przerabiany osobno (druga kopia + ponowne pobieranie przez
  NAS). Jedna para funkcji `hardlink_twins`/`relink_twins` we WSZYSTKICH
  miejscach podmiany: hardlinki są przepinane na nowy plik, odbudowa CHD
  pomija cele będące hardlinkami innych celów. Flagi problemów pliku
  sprawdzane z indeksu w chwili wykonania (`_still_flagged`).
- Dowód: odtworzenie ZX na kopii indeksu usera — przed: 127 kopii, po:
  127 linków, 0 kopii, przepakowanie tylko plików rodzica.

### Reguły: zapis atomowy i STOP przy nieczytelnym pliku
- `_reguly.json` wyzerowany (0 B) przez przerwany zapis na NAS → program
  po cichu liczył na domyślnych regułach (inne katalogi docelowe, 4551 plików
  „bez DAT-a" do ToSort, przenosiny całych katalogów).
- Wszystkie pliki konfiguracyjne (reguły, kolejność, priorytety, ustawienia,
  tłumaczenia, manifest BIOS, wersje) przez jedno `atomic_write_text`:
  plik tymczasowy + fsync + atomowa podmiana, poprzednia wersja jako `.bak`.
- Nieczytelne reguły: odczyt z `.bak`; bez niej naprawa, podgląd i skan
  ZATRZYMUJĄ się z komunikatem (bezpiecznik). Zapis reguły nie nadpisuje
  nieczytelnego pliku.

### Bez zbędnych skanów
- Po zmianie ustawień DAT-u/katalogu program radził „Skanuj i raportuj" —
  wystarczy „Znajdź naprawy" (dopasowanie z indeksu). Skan tylko przy
  włączeniu nigdy nie skanowanej platformy.
- Sonda CHD nie pyta NAS o istnienie każdego katalogu (~430 rund).

### Sprzątanie
- Usunięte martwe `repack_incompatible_zips` (bez wywołań) i nieużywane
  importy; logika atomowej zamiany na hardlink w jednym miejscu
  (`replace_with_hardlink`).

## [0.6.84] — 2026-09-29

### Skan: katalogi listowane równolegle
- Obchód katalogów był szeregowy: każdy `scandir` na NAS to runda sieciowa
  (~68 ms na katalog przez Tailscale), a kolekcja ma tysiące katalogów gier
  (bin/cue, ToSort) — minuty samego czekania, nawet gdy nic się nie zmieniło.
- Teraz katalogi listowane naraz wg nośnika: NAS 16, SSD 8, HDD szeregowo
  (bez skakania głowicy). Pomiar na NAS usera (na zimno): 68 ms → ~6 ms na
  katalog (ToSort\other: 146 katalogów w 0,9 s).
- Te same zasady co dotąd: pomijanie katalogów już przeskanowanych,
  plików tymczasowych, czekanie na powrót NAS po zaniku sieci.

### Wiedza o CHD: jedno źródło dla wszystkich faz (koniec łatania per miejsce)
- 0.6.83 poprawiło tylko skan; faza sondy CHD po skanie (`deep_probe_chds`)
  nadal pytała chdman o 2942 hardlinki REDUMP (PS1, 3DO, Saturn, Dreamcast),
  plus szeregowe `is_file()` na NAS per plik („20 s bez postępu”).
- Teraz jedna metoda `FileIndex.fill_from_twins()`: jednym przebiegiem po
  indeksie (0,4 s, bez NAS) każdy CHD dostaje od bliźniaków (hardlink/kopia,
  ta sama suma) wszystko, co one wiedzą. Wołana przed sondą CHD oraz na starcie
  naprawy i „Znajdź naprawy”. Na indeksie usera: 11 107 wpisów uzupełnionych,
  do chdman zostaje 0 (skan i sonda).
- Skan ma jedną drogę do wiedzy o CHD (`_know_chd`, plik nowy i znany):
  bliźniak, a chdman tylko dla tego, co nadal nieznane. Usunięte dwie osobne
  kopie tej logiki; sonda bez `is_file()` per plik.
- Sprzątanie: reguła „komplet / do naprawy / brak” w jednym miejscu
  (`matcher.game_category`, dotąd 3 kopie), indeks gra→statusy w jednym
  (rebuilder, dotąd 2 kopie).

## [0.6.83] — 2026-09-29

### Skan nie sonduje hardlinków CHD po NAS
- Hardlinki CHD z naprawy dostawały w indeksie sumy, ale NIE wynik sondy CHD
  (układ ścieżek, typ CD/DVD, kontener). Skan uznawał je za niezbadane i
  uruchamiał chdman po NAS na każdym, pojedynczo, w głównej pętli — 1344 CHD
  PS1/PS2 w REDUMP, mimo że oryginał każdego z nich miał komplet danych.
- Przyczyna systemowa: każde kopiowanie wpisu z bliźniaka (hardlink z naprawy,
  hardlink wykryty skanem, plik przeniesiony) miało własną, niepełną listę
  kolumn. Teraz jedna wspólna lista „kolumn treści” (`_CONTENT_COLS`).
- Skan, zanim uruchomi chdman, bierze wynik z bliźniaka o tej samej sumie
  całego pliku (także dla nowych plików i kopii zapisanych przez naprawę).
  Na indeksie usera: 988 z 988 oczekujących CHD bez chdman.

## [0.6.82] — 2026-09-29

### Liczby NA ŻYWO w trakcie naprawy (jak RomVault)
- Każda udana operacja (hardlink, przeniesienie, zmiana nazwy, rozpakowanie,
  konwersja, odbudowa CHD) od razu przestawia stan TEJ gry na „jest", a drzewo
  DAT-ów przelicza liczby i kolor tylko tego DAT-u. Żadnego dopasowania ani
  przeliczania — liczba jest wypadkową skanu i wykonanych napraw.
- Hardlinki równoległe zgłaszają grę dopiero po faktycznym utworzeniu linku;
  podgląd („Znajdź naprawy") niczego nie przestawia.
- Po etapie 1 okno wczytuje zapisany stan wszystkich DAT-ów (przepis etapu 2).
- Indeks gra→statusy per raport: przestawienie gry nie przegląda całego DAT-u.

## [0.6.81] — 2026-09-28

### Program pamięta, co naprawił (bez skanu i bez „Znajdź naprawy")
- Liczby „komplet / do naprawy / brak" po starcie pochodziły z zapamiętanego
  wyniku OSTATNIEGO „Skanuj i raportuj". Naprawa aktualizowała indeks po każdej
  operacji, ale nigdy tego wyniku — po przerwaniu i restarcie znów było
  „ponad 800 PS2 do naprawy", choć indeks wiedział już o 572.
- Po naprawie (zakończonej, PRZERWANEJ) stan jest przeliczany z INDEKSU —
  bez skanu plików (PS2 na kopii indeksu usera: 2,5 s, 572 = wynik skanu)
  — pokazany i zapamiętany. Dotąd: po przerwaniu komunikat „zrób skan",
  po zakończeniu pełne „Skanuj i raportuj" po NAS.
- Podsumowanie zapisywane NA BIEŻĄCO w naprawie: po etapie 1 (przepis etapu 2
  i tak jest liczony — zapis darmowy) i po każdym DAT-cie etapu 2 (tylko ten
  DAT, z indeksu, bez NAS). Start programu NICZEGO nie przelicza (natychmiast),
  po naprawie okno tylko wczytuje zapisane liczby (zamiast ~50 s przeliczania
  całej kolekcji). Dopasowanie nie pyta NAS o symlinki bez zapisanego celu.
- „Znajdź naprawy" też odświeża liczby (podgląd liczy stan z indeksu, więc
  jego wynik to aktualny stan kolekcji).

### Jeden format DAT-u w całym programie (koniec zbędnych przepakowań)
- Format „per platforma" (DAT-dziecko dziedziczy jawny format rodzica) trafiał
  do `entry.store_format`, którego używa matcher i rebuilder, ale konwersja
  liczyła format OD NOWA z reguły samego DAT-u. PSP PSN (Decrypted) z „auto" →
  zip, platforma PSP → CHD: matcher planował wypakowanie, konwersja
  przepakowanie zipa — 130 zipów z ToSort z DOKŁADNIE właściwą zawartością
  miało być pobranych z NAS, przepakowanych i wysłanych z powrotem.
  Teraz `dirrules.effective_format` = jedno źródło formatu.
- Podgląd całej kolekcji (kopia indeksu): DAT-y-dzieci dostają HARDLINKI do
  plików rodzica (68 269; PS2: No-intro ISO→`ROMS\ps2\<gra>.chd`), żadna
  konwersja nie bierze źródła z kolekcji. Hardlink na Z: (SMB) sprawdzony.

### Naprawa w dwóch etapach: najpierw szybkie operacje we wszystkich katalogach
- ETAP 1 (wszystkie katalogi): linki (hardlinki dziecko → rodzic),
  przeniesienia i zmiany nazw na tym samym dysku, spłaszczanie, wypakowania;
  potem zbędne archiwa i opisy ścieżek bez torów w ToSort. Gry do konwersji są
  pomijane (lista z podglądu konwersji — z indeksu, bez NAS).
- ETAP 2 (katalog po katalogu): konwersje, odbudowa złych CHD, sprzątanie,
  kasowanie źródeł — na przepisie PRZELICZONYM z indeksu po etapie 1.
- Dawniej wszystko szło katalog po katalogu: przerwanie w ROMS (dni odbudowy
  PS2 przez internet) zostawiało No-intro i 1G1R bez ani jednego linku
  (15 logów napraw — 0 linii „LINK").
- Dziecko linkuje do CHD rodzica odbudowanego W TYM SAMYM przebiegu (stan
  kontenera z aktualnego indeksu, nie z raportu sprzed naprawy).
- Wspólny katalog kilku DAT-ów (ROMS\pc98: „NEC - PC-98" i „NEC - PC-98
  (HardDisk)"): sprzątanie jednego DAT-u zmiatało do ToSort pliki drugiego,
  do których linkowały No-intro i 1G1R (12 zipów PC-98). Etap 1 rejestruje
  wszystkie pliki przed sprzątaniem.

### Skan nie przelicza hardlinków
- Hardlinki z naprawy (przed tą poprawką) trafiały do indeksu z sumami, ale BEZ
  członków archiwum. Skan przy każdym takim zipie (u usera 26 499) otwierał go
  na NAS i hashował zawartość (~0,3–0,4 s/plik), choć log pokazywał „policzono
  0, bez zmian N" — członkowie nie wchodzą w licznik.
- Teraz członkowie są brani z BLIŹNIAKA w indeksie (ta sama suma i rozmiar
  całego pliku = te same bajty), bez otwierania zipa (u usera 24 324 z 26 499).
  Każdy nowy hardlink dostaje członków od razu (`record_hardlink`).
- Nowa ścieżka będąca hardlinkiem znanego pliku (np. po zmianie katalogów
  DAT-ów): sumy i członkowie przejęte po identyfikatorze pliku (os.stat, jedna
  runda SMB) zamiast czytania całego pliku.
- Indeks bazy po (rozmiar, mtime) — szukanie bliźniaka / przeniesionego pliku
  przeglądało całą tabelę przy każdym nowym pliku.
- Członkowie przeżywają zniknięcie pliku-bliźniaka: `remove_path` / nadpisanie
  przy `rename` przekazują członków pozostałym wpisom o tej samej treści, a
  skan pożycza je także z wpisów BRAKUJĄCYCH (missing=1 zachowuje członków).
  Dawniej hardlink, którego cel usunięto, był otwierany na NAS przy skanie
  (u usera 1373 zipy Mega Drive + 134 ColecoVision po błędzie przerzucania).

### W kolekcji wyłącznie hardlinki
- Tworzenie linku na tym samym woluminie przy KAŻDYM błędzie hardlinku (np.
  chwilowa czkawka SMB przy równoległych linkach) po cichu robiło SYMLINK
  (jako administrator się udawał). U usera 1639 symlinków. Teraz na tym samym
  woluminie tylko hardlink; symlink wyłącznie gdy system jawnie nie obsługuje
  hardlinków (inny wolumin, brak funkcji), inaczej błąd jest zgłaszany.
- Na starcie każdej naprawy (równolegle, 16 wątków): zerwany symlink →
  usunięty, symlink z celem na tym samym woluminie → zamieniony na HARDLINK
  (wpis w indeksie z danymi celu, bez pytania NAS).
- Skan zapisuje cel symlinku (link_of), dopasowanie porównuje z indeksem —
  dawniej 3 rundy SMB na grę z symlinkiem („20 s bez postępu" w Znajdź naprawy).

### Niezmiennik „nie zabieraj plików innym DAT-om" — sprawdzony na całej kolekcji
- Skrypt-audytor (niezależny od logiki naprawy): plik, którego treść ma DAT
  jego katalogu, nie może zniknąć (przeniesienie, przepakowanie z kasowaniem,
  ToSort, kasowanie), chyba że to miejsce dostaje link. Log naprawy z 28.09:
  4900 naruszeń w 17 DAT-ach + 8 przeniesień (FDS QD, fbneo). Podgląd obecnym
  kodem na kopii indeksu usera (603 DAT-y): 0 naruszeń.
- Poprawione KLASY błędów (nie platformy):
  - DAT-y z samymi CRC (FinalBurn Neo, MAME) nie były uznawane za właściciela
    treści (sprawdzany był tylko SHA-1) → inne DAT-y przepakowywały ich zipy
    z kasowaniem źródła. `Hierarchy._has_content`: SHA-1 ALBO CRC+rozmiar.
  - Podgląd nie pokazywał linku w miejscu, z którego plik zabrał DAT wyżej
    (plik „wciąż leżał" w podglądzie). Teraz podgląd = to, co zrobi naprawa.
  - Sprzątanie sierot (katalog bez DAT-u, np. stary No-intro po przeniesieniu
    DAT-ów płyt do Redump) wynosiło do ToSort pliki, których treść leży już w
    kolekcji (7052 hardlinki). Teraz ta sama reguła co w katalogu DAT-u:
    zbędna kopia/nazwa jest usuwana (przy kasowaniu ułożonych kopii z ToSort).
- Log przepakowania mówi wprost o losie źródła: „[źródło zostaje: …]" albo
  „[źródło zostanie skasowane]".

### Koniec przerzucania plików między DAT-ami różnych platform
- Te same ROM-y w DAT-ach RÓŻNYCH platform pod inną nazwą gry („Microsoft -
  MSX": „10-Yard Fight (Japan)", „FinalBurn Neo - MSX 1 Games": „10yard"):
  naprawa brała zip jednego DAT-u, przepakowywała go pod nazwę drugiego i
  KASOWAŁA źródło; następna naprawa robiła to samo w drugą stronę — te same
  tysiące PRZEPAKUJ przy każdej naprawie, choć nic się nie zmieniło.
- Teraz plik należący do innego DAT-u, który po jego zabraniu nie dostałby
  linku (inna platforma), zostaje u właściciela; ten DAT dostaje własną kopię
  (`Hierarchy.must_keep_source`). Przeniesienie z DAT-u tej samej platformy
  NIŻEJ (1G1R → ROMS) dalej jest przeniesieniem + linkiem.
- Kopia archiwum z INNYMI nazwami wewnętrznymi jest przepakowywana (dawniej
  kopiowana 1:1 — ze złymi nazwami, więc „do naprawy" w nieskończoność).

### Linki kilka razy szybciej (etap 1 z ~10 h do ~1,5 h)
- Log naprawy usera: 62 133 linki × 0,6 s = 10,4 h, przeniesienia 10 300 ×
  0,8 s = 2,3 h. Link robił SZEREGOWO lexists, mkdir (×2), os.link, lstat ×2
  i dwa commity indeksu — przy 33 ms do NAS każde to runda SMB.
- Teraz: sam os.link w puli 16 wątków (zajęta ścieżka / „już zlinkowane"
  rozstrzyga FileExistsError + same_file), katalog tworzony RAZ na przebieg,
  wpis indeksu z danymi celu bez pytania NAS (`record_hardlink`), commit co
  500 linków. Pomiar na NAS: 0,54 → 0,08 s/link (serwer i tak szereguje
  linki w obrębie jednego katalogu — sam os.link szeregowo to 0,13 s).
- Przeniesienia: bez drugiego mkdir w `move_with_progress` (wołający już
  zapewnił katalog).

### Licznik złych kontenerów CHD = liczba PLIKÓW
- Podsumowanie liczyło ten sam CHD osobno w każdym DAT-cie, który na niego
  wskazuje (ROMS, No-intro, 1G1R): 1162 zamiast 572 realnych plików PS2
  (503 w ROMS\ps2 + 69 w ToSort).

### Fizyczna kopia w najwyższym DAT-cie, który MA grę
- Plik leżący w katalogu DAT-u wyżej był uznawany za kopię „rodzica" po samym
  POŁOŻENIU — nawet gdy żaden DAT tamtego katalogu tej gry nie ma. Dziecko
  (No-intro) linkowało do niego, a sprzątanie rodzica kasowało jego nazwę
  (hardlink ratował dane; symlink — inny dysk — zostałby linkiem donikąd).
- Teraz link tylko wtedy, gdy któryś DAT katalogu wyżej zawiera tę treść
  (`Hierarchy.owned_above`, po SHA-1/CRC). Inaczej plik PRZENOSI się fizycznie
  do najwyższego DAT-u z tą grą, a niższe linkują do niego.

### Sprzątanie ToSort i pustych katalogów
- Opisy ścieżek (`.cue`/`.gdi`/`.toc`) w ToSort bez żadnego toru obok są
  kasowane — m.in. cue zostawiony po konwersji na CHD (cue ze zrzutu bywa
  bajtowo inny niż w DAT-cie, więc nie schodził razem z torami). U usera: 329
  takich plików (CD32 176, Dreamcast 93, Saturn 60), gier nie ma nigdzie.
- Na koniec naprawy: puste katalogi w ToSort i POD katalogami DAT-ów
  (równoległy obchód NAS; katalogi docelowe DAT-ów i korzenie zostają).
  Dotąd sprzątane były tylko katalogi opuszczone w tym przebiegu.

### „auto" dla Xbox, Xbox 360 i PS3 = ISO (bez CHD i zipa)
- Xenia, Xemu i RPCS3 nie czytają CHD ani obrazu z zipa. „auto" dawało
  Xbox/X360 zip (7 GB ISO do zipa), a PS3 CHD. Teraz „auto" = keep (ISO jak
  jest); zip tylko z jawnej reguły „archiwum". Podpowiedź formatu tak samo.

## [0.6.80] — 2026-09-27

### Gry jednoplikowe (CHD/RVZ/ISO) płasko, bez podfolderów
- Gra z JEDNYM plikiem w podfolderze nazwanym jak gra (`<gra>\<gra>.rvz`,
  układ z paczek RomVault) nie jest już akceptowana jako „na miejscu" — dostaje
  „zła nazwa", a Napraw przenosi ją płasko (`<gra>.rvz`) ZMIANĄ NAZWY na tym
  samym dysku (bez przesyłania danych, indeks bez ponownego liczenia sum)
  i kasuje pusty folder. Podfolder zostaje tylko dla gier wieloplikowych
  (bin/cue, gdi — reguła `subdir_per_game`). U usera: 610 RVZ GameCube +
  1266 Wii (podgląd na kopii indeksu: 1876 × NAZWA, 0 do ToSort, 0 błędów).
- Plik, którego przeniesienie się nie udało (albo w podglądzie), jest chroniony
  pod starą ścieżką — sprzątanie nie zmiecie poprawnej gry do ToSort (podgląd
  pokazywał każdy spłaszczany plik 2×: NAZWA + TOSORT).
- Dziecko w hierarchii (np. No-intro) linkuje do NOWEJ ścieżki rodzica, gdy
  rodzic w tym samym przebiegu przeniósł plik — wcześniej celowało w starą
  ścieżkę ze skanu, której już nie ma (link się nie tworzył).

### Konwersja nie rusza DAT-ów już w formacie docelowym
- DAT „surowy" (NKit RVZ: ROM-y to pliki `.rvz` z własną sumą) — konwersja
  ze źródła pomija takie gry. Wcześniej każda gra GameCube/Wii spoza ścieżki
  kanonicznej (np. kopia dla No-intro) była pobierana z NAS na RAM (~1,4 GB)
  tylko po to, by skończyć „brak iso — pomijam" (RVZ→RVZ dałby i tak inne
  bajty niż w DAT-cie). Umieszczenie/link robi rebuilder.

## [0.6.79] — 2026-09-25

### Wysyłka na NAS znów jednym strumieniem (regresja 0.6.78)
- 0.6.78 wysyłała równolegle (8 zapisów w różne miejsca pliku): na NAS przez
  internet ~0,1 MB/s wobec 5,4 MB/s zwykłego zapisu (pomiar) — NTFS po drugiej
  stronie dopełnia zerami wszystko przed miejscem zapisu. Równolegle zostaje
  tylko POBIERANIE (tam 8 odczytów naraz dawało do 21 MB/s).

### Szybsza wysyłka: robocopy (fallback: Python, blok 64 MB)
- Pomiar wysyłki 256 MB na NAS (Tailscale): robocopy 12–13 MB/s, Python
  1 strumień blok 64 MB ~11 MB/s, blok 8 MB (dotąd) ~8 MB/s, CopyFile2
  6,4 MB/s, zapisy równoległe 6–7 MB/s, rezerwacja rozmiaru przed zapisem —
  patologicznie wolno (serwer dopełnia zerami).
- Pliki ≥ 32 MB wysyłane przez robocopy (hardlink źródła pod nazwą tmp
  w prywatnym katalogu na RAM-dysku → robocopy → os.replace w celu), postęp
  z procentów robocopy, bez okna konsoli, /R:2 /W:5. Błąd robocopy →
  ta sama wysyłka w Pythonie blokami 64 MB. Źródło kasowane dopiero po
  udanej wysyłce, jak dotąd.

### Przebudowa CHD nie kasuje oryginału przed wysyłką
- `_place_final` kasował stary CHD na NAS PRZED wysyłką nowego — przez całą
  (przez internet — nawet godzinną) wysyłkę jedyna kopia gry leżała na ulotnym
  RAM-dysku. Teraz nowy plik idzie obok jako `*.chdbuddy_move_tmp` i dopiero
  kompletny zastępuje stary (atomowe os.replace). Przerwanie wysyłki = stary
  plik nietknięty.

## [0.6.78] — 2026-09-25

### Kopiowanie z/na NAS równolegle (8 odczytów/zapisów naraz)
- Pobieranie i wysyłka szły JEDNYM strumieniem blok po bloku — przez internet
  (Tailscale, 33 ms na rundę) każdy blok czekał osobno. Pomiar na Z: w czasie
  trwającej naprawy: jeden strumień 2,2–2,8 MB/s, CopyFile2 (jak Eksplorator)
  1,4–1,9 MB/s, 8 odczytów naraz do 21 MB/s (Total Commander ~30 MB/s).
- `fileops.copy_parallel`: 8 wątków, każdy na własnym uchwycie i kawałku pliku,
  kontrola rozmiaru, pierwszy błąd przerywa całość (nic niepełnego nie zostaje
  jako „udane"). Użyte przy: pobieraniu CHD w przebudowie, pobieraniu luźnych
  plików w konwersji ze źródła, wysyłce gotowych plików na NAS.

### Przebudowa CHD: etap pobierania tylko KOPIUJE
- Rozpakowanie (`extractcd`, jednowątkowe, ~1–1,5 min na grę PS2), deframe i
  sprawdzenie SHA-1 przeniesione do etapu przeróbki — następne pobranie rusza
  zaraz po skopiowaniu, łącze nie czeka na rozpakowanie. Wątki chdman liczone
  tuż przed samą kompresją.

## [0.6.77] — 2026-09-24

### Przebudowa/konwersja CHD „na zakładkę" (jedno pobranie naraz)
- Zamiast 3 pobrań naraz (0.6.74–0.6.76, dzieliły łącze): pobiera się JEDEN
  plik; gdy skończy i zaczyna się przerabiać, rusza pobieranie następnego;
  przerobiony idzie do wysyłki, a w tym czasie kolejne się przerabiają.
- Ustawienie `download_workers` (domyślnie 1) zastępuje `gather_workers` —
  stara wartość 3 zapisana w pliku ustawień jest ignorowana (bez edycji pliku).
- Zostają: budżet RAM rezerwowany przy starcie pobierania, kopia CHD na RAM
  przed ekstrakcją, osobne paski pobierania/przeróbki.

### Kompresja CHD na 1–2 wątkach (CPU 8%)
- Wątki chdman były dzielone Z GÓRY „na 4 równoległe" (przebudowa: 8/4 = 2;
  konwersja ze źródła: sztywno 1). Przy jednym pobraniu naraz przez wolne łącze
  kompresja idzie zwykle SAMA → 1–2 wątki, reszta procesora stoi.
- Teraz wątki liczone w CHWILI startu kompresji: pula (8) / ile kompresji
  faktycznie trwa. Sama gra → 8 wątków, dwie → po 4. W logu linia
  „kompresja: N wątków chdman (trwa K kompresji naraz)".
- Rozpakowanie (`extractcd`) i weryfikacja (`verify`) w chdman 0.288 NIE mają
  `-np` — zawsze jeden wątek na plik; tego nie przyspieszy żadne ustawienie.

## [0.6.76] — 2026-09-24

### Regresja: zip gry już na CHD nie był sprzątany z ToSort (Lunar)
- Skrót „gra już na ZWERYFIKOWANYM CHD" (wznawianie naprawy) robił `continue`
  PRZED gałęzią HAVE_CHD — omijał sprzątanie jej źródeł w ToSort i rejestrację
  CHD jako rodzica (keeper) dla linków dzieci. Teraz skrót robi jedno i drugie.
- Opcja „buduj tylko kompletne" (i reguła katalogu) trafia do konwersji: gra,
  której brakuje toru DANYCH (nie ma go nigdzie), nie chroni torów w ToSort
  (Lunar (RE) — 50/52 torów oryginału — blokował zip oryginału). Przy
  dozwolonych niekompletnych ochrona zostaje jak była.
- Podgląd („Znajdź naprawy") POKAZUJE „(podgląd) KASUJ z ToSort … (gra już na
  CHD)" — dawniej ta część działała tylko przy prawdziwej naprawie.
- Testy: kasowanie przy „tylko kompletne", zostawienie przy niekompletnych,
  widoczność w podglądzie.

### GUI: „symlinki" → „hardlinki"
- Od 0.6.50 program tworzy HARDLINKI (ten sam wolumin, także NAS Z:), symlink
  tylko awaryjnie. Etykiety i podpowiedzi („kopie potwierdzonych → hardlinki",
  „twórz hardlinki dla DAT-ów dzieci", okna ustawień DAT i hierarchii)
  poprawione; komunikaty o adminie/UAC zostają (dotyczą symlinków).

## [0.6.75] — 2026-09-24

### Okno „nie odpowiada" na 0,5–2 s co kilkanaście sekund
- Przyczyna (pomiar bez GUI: czujnik GIL + gc.callbacks): PEŁNE sprzątanie
  pamięci Pythona (GC pokolenia 2) przy 2,5–8 mln obiektów w pamięci (DAT-y,
  cache indeksu, raporty) — 0,5–1,7 s, w tym czasie stoją WSZYSTKIE wątki.
- `core/gcpause.py`: po zbudowaniu dużych struktur `gc.freeze()` (po każdym
  DAT-cie, po cache indeksu, po każdym DAT-cie dopasowania; na czas operacji);
  na końcu operacji odmrożenie i JEDNO zebranie. Podgląd: zatrzymania okna
  6,9 s → 0,2 s łącznie, najdłuższe 1745 → 243 ms.
- Log w oknie dopisywany PACZKĄ co 100 ms (jedno dopisanie + jeden zapis pliku)
  zamiast każdej linii osobno — podgląd wypisuje do 23 tys. linii/min.

### Wii: minuty ciszy w „puste katalogi" (`_prune_empty_dirs`)
- Sprzątanie pustych katalogów przeglądało CAŁE drzewo (os.walk) i robiło
  `rmdir` na każdym podkatalogu — Wii: 1266 katalogów gier, przez internet same
  rundy SMB (~17 KB/s ruchu, 200+ s). Teraz tylko katalogi, z których w tym
  przebiegu coś zniknęło (indeks notuje je przy remove_path/rename) + rodzice.

### Lunar - The Silver Star (USA) (RE) budowany na darmo w każdej naprawie
- „CHD z archiwum" ruszał, gdy archiwum miało NAJWIĘKSZY tor gry — także dla
  INNEJ płyty dzielącej tory (RE ma 50 z 52 torów oryginału): pobranie 430 MB,
  createcd, weryfikacja i ODRZUCENIE przez strażnika treści. Teraz wymagany
  KOMPLET torów danych gry w tym archiwum (sprawdzenie z indeksu, bez I/O).

## [0.6.74] — 2026-09-24

### Potok konwersji/odbudowy: mniej czekania na NAS (Z: przez Tailscale, 33 ms)
Analiza żywej odbudowy PS2 (CD→DVD): w 20 min 2 gry, 4 wątki kompresji
głównie CZEKAŁY — wąskim gardłem było POBIERANIE (99–412 s/grę, jeden wątek),
nie chdman. Z: jest podpięty adresem Tailscale (100.85.254.31), ruch idzie przez
internet (~10 MB/s).
- **Kilka pobierań naraz** (`gather_workers`, domyślnie 3) w potoku konwersji i
  odbudowy CHD. W trybie z zachowaną kolejnością nadal 1 (bez zakleszczeń).
- **Budżet RAM rezerwowany przy STARCIE pobierania**, nie przy zleceniu — gry
  czekające w kolejce nie blokują już nowych zleceń (log: 5 min przestoju przy
  pustym RAM). Kolejka zleceń ograniczona liczbą; `drain()`/`wait()` finalizują
  każde gotowe zadanie (głowa kolejki może czekać na budżet).
- **Odbudowa CHD: kopia całego CHD na RAM-dysk przed ekstrakcją** — chdman
  czytający hunk po hunku przez SMB dawał 39 MB/s, lokalnie 101 MB/s (pomiar).
  Kopia i surowy .bin kasowane od razu po użyciu (mniejszy szczyt RAM).
- **SHA-1 obrazu w locie** przy deframingu bin→iso (paczkami ramek zamiast
  ramka po ramce); koniec z `iso.read_bytes()` — cały obraz PS2 w pamięci
  programu (3,2 GB RomHelper w tasklist) w walce o RAM z RAM-dyskiem.
- **Konwersja ze źródła: sumy liczone ze scratchu (RAM) PRZED wysyłką**
  (potok i obie ścieżki seryjne) — koniec ponownego odczytu całego CHD/RVZ z
  NAS po wysyłce (podwójny transfer przez internet). Po wysyłce tylko kontrola
  rozmiaru; niezgodny → źródła zostają do ponowienia.
- **Równoległe pliki na osobnych paskach.** Odbudowa CHD podawała chdmanowi
  callback o złej sygnaturze (`done, total, text` zamiast `pct, msg`) — do paska
  trafiał tekst jako liczba, obsługa w oknie się wywracała i własne paski nigdy
  się nie pokazywały; widać było tylko wspólny pasek, na który pisały
  pobierania i wysyłki WSZYSTKICH gier naraz. Teraz: kompresja każdej gry na
  swoim pasku, każde równoległe pobieranie na swoim (numery za paskami
  kompresji), konwersja ze źródła pokazuje postęp pobierania (dotąd żadnego).
  Okno postępu toleruje zły typ wartości (pasek pulsuje zamiast znikać).

## [0.6.73] — 2026-09-24

### Przepakowania w KAŻDEJ naprawie mimo poprawnych nazw w zipie (pętle)
- **ROM-y-bliźniaki** (DAT arcade: ta sama treść pod różnymi nazwami, np.
  angelkds `epr-11437` = `epr-11445`, alpha1v): dopasowanie brało DOWOLNEGO
  członka o tej sumie → poprawny zip wyglądał na „złe nazwy" → PRZEPAKUJ w
  każdej naprawie. Teraz spośród członków o tej samej treści wybierany jest
  ten o NAZWIE ROM-u.
- **Ukośniki w ścieżkach** (DAT-y Flux: `disk1	rack.raw`, ZIP zawsze
  `disk1/track.raw`): porównanie nazw bez normalizacji separatora → pętla
  przepakowań całych kolekcji Flux (Amiga, FM Towns, PC-88/98, X68000…).
- Audyt całej kolekcji: przepakowania „poprawne nazwy wewn." 6370 → 4903;
  pozostałe to PIERWSZE zbudowanie zestawów FinalBurn Neo (konsole w 1G1R) z
  zipów No-Intro — inne nazwy zestawów/plików, jednorazowo.

### Nieaktualny skład zipa w indeksie („There is no item named … in the archive")
- Konwersja „w miejscu" do ZIP zapisywała w indeksie tylko sam plik, a
  członków zostawiała STARYCH (mario.zip: indeks 15 plików, na dysku 12).
  Teraz archiwum jest indeksowane z członkami (`reindex_archive`).
- Kopia archiwum w naprawie (`_copy_file`) przenosi w indeksie skład źródła.
- SAMONAPRAWA: gdy pobieranie trafi na członka, którego w pliku nie ma, skład
  tego archiwum w indeksie jest odświeżany na końcu konwersji katalogu —
  dotychczasowe nieaktualne wpisy znikną przy najbliższej naprawie.

## [0.6.72] — 2026-09-24

### Skan plików: bez podwójnego obchodu NAS przed skanem
- **„Liczenie plików" usunięte** — przed skanem program obchodził CAŁĄ
  kolekcję na NAS tylko po to, żeby policzyć pliki na mianownik paska, a
  potem skan obchodził te same katalogi drugi raz. Teraz mianownik to liczba
  plików z indeksu (poprzedni skan, jedno zapytanie SQL): „plik X z ~Y";
  skan rusza od razu, katalog po katalogu. Nowe pliki ponad szacunek → pasek
  nieokreślony zamiast >100%.
- **„Ustalam katalogi platform" / „Analizuję rozmiary…"** — istnienie
  katalogów kandydatów (target, Redump, ES × ~600 DAT-ów, dwa razy) sprawdzane
  było `is_dir` na NAS pojedynczo. Teraz JEDEN listing każdego katalogu
  nadrzędnego (kilka) z cache na całe zadanie (`dirrules.DirExists`).
- Te same zmiany w „Pełnym skanie" katalogu i skanie z zakładki Indeks.

### Strażnik ciszy widzi kod okna i działa w exe
- Pisał „(poza kodem programu)": pomijał ramki z `ui/` (a przygotowanie skanu
  żyje w pliku okna) i w exe nie rozpoznawał ścieżek modułów (PyInstaller
  zapisuje je względnie). Teraz pomija tylko główny wątek GUI.

## [0.6.71] — 2026-09-24

### „Zawieszenie" na PlayStation w Znajdź naprawy / Napraw
- **Przyczyna:** krok „Odbudowa CHD" przed PIERWSZĄ linią logu sprawdzał dla
  KAŻDEJ gry z DAT-u, czy `<gra>.chd` istnieje — osobnym zapytaniem do NAS
  (`is_file`), szeregowo. PSX: ~4600 zapytań × ~39 ms = **~3 minuty ciszy**
  (bez paska, bez logu). Przy każdym z ~600 katalogów przeglądał też cały
  ToSort (53 tys. wpisów) w Pythonie.
- **Poprawka:** istnienie CHD z INDEKSU (jedno zapytanie na katalog), CHD w
  ToSort filtrowane w SQL (`identified_chds_under`). PSX: 3 min → **1 s**.
  Samą odbudowę i tak poprzedza odczyt nagłówka pliku.
- **Widoczność:** w przeliczaniu kandydatów pasek pokazuje bieżącą grę i
  licznik („Odbudowa CHD — przeliczam: <gra>", zrobione / wszystkie); dalej,
  jak dotąd, „CHD wg cue: <gra>" przy czytaniu nagłówków.

### Sprzątanie katalogu: bez ciszy na NAS, z nazwą pliku
- W PODGLĄDZIE sprzątanie nie-kanonicznych plików (zły link / do ToSort)
  opiera się wyłącznie na indeksie — wcześniej każdy plik to 2–3 rundy SMB
  (`is_link`, `is_file`, `lexists`), nawet gdy nic się nie ruszało. Realna
  naprawa nadal sprawdza system plików.
- Pasek pokazuje bieżący plik („sprzątanie: <plik>") i licznik; przerwanie
  działa w trakcie.

### MSU-1 (i każda gra w archiwum): luźne kopie nie trafiają do ToSort
- Luźne `.pcm`/`.sfc` obok kanonicznego `<gra>.zip` (ta sama treść co członek
  archiwum) szły do ToSort — sprawdzanie „czy treść jest w kolekcji" patrzyło
  tylko na pliki, nie na zawartość archiwów.
- Teraz: gdy treść leży w kanonicznym pliku ALBO archiwum kolekcji (fizycznym,
  poza ToSort, potwierdzonym na dysku), a włączone jest kasowanie ułożonych
  kopii z ToSort — zbędna kopia jest KASOWANA („KASUJ zbędną kopię … (jest w
  …)"). Bez tej opcji — ToSort jak dotąd.
- Czystka ToSort obejmuje też LUŹNE pliki (nie tylko zip/7z) i członków
  archiwów w kolekcji — usuwa pozostałości MSU-1 z poprzednich napraw.
  Pliki przeniesione do ToSort w bieżącym przebiegu są chronione.
- **Przepakowanie zipa MSU-1 tworzy pusty `.msu`** (0 B, w DAT-cie bez sum)
  zamiast „BŁĄD przepakowania … brak ….msu" — wcześniej KAŻDY zip MSU-1 z
  poprawnymi danymi był odrzucany, a potem sprzątany do ToSort (ActRaiser,
  Aladdin, Axelay…). Braki wykrywane PRZED czytaniem danych (sam katalog zipa)
  — wcześniej błąd wychodził po przepisaniu setek MB z NAS (1–3 min na grę).

### Utrata NAS (uśpienie laptopa, restart routera) — praca czeka i wznawia się sama
- Nowy `core/netguard.py`: gdy dysk sieciowy zniknie, operacja NIE sypie
  błędem — log „⚠ NAS niedostępny … Praca WSTRZYMANA", pasek pokazuje czas
  czekania, a po powrocie („✓ NAS znowu dostępny po m:ss — wznawiam") ta sama
  operacja jest ponawiana. Obejmuje: przenoszenie/kopiowanie/kasowanie w
  naprawie, pobieranie źródeł na RAM i wysyłkę finałów konwersji, odbudowę
  CHD, odczyt plików przy skanie; punkt kontrolny co 20 s między grami.
- **Skan nie gubi plików przy zniknięciu NAS** — nieczytelny katalog nie jest
  już pomijany po cichu (co oznaczało całe drzewo jako „brakujące"); skan
  czeka na powrót, a przerwane czekanie = przerwany skan (nic nie oznaczone).
- System nie usypia się sam (bezczynność) w czasie pracy zadania. Uśpienie po
  zamknięciu pokrywy to ustawienie zasilania Windows — po wybudzeniu praca
  czeka na NAS i rusza dalej.
- Wolumin martwy już na starcie zadania nie wstrzymuje pracy (obserwowane są
  tylko żywe); trwały błąd sieci przy działającym woluminie — kilka prób, potem
  zwykły błąd (nie wieczne czekanie).

### „Czy to się zawiesiło?" — strażnik ciszy i stan NAS w oknie postępu
- Nowy `core/watchdog.py`: gdy przez 20 s nie ma żadnego zdarzenia (log,
  pasek), program SAM loguje, w której funkcji stoi i na jakim pliku/grze
  („⏳ [60 s bez postępu] trwa: …"), potem co minutę. Działa w KAŻDEJ fazie,
  bez łatania pętli po kolei; linie trafiają do pliku logu.
- Okno postępu: „brak nowych zdarzeń od m:ss — trwa ostatnia operacja…" oraz
  sprawdzany w tle stan NAS („NAS odpowiada" / „NAS NIE odpowiada — program
  czeka").

### Formuła naprawy w jednym module (`core/repair.py`)
- Cały przebieg naprawy/podglądu przeniesiony z okna do `repair_collection` —
  GUI tylko go woła. Pozwala puścić podgląd CAŁEJ kolekcji bez GUI (audyt
  cichych miejsc wszystkich platform naraz, testy), zamiast wyłapywać je u
  usera platforma po platformie.

### Planowanie naprawy nie dotyka NAS (Znajdź naprawy: godziny → minuty)
- Pomiar na logu „Znajdź naprawy" (184 min): **107 min to cisza** — pytania do
  NAS o pliki, które indeks już znał. Zasada: po skanie planowanie (podgląd i
  planująca część naprawy) pracuje WYŁĄCZNIE na indeksie; realna naprawa pyta
  dysk tylko o pliki, które faktycznie rusza, tuż przed operacją.
- **Finał „porządki w ToSort" (~50 min ciszy)**: `is_file` na NAS dla KAŻDEGO
  pliku kanonicznego kolekcji, zanim sprawdzono, czy w ogóle jest jakaś kopia.
  Teraz kandydaci najpierw z indeksu; NAS tylko dla realnych kopii i tylko w
  naprawie.
- **Hardlinki znane indeksowi** (nowa kolumna `link_of`): program zapisuje je,
  gdy sam tworzy hardlink albo go wykryje. Podgląd rozpoznaje „już zlinkowane"
  bez `same_file` na NAS (dawniej per kandydat na link — 64 tys. w podglądzie).
- **Nagłówki CHD czyta skan, nie naprawa**: liczba ścieżek CD i typ kontenera
  zapisywane w indeksie z tego samego odczytu co profil zawartości (stare wpisy
  z niepotwierdzonym układem uzupełnia najbliższy skan — raz). Odbudowa CHD w
  podglądzie rozstrzyga z indeksu (dawniej `chdman info` ~6 s na plik PS2);
  nieznane tylko liczy („sprawdzi je naprawa").
- Dopasowanie: pusty ROM (.msu MSU-1) sprawdzany w indeksie, nie `isfile` +
  `getsize` na NAS przy każdej grze MSU-1.
- Wyszukiwanie DAT-ów: jeden obchód katalogów (typ pliku z listingu) zamiast
  `rglob` + `is_file` per DAT; postęp „…szukam DAT-ów / sygnatury" co ~3 s.
- Narzędzie audytu (skrypt deweloperski): podgląd całej kolekcji z emulacją
  dysku z indeksu — każde wywołanie systemu plików na NAS liczone z miejscem w
  kodzie.

### Konwersja: bez ciszy przed PlayStation, skąd → dokąd w logu
- Przed konwersją każda gra z DAT-u była sprawdzana na NAS (`is_file`
  `<gra>.chd`) — pętla szła po GRACH DAT-u (PSX 1G1R: 4574), nie po ~1750
  plikach na dysku, bez paska. Teraz jedno listowanie katalogu + postęp
  „konwersja — sprawdzam: <gra>".
- Każda linia konwersji/odbudowy ma pełne ścieżki: „KONWERSJA→ZIP: <źródło>
  (+N plików)  →  <cel>", „ODBUDOWA CD→DVD: <plik>  →  <plik> (w miejscu)".

## [0.6.70] — 2026-09-24

### Porządki (bez zmiany zachowania)
- **Nowy moduł `core/paths.py`** — jedno miejsce na porównania „czy ścieżka
  leży w katalogu" (`dir_key`, `dir_prefix`, `dir_prefixes`, `is_under`,
  `under_any`). Zastępuje ręcznie sklejane prefiksy w matcherze, rebuilderze,
  konwersji, indeksie i GUI (w tym wzorcu łatwo o błąd z separatorem albo
  wielkością liter). Zapytania SQL indeksu z prefiksem zostały bez zmian.
- **Rebuilder: jedna funkcja kopii fizycznej** (`_copy_file`) zamiast dwóch
  identycznych bloków w `_process`.
- Podgląd PS2 na realnych danych identyczny jak w 0.6.69 (2074 linki do ROMS,
  0 przeniesień). Testy: `tests/test_paths.py`.

## [0.6.69] — 2026-09-24

### Wycofana reguła „rodzic" (parent_priority) — hierarchię wyznacza drzewo
- **Kolejność katalogów (`_kolejnosc.json`) jest jedynym źródłem hierarchii.**
  Reguła „wszystkie DAT-y katalogu = rodzice" dublowała ją, a jej drugą rolę
  (zawsze kopie fizyczne) pełni już `dedup_copies=false`.
- **Jednorazowa, automatyczna migracja `_reguly.json`:** `parent_priority=true`
  → „zawsze kopie fizyczne" (`dedup_copies=false`); katalog-rodzic spoza
  zapisanej kolejności jest do niej dopisywany (zostaje tam, gdzie stał).
  Komunikat migracji trafia do logu po wczytaniu DAT-ów.
- GUI: z menu katalogu zniknęło „⭐ Wszystkie DAT-y tu = rodzice platform";
  w ustawieniach katalogu zamiast „Rola: rodzice" jest „Wymuszenie: zawsze
  kopie fizyczne (bez linków do DAT-ów wyżej)".

### Konwersja ze źródła na tej samej hierarchii co naprawa (krok 2)
- `convert_from_source` pyta `Hierarchy` (ten sam obiekt co rebuilder):
  zniknęły `is_parent`, własny klucz platformy i osobne sprawdzanie
  `dedup_copies`.
- **Dziecko w późniejszym katalogu linkuje do pliku zrobionego przez rodzica
  wcześniej w tej samej naprawie** — mapa gotowych finałów jest wspólna dla
  wszystkich katalogów (dawniej tworzona od nowa per katalog, więc takie linki
  w konwersji praktycznie nie powstawały).
- **Dwie gry jednego DAT-u o identycznej treści = dwie kopie fizyczne**
  (dawniej konwersja linkowała je wewnątrz kolekcji — wbrew regule).
- Testy: `tests/test_convert_hierarchy.py` (dziecko → rodzic między
  katalogami, wymuszenie fizycznych, duplikat w jednej kolekcji, inna
  platforma). Podgląd na realnych danych PS2 / Master System bez zmian
  względem 0.6.68 (2074 / 1030 linków do ROMS, 0 przeniesień).

## [0.6.68] — 2026-09-24

### Jedna reguła dedup: hierarchia DAT-ów (`core/hierarchy.py`)
- **Nowy moduł `Hierarchy`** — jedyne miejsce, które decyduje „kopia fizyczna
  czy link": katalog docelowy DAT-u + kolejność z `sort_entries` + platforma.
  Link tylko DAT niżej → DAT wyżej tej samej platformy; „rodzic" i
  `dedup_copies=false` zawsze fizycznie; różne platformy nigdy się nie linkują.
- **Naprawa (rebuilder) przepięta na hierarchię** — zniknęły równoległe
  mechanizmy: flaga `is_parent`, porównania prefiksów katalogów (`intra`),
  listy `protected` / `coll_prefixes` / `parent_prefixes` w finałowym dedupie
  i łatka 0.6.66. Rezerwacje rozdzielone na dwie role: „gdzie treść już leży"
  (źródło kopii) i „kopia tej platformy" (cel linku).
- **Naprawiony ukryty błąd cross-platform:** dziecko (np. SMS 1G1R) mogło
  linkować do pliku INNEJ platformy o identycznej treści (MSX), bo rezerwacja
  nie znała platformy. Teraz linkuje do rodzica swojej platformy.
- **ToSort nigdy nie dostaje linków** — kopia treści już ułożonej w kolekcji
  jest kasowana („usuń z ToSort pliki już na miejscu"), a nie zamieniana na
  link. Po naprawie w ToSort nie zostaje nic z DAT-ów.
- **Usunięty przycisk „Dedup" z zakładki Indeks i komenda CLI `dedup`** —
  działały po samym SHA-1, bez platform i hierarchii (mogły zlinkować MSX↔SMS
  albo pliki w katalogu-rodzicu). Dedup robi Naprawa. „Pokaż duplikaty" zostaje.
- Podgląd na realnych danych: PS2 — 1092 linki No-intro → ROMS\ps2 i 982 linki
  1G1R → ROMS\ps2 (bezpośrednio do pliku fizycznego), 0 przeniesień z ROMS;
  Master System — 694 + 336 linków do ROMS\mastersystem, 0 przeniesień.

## [0.6.67] — 2026-09-23

### Dedup wg hierarchii DAT-ów (katalog + hierarchia, bez rezerwacji)
- **Kopia fizyczna w katalogu DAT-u stojącego wyżej = oryginał; niższy DAT
  robi do niej link, nigdy jej nie przenosi.** O tym decyduje wyłącznie
  katalog docelowy i hierarchia DAT-ów (kolejność folderów → „rodzic" →
  `_priorytet.txt`), w obrębie tej samej platformy. Rezerwacje z bieżącego
  przebiegu już o tym nie decydują — bywały niekompletne (np. rodzic
  pominięty, przerwany albo niewłączony) i wtedy planowało się `PRZENIEŚ`
  z ROMS do No-intro zamiast LINK. Kierunek odwrotny bez zmian: plik leżący
  u dziecka rodzic może zabrać do siebie.
  Testy: `test_file_in_parent_dir_child_links_without_any_claim`,
  `test_file_in_child_dir_parent_may_take_it`.

## [0.6.66] — 2026-09-23

### Hierarchia rodzic → dziecko respektowana dla gier na CHD
- **Dziecko nie przenosi już CHD z katalogu rodzica.** Przy katalogu rodzica
  konwersja ze źródła zgłasza także GOTOWE CHD jako obsłużone, a układanie takie
  gry pomijało — bez zapisania, że plik należy do rodzica. Dziecko (np. No-intro
  pod ROMS) widziało go jako „wolny" i planowało `PRZENIEŚ ROMS\ps2\… ->
  No-intro\…` (podgląd PS2: 1090 takich przeniesień) zamiast linku. Teraz
  pominięta gra rodzica na CHD nadal rezerwuje swój plik → dziecko dostaje LINK.
  Test: `test_parent_chd_skipped_as_converted_still_claimed_child_links`.

## [0.6.65] — 2026-09-23

### FinalBurn Neo / arcade (split): koniec kopiowania cudzych zipów i wycinania ROM-ów
- **Klucz roszczeń gry-archiwum zawiera odcisk TREŚCI gry**, nie samą ścieżkę
  źródłowego zipa. Dawniej dwie RÓŻNE gry znalezione w jednym zipie (pgm w
  ddp2.zip, apb3 w apb2.zip, klon w zipie rodzica) wyglądały na duplikat →
  „KOPIA pgm.zip <- ddp2.zip" (cały cudzy zip pod nazwą innej gry). Teraz każda
  gra dostaje WŁASNY zip z wypakowanymi SWOIMI ROM-ami, źródło zostaje.
  Realny podgląd fbneo: KOPIA 31 → 0.
- **Split: gry na BIOS-ie** (romof=pgm/cchip/ym2608/namcoc69, bez cloneof) nie
  „potrzebują" już ROM-ów BIOS-u (dawniej tylko klony odcinały `merge=`). W
  non-merged/merged BIOS też nigdy nie jest wtapiany w grę (osobny zip).
- **Własny zip gry ma pierwszeństwo** przy wielu kandydatach (pgm.zip przed
  ddp2.zip) — dawniej alfabetycznie, więc gra „znajdowała się" w cudzym zipie.
- **Nadzbiory arcade NIE są przepakowywane w miejscu z utratą danych**: własny
  zip gry z dodatkowymi ROM-ami (rodzica/BIOS-u/klonów) = kompletny; przy złych
  nazwach wewnętrznych poprawiamy tylko nazwy, dodatki ZOSTAJĄ. (16.09 naprawa
  zrobiła 4095 takich przepakowań w fbneo, wycinając ROM-y innych gier.)
- Log „PRZEPAKUJ" pokazuje pełną ścieżkę źródła, gdy leży w innym katalogu
  (np. ToSort\mame\gra.zip → fbneo\gra.zip), a nie mylące „gra.zip -> gra.zip".
- Testy: `tests/test_arcade_fbneo.py` (scenariusze z realnej naprawy).

## [0.6.64] — 2026-09-23

### Naprawa nie „stoi" na kompletnych platformach
- **Konwersja w miejscu decyduje z INDEKSU** (`convert_reports`): dawniej dla
  KAŻDEJ gry i KAŻDEGO ROM-u robiła `is_file` + `islink` na NAS — także gdy nic
  nie było do zrobienia. Pomiar: Amiga ~111 s ciszy w logu → ~0 s (3176 gier z
  indeksu w ułamku sekundy); Atari 2600 ~30 s, C64 ~12 s. Dysk sprawdzany jest
  już tylko dla gier, które faktycznie trzeba skonwertować.
- **Dopasowanie DAT-ów z pustymi plikami** (DSi CDN, MSU-1): regresja z 0.6.55 —
  pusty ROM (SHA-1 pustego pliku) łapał KAŻDE archiwum z pustym wpisem w całej
  kolekcji, a potem dla każdego leciało zapytanie o członków (DSi Encrypted:
  ~milion zapytań SQL, ~248 s przy starcie naprawy). Teraz puste ROM-y nie są
  wyszukiwane po sumie, a po NAZWIE sprawdzane tylko w archiwach-kandydatach
  (mających wszystkie niepuste ROM-y). DSi: 248 s → 13 s.

## [0.6.63] — 2026-09-23

### Odbudowa CHD: licznik mówi prawdę + gry CD nie są sprawdzane co przebieg
- Komunikat „Odbudowa CHD: N plików do przerobienia" był mylący — N to
  kandydaci do SPRAWDZENIA (odczyt nagłówka), a przerabiane są tylko te z
  linią „ODBUDOWA". Teraz: „N plików do SPRAWDZENIA … M już potwierdzonych jako
  OK — pominięte". (Przykład: PS2 1538 kandydatów → ~880 realnie do przerobienia.)
- Nowy znacznik w indeksie `layout_ok` (układ ścieżek CHD gry CD zgodny z DAT).
  Potwierdzone gry CD (PSX/Saturn/Dreamcast/Sega CD) są pomijane BEZ czytania
  nagłówka z NAS — dawniej każdy przebieg sprawdzał setki plików. Znacznik
  zeruje się, gdy plik się zmieni.
- Kolejność odbudowy = kolejność gier w pliku DAT (Redump PS2 jest ułożony wg
  kolejności zrzutów, nie alfabetycznie) — bez zmian, tylko wyjaśnienie.

### MSU-1 / konwersja ze źródła
- Sprzątanie NIE przenosi do ToSort źródeł zaplanowanych do skasowania po
  konwersji (np. współdzielone luźne `.pcm` gry spakowanej do `<gra>.zip`) —
  są kasowane, a nie dublowane w ToSort.
- Podgląd („Znajdź naprawy") rejestruje planowany finał jako docelowy — koniec
  fałszywych „TOSORT <gra>.zip" zaraz po „finał → <gra>.zip".

## [0.6.62] — 2026-09-23

### Cofnięte: administrator znów domyślnie WŁĄCZONY (symlinki)
- `auto_elevate` domyślnie **True** (cofnięcie zmiany z 0.6.59). Symlinki są
  używane stale, a bez trybu dewelopera Windows wymagają administratora —
  wyłączenie admina „bo hardlinki” było błędnym założeniem. Opisy przełączników
  (pasek i okno RAM-dysku) poprawione.
- Ścieżka „RAM dysk przez osobny prompt UAC” zostaje jako fallback, gdy UAC przy
  starcie zostanie odrzucony.

## [0.6.61] — 2026-09-23

### Koniec „Nie odpowiada": start, Przerwij, zamykanie
- **Główna przyczyna zamrożeń GUI**: odczyt zapisanego wyniku skanu
  (`load_report_states`) sprawdzał `os.path.isfile` dla KAŻDEGO z ~650 DAT-ów —
  a DAT-y leżą na NAS, więc to ~45 s seryjnych rund SMB **na wątku GUI** (przy
  starcie po wczytaniu DAT-ów, po „Przerwij" i po każdym skanie). Pomiar:
  54,9 s → 3,3 s. Teraz filtrujemy po DAT-ach odkrytych w pamięci
  (`known_keys`), bez dotykania NAS; a odczyt przy starcie idzie w wątku tła.
- **Przerwanie** nie przeładowuje już stanów (są w pamięci od startu).
- **Zamykanie nie wisi**: po zamknięciu okna proces kończy się twardo
  (`os._exit`) — globalna pula wątków Qt czekała na zalegające zadania (obchód
  NAS, oczekiwanie na UAC); `waitForDone` 10 s → 3 s; `imdisk -D` przy zamykaniu
  z timeoutem. Wszystko trwałe jest już zapisane (indeks commituje per operację).
- **Skan: widoczny postęp przygotowania** — fazy ustalania katalogów platform,
  szukania folderów-sierot i analizy rozmiarów DAT-ów (sprawdzenia na NAS)
  logują się i pokazują licznik; analiza DAT-ów reaguje na Przerwij.
- Checkbox „uruchamiaj jako administrator (auto)" w pasku ma aktualny opis
  (zalecane: wyłączone). Uwaga: działający program nadpisywał zmianę w pliku
  ustawień przy zamknięciu — ustawienie zmieniaj checkboxem w programie.

## [0.6.60] — 2026-09-22

### Przerwanie skanu = STOP (koniec wielominutowego mielenia dopasowania)
- **Przerwanie skanu zatrzymuje NATYCHMIAST.** Dawniej po „Przerwij" program
  czyścił flagę i MIMO TO odpalał pełne dopasowanie po WSZYSTKICH włączonych
  DAT-ach (z trwałego indeksu) — a to potrafiło mielić minuty w czystym Pythonie
  NAWET gdy w tej sesji nie przeskanowano ani jednego pliku (użytkownik: „nie ma
  czego dopasowywać"), blokując też zamknięcie programu (GUI „Nie odpowiada").
  Teraz przerwanie kończy pracę od razu, poprzedni wynik zostaje nienaruszony.
- **Odświeżenie dopasowania bez skanu plików**: przycisk „Znajdź naprawy" i tak
  przelicza dopasowanie z indeksu (szybko) — nie trzeba go już wymuszać po
  przerwanym skanie. Przerwanie w TRAKCIE dopasowania (pełny skan) też kończy
  od razu bez nadpisywania wyniku.

## [0.6.59] — 2026-09-22

### Elevacja tylko dla ImDisk (okno wychodzi na wierzch, łatwe zamknięcie)
- **Główny program NIE startuje już jako administrator** (`auto_elevate`
  domyślnie False). Elevacja całego programu powodowała, że Windows (UIPI)
  blokował wyciąganie okna na wierzch kliknięciem w pasku zadań i utrudniał
  ubicie procesu. Linkowanie i tak idzie HARDLINKAMI (bez admina), a symlinki
  nie działają na SMB — admin był potrzebny właściwie tylko dla RAM-dysku.
- **RAM dysk ImDisk podnoszony OSOBNO**: gdy program działa bez admina, tworzenie
  R: idzie przez jeden elewowany PowerShell (`ShellExecuteEx runas` → JEDEN prompt
  UAC przy pierwszym starcie; attach + format w jednym kroku). Istniejący R:
  (z poprzedniej sesji) jest przejmowany BEZ promptu, więc kolejne starty nie
  pytają. Przy zamknięciu bez admina R: NIE jest odmontowywany (zero promptu przy
  zamykaniu; następny start go przejmie). Odmowa UAC/błąd → scratch na dysku
  fizycznym (jak dotąd).
- Przełącznik „Uruchamiaj CAŁY program jako administrator" w oknie RAM-dysku
  (dla potrzebujących symlinków mirror_tree/RetroBat bez trybu dewelopera).

## [0.6.58] — 2026-09-22

### Start/zamknięcie: koniec „cichego zawieszenia"
- **Start nie milczy** — wczytywanie DAT-ów loguje każdą fazę (szukam plików →
  sygnatury → kolizje → metadane JSON → migracja cache → wczytuję DAT: X).
  Wcześniej migracja monolitu + liczenie sum kolizji (jednorazowo ~30–60 s) nie
  dawały żadnego znaku → wyglądało na zawieszenie. Migracja cache DAT-ów loguje
  „Migruję… / zakończona (N plików)".
- **Zamknięcie nie wisi minutami** — `discover` przyjmuje `cancel` i sprawdza go
  między fazami i między DAT-ami; auto-wczytanie na starcie wpięło `cancel`.
  Wcześniej zamknięcie w trakcie pierwszego (długiego) wczytywania z NAS czekało
  aż parsowanie się skończy (proces wisiał, bo wątek ignorował przerwanie).
- **Okno wychodzi na wierzch przy starcie** (`raise_`/`activateWindow`).
  Uwaga: gdy program działa JAKO ADMINISTRATOR, Windows (UIPI) potrafi blokować
  wyciąganie okna na wierzch kliknięciem w pasku zadań — patrz ustawienie
  auto-elevacji (RAM dysk ImDisk wymaga admina).
- Komunikat „Warsztat" jest teraz samowyjaśniający (to pole katalogu-matki na
  górze okna; pusta wartość = ścieżki ustawiasz osobno).

## [0.6.57] — 2026-09-22

### Naprawa: przepis z indeksu + wznawianie (open→Napraw bez skanu)
- **Naprawa odtwarza przepis z INDEKSU na starcie** (wspólna funkcja
  `matcher.match_reports`, ta sama ścieżka co etap „dopasowanie" skanu — koniec
  dwóch rozjeżdżających się ścieżek). Wcześniej naprawa wymagała świeżego
  „Skanuj i raportuj" w tej samej sesji (`self._reports` w pamięci); po restarcie
  mówiła „Brak przepisu". Teraz:
  - **open → Napraw działa od razu** — przepis powstaje z trwałego indeksu w
    sekundy, bez skanu plików (DAT-y odkrywane w locie, cache per DAT).
  - **WZNAWIANIE** — naprawa zapisuje wynik do indeksu per operacja (z commitem),
    więc ponowne dopasowanie widzi gry już naprawione jako HAVE i one wypadają z
    przepisu. Po przerwaniu/restarcie/twardym ubiciu naprawa rusza od miejsca,
    gdzie stanęła, a nie od początku (koniec „doszedł do PS2, przerwałem, a po
    restarcie robi wszystko od nowa").
  - **zmiana DAT** jest łapana bez skanu plików (discover re-parsuje zmieniony
    DAT po sygnaturze, dopasowanie liczone z indeksu). Skan plików potrzebny
    wyłącznie gdy zmieniły się PLIKI.
- **„Znajdź naprawy" (podgląd) = to samo dopasowanie z indeksu + plan dry-run** —
  przestaje być krokiem obowiązkowym przed naprawą, zostaje jako podgląd planu.
- Test: `test_match_reports_from_index_matches_store`.

## [0.6.56] — 2026-09-22

### Wydajność (wczytywanie DAT-ów — koniec „ładowania od nowa" przy każdym starcie)
- **Cache sparsowanych DAT-ów rozbity na OSOBNY plik per DAT** (dawniej jeden
  monolit `dat_parse_cache.pkl` ~315 MB obok exe). Katalog `dat_parse_cache/`,
  jeden mały `<hash>.pkl` na DAT: zmiana JEDNEGO DAT-a nadpisuje tylko jego plik,
  a nie całe 315 MB. Stary monolit jest jednorazowo rozbijany na pliki per DAT
  i usuwany (dane przenoszone 1:1, bez ponownego parsowania). Cache dalej obok
  exe — DAT-y są na NAS, więc lokalny cache omija transfer SMB.
- **Równoległy `stat()` DAT-ów** (`DatStore._stat_sigs`): pomiar wykazał, że
  hamulcem NIE było parsowanie ani odpicklowanie (odczyt 315 MB = 2,5 s), tylko
  **szeregowy `stat()` 609 plików na NAS = ~52 s** (runda SMB na plik). Teraz
  jeden RÓWNOLEGŁY przebieg pobiera sygnatury (mtime+rozmiar) wszystkich DAT-ów
  (liczba wątków wg nośnika: NAS dużo, HDD 1); te same sygnatury zasilają dedup
  kolizji i walidację cache — **koniec drugiego przebiegu `stat()` i `stat()` per
  rekord**.
- **Cache SHA-1 dla dedupu kolizji** (`_load/_save_sha1_cache`,
  `dat_sha1_cache.pkl` obok exe): `_dedupe_collisions` hashowało z NAS treść
  DAT-ów o kolidującym rozmiarze — a identyczne DAT-y ROMS/No-Intro (celowy
  układ) kolidują ZAWSZE, więc było to ~36 s przy KAŻDYM wczytaniu. Teraz SHA-1
  jest cache'owany po sygnaturze; steady-state = 0 odczytów z NAS w dedupie.
- **Sidecary JSON jednym przebiegiem** (`_sidecar_index`): dawniej
  `glob("*.json")` per katalog na NAS (11 katalogów × ~5 s = ~53 s przez listing
  SMB). Teraz jeden `rglob` + RÓWNOLEGŁY odczyt/parse.
- **Błąd: `DatParseCache.prune` kasował cache SHA-1**: prune usuwał z katalogu
  cache KAŻDY `*.pkl` spoza zbioru per-DAT, w tym `dat_sha1_cache.pkl` — więc
  dedup wiecznie re-hashował z NAS. prune rusza teraz TYLKO pliki o kształcie
  per-DAT (`<20 hex>.pkl`).
- **Efekt (pomiar na żywym NAS):** wczytanie wszystkich DAT-ów (`discover`)
  ~104 s → **~13 s** w steady-state (pierwszy przebieg po zmianie DAT-ów dłuższy).
  Testy: `test_cache_is_one_file_per_dat`,
  `test_cache_migrates_monolith_to_per_dat`, `test_prune_keeps_non_per_dat_files`.

## [0.6.55] — 2026-09-21

### Naprawiono (MSU1/format=zip: pusty znacznik .msu w archiwum — koniec pętli wypakuj/pakuj)
- **`<gra>.zip` (format=zip, wieloplikowa) zawiera teraz PUSTE znaczniki size=0
  (np. `.msu` MSU-1).** Dotąd pakowarka gubiła ROM size=0 → zip miał o plik za
  mało (20/21) → matcher NIGDY nie uznawał gry za kompletną (HAVE) → naprawa
  wypakowywała luźno ze źródła i pakowała w kółko, za każdym razem znów bez
  `.msu`. Fix: `pack_zip(empty_entries=…)` zapisuje puste wpisy; `_conv_prepare`
  (i `_convert_one` w miejscu) wyliczają znaczniki size=0 z DAT-u i pakują je,
  a nie wymagają ich „zbieralności".
- **Matcher liczy pusty znacznik jako obecny w archiwum**: `_match_game_archive`
  dopasowuje ROM-y size=0 po NAZWIE członka (sha1/crc puste — nie łapały się po
  treści). Dzięki temu kompletny `<gra>.zip` = HAVE → luźny folder obok staje się
  redundantny (sprzątany), koniec re-dekompresji. Testy:
  `test_pack_zip_writes_empty_markers`.

## [0.6.54] — 2026-09-21

### Naprawiono (Przerwanie naprawy działa na granicy gry — nie mieli do końca DAT-u)
- **„Przerwij" w Naprawie reaguje teraz na GRANICY GRY**, a nie dopiero po całym
  DAT-cie. Dotąd cancel był sprawdzany raz na DAT (`rebuilder.run`), więc przy
  wielkim DAT-cie (np. SNESMSU1 = setki gier × dziesiątki plików) „przerwij"
  wypakowywał tysiące plików do końca platformy, zanim stanął. Teraz pętla
  sprawdza cancel przy KAŻDEJ zmianie gry: **bieżąca gra jest dokańczana**
  (żadnych pół-wypakowanych MSU1), następna NIE jest zaczynana, po czym stop.
  Wykonane operacje są na dysku i w indeksie; wznowienie dokończy resztę.
  Test: `test_cancel_finishes_current_game_skips_next`.
- **Jaśniejszy komunikat przy żądaniu przerwania**: „dokańczam gry będące w
  trakcie, nie zaczynam nowych; po ich zakończeniu stop" (potok konwersji i tak
  dokańcza zadania w locie i nie bierze nowych — `StagePipeline.drain`).

## [0.6.53] — 2026-09-21

### Naprawiono (odbudowa CHD: stabilność potoku + czytelny postęp)
- **Scratch odbudowy NIGDY nie spada na NAS.** Dotąd przy pełnym RAM-dysku scratch
  lądował „obok pliku" = `Z:\ROMS\ROMS\ps2` (SMB) — wielogigowy `createdvd` przez
  sieć zwieszał potok (CPU/dysk/sieć stały minutami) i sypał `createdvd kod 1`.
  Teraz scratch = tylko RAM-dysk → `scratch_dir` (lokalny) → temp systemowy (tylko
  gdy brak RAM-dysku, tryb seryjny). Gdy nic lokalnego się nie mieści → zadanie
  POMINIĘTE (`skipped_space`) i wznowione następnym przebiegiem (odbudowa jest
  idempotentna). Test: `test_scratch_tmp_never_falls_back_to_nas`.
- **Budżet RAM z zapasem (0.6 zamiast 0.85 wolnego RAM-dysku).** Scratch na
  RAM-dysku to ten sam fizyczny RAM, o który walczą OS + cache odczytu z NAS +
  chdman; zapełnianie pod korek wypychało 17–30 GB na `C:\pagefile.sys` (thrash).
  Zapas 40% trzyma RAM pod kontrolą i ogranicza równoległość, gdy trzeba.
- **Realny licznik postępu „zrobione / wszystkie" + nagłówek z kolekcjami/dyskami.**
  Dotąd pasek pokazywał indeks DAT-u („0 / 1"). Teraz: pre-liczenie plików do
  przerobienia z rozbiciem per katalog (platforma + dysk) i licznik podbijany przy
  KAŻDYM zakończonym zadaniu (potok: w release; seryjnie: po zadaniu).
- **Szybkie wznawianie.** Gry DVD z kontenerem już DVD (`bad_container=0` w indeksie)
  są pomijane bez czytania nagłówka z NAS — po przerwaniu wznowienie nie miele od
  nowa wszystkich ~2600 PS2.
- **GUI:** po odbudowie nota, że liczby „do naprawy" odświeży Skanuj/dopasuj
  (indeks już zaktualizowany; bieżący raport jest sprzed odbudowy).

## [0.6.52] — 2026-09-16

### Naprawiono (deep-scan CHD nie miele gotowych plików innych platform)
- **Deep-scan CHD dopasowuje teraz do PEŁNEJ puli włączonych DAT-ów płytowych,
  a nie tylko zaznaczonej platformy.** Objaw (log usera): `CHD do sprawdzenia:
  5648 w 22 katalogach (DAT-y: Commodore Amiga CD32 …)` — 5648 gotowych CHD
  (ps2/psx/3do/saturn/dreamcast) było wypakowywanych (extractcd/deframe/…) i
  znaczonych „brak dopasowania w DAT", bo `known` zawierał TYLKO jeden obcy DAT
  (CD32). Faza 2 skanu wołała `_deep_probe_gui` z wąskim `sel_entries` przy
  pełnym zakresie `roots` → treść 3DO nie była w wąskiej puli. Pliki były CAŁE
  (data_sha1 == profil z DAT-u, round-trip OK) — to skan pytał zły DAT. Fix:
  Faza 2 przekazuje `enabled` (wszystkie włączone).
- **CHD z ustalonym `data_sha1` (już zidentyfikowany do SWOJEGO DAT-u) NIE jest
  ponownie wypakowywany dla innego DAT-u — niezależnie od bieżącej puli.**
  Utwardzenie selekcji kandydatów i taniego checku nagłówka: plik zidentyfikowany
  = zidentyfikowany, kropka; ekstrakcję wymusza dopiero zmiana pliku (mtime) lub
  pełny skan. Chroni przed powtórką „mielenia" przy każdym zawężeniu puli DAT.
  Testy: `test_identified_chd_not_reprobed_for_foreign_dat`.
- **Log sondy CHD**: nagłówek pokazuje `dopasowuję do N DAT-ów płytowych, M gier`
  (od razu widać patologię „tylko 1 DAT"); prefiks per-plik to teraz
  `[platforma/plik.chd]` (widać, z którego katalogu leci CHD w przeplatanym logu).

## [0.6.51] — 2026-09-16

### Naprawiono (re-parenting: dziecko nie może zostać puste)
- **Gdy jedyna kopia fizyczna leży w niższym tierze (np. 1G1R), a naprawa
  RE-PARENTUJE ją do wyższego (ROMS, parent_priority) — miejsce dziecka dostaje
  teraz LINK, zamiast zostać PUSTE.** Scenariusz: gra istniała fizycznie tylko w
  1G1R, potem doszedł wpis do DAT-u ROMS. Rodzik (przetwarzany pierwszy) zabierał
  jedyny plik do siebie, a gałąź HAVE liczyła dziecko jako `already_ok` bez
  odtworzenia linku (bo `_relink_if_stale` odpalało się TYLKO dla istniejącego
  symlinku, a przeniesiony plik po prostu znikał) → gra znikała z 1G1R. Teraz
  warunek obejmuje też „canonical zniknął, a treść jest pod claimem".
- **Utrzymany inwariant (user):** jedna kopia fizyczna na grę, reszta linki;
  priorytet decyduje tylko GDZIE leży oryginał. Zmiana priorytetu przy hardlinkach
  nie robi żadnego ruchu fizycznego (jeden i-węzeł, kilka nazw → `already_ok`).
  Testy: `test_reparent_when_higher_tier_dat_added`, `test_priority_change_no_physical_churn`.

## [0.6.50] — 2026-09-16

### Dodano (HARDLINKI na tym samym woluminie zamiast symlinków)
- **Linkowanie (dedup dziecko→rodzic, zamiana kopii na link, tłumaczenia) na TYM
  SAMYM woluminie tworzy teraz HARDLINK (`os.link`), a nie symlink.** Powód: symlink
  na Windows wymaga trybu dewelopera/administratora (WinError 1314) i **nie działa
  na SMB Z:** — u usera realne linkowanie w ogóle się nie odbywało (miejsca dzieci
  zostawały puste / links_skipped). Hardlink nie wymaga uprawnień i działa na tym
  samym share. `create_link` próbuje hardlink dla PLIKÓW na tym samym woluminie
  (litera dysku albo UNC `\\serwer\share`), a symlink jest fallbackiem (inny wolumin,
  katalog, brak wsparcia). `mirror_tree` (RetroBat) celowo zostaje na symlinkach
  (`prefer_hardlink=False`) — polega na semantyce reparse pointa do bezpiecznego
  czyszczenia i z założenia wskazuje inny wolumin.
- **Hardlink = kopia równorzędna (nie reparse point).** W indeksie zapisywany jak
  zwykły plik z tą treścią (is_link=1 tylko dla realnego symlinku). Nowy helper
  `linker.same_file` (ten sam st_dev+st_ino) rozpoznaje „już zlinkowane" przy
  powtórnym uruchomieniu — bez tego hardlink-dziecko (którego `is_link` nie widzi)
  byłby błędnie uznany za „zwykły plik" → KONFLIKT / zbędna przebudowa fizyczna.
  Poprawione ścieżki: `convert._link_child_to_parent`, `convert._relink_verified_duplicate`,
  `rebuilder._process` (link dziecka), `rebuilder._dedup_confirmed`, `linker.apply_dedup`,
  `translations`. Testy zaktualizowane pod semantykę współdzielenia treści (część
  wcześniej pomijana z braku uprawnień do symlinków — teraz realnie działa).

## [0.6.49] — 2026-09-16

### Naprawiono (audyt spójności ustawień: dedup_copies honorowany też w konwersji)
- **`dedup_copies=false` jest teraz respektowany w konwersji ze źródła (convert),
  nie tylko w rebuilderze.** Dotąd `convert_from_source` linkował dziecko (np.
  1G1R) do fizycznego pliku rodzica ZAWSZE, gdy zgadzał się odcisk treści — mimo
  że katalog miał wyłączony dedup. Rebuilder tę regułę honorował (chronił katalog
  przed dedupem), convert — nie: klasyczna regresja logiczna „zmieniasz opcję dla
  DAT, a program dalej jej nie stosuje". Teraz przy `dedup_copies=false` dziecko
  dostaje WŁASNĄ kopię fizyczną. Test: `test_convert_from_source_dedup_copies_false_makes_physical`.

### Audyt (13 ustawień DAT × skaner/naprawa)
- Zweryfikowano spójność wszystkich ustawień DEFAULT_RULES między skanem a naprawą
  (patrz opis w odpowiedzi/sesji). Cel `target`/`naming`/`rom_root`/`platform`
  schodzą przez `apply_rule_targets` do `entry.target_dir`, którego używają OBA
  (matcher przy skanie, rebuilder/convert przy naprawie) — spójne. `only_complete`,
  `skip`, `prefer_translations`, `parent_priority` honorowane per-DAT w rebuilderze;
  podgląd „Znajdź naprawy" i „Napraw" to ta sama ścieżka `rebuilder.run` (dry/real).

## [0.6.48] — 2026-09-16

### Zmieniono (sieroty: migracja do targetu zamiast ślepego ToSort)
- **Foldery-sieroty (stary/inny output tego samego DAT-u) są teraz SKANOWANE i
  MIGROWANE do skonfigurowanego folderu docelowego DAT-u — a nie ślepo wysyłane do
  ToSort.** Folder output DAT-u jest EDYTOWALNY i często różni się od nazwy z DAT-u
  (np. Commodore 64 z output `c64`, a pliki leżą w starym `commodore64`) — to dalej
  TEN SAM DAT. Poprzednio (0.6.46/0.6.47) sweep patrzył na NAZWĘ folderu i słał
  całość do ToSort (fałszywy pozytyw: `commodore64`→ToSort mimo że to gry C64).
  Teraz:
  - `dirrules.stray_dirs` znajduje sieroty (rodzeństwo zarządzanych platform, nie
    target/kandydat/przodek żadnego DAT-u — z WSZYSTKICH DAT-ów, też wyłączonych).
  - Skan obejmuje sieroty → DAT dopasowuje ich treść po sumach → naprawa PRZENOSI
    pliki do targetu (ELSEWHERE→move, zwykłe przeniesienie). Tak samo działa zmiana
    ustawienia output (ES→nazwa DAT / własny) = migracja starego folderu do nowego.
  - `sweep_orphans` przenosi do ToSort **tylko pliki niepasujące do ŻADNEGO DAT-u**
    (pomija źródła dopasowanych gier — `_placed_sources`), więc nie ma sprzeczności
    „przenieś do targetu" vs „→ToSort" dla tych samych plików. Puste sieroty po
    migracji są usuwane.

## [0.6.47] — 2026-09-16

### Dodano / poprawiono (czytelność logów naprawy)
- **Log KONWERSJI pokazuje ŹRÓDŁO**: `KONWERSJA(ze źródła)→CHD: <gra>  [źródło:
  <ścieżka>]`. Wcześniej nie było widać, skąd leci konwersja (np. PSP: ISO w
  `ROMS\psp\<gra>\` vs archiwum w ToSort).
- **Czytelniejszy kierunek linku**: zamiast mylącego `LINK  A -> B` (czytane jak
  „przenieś A do B") log pisze `LINK (tworzę) A  ⟶  wskazuje na B`. Semantyka bez
  zmian: symlink powstaje w A (miejsce dziecka) i wskazuje na fizyczny plik B
  (rodzic). Kierunek zawsze był poprawny (dziecko No-intro/1G1R → rodzic ROMS).

### Znane / do zrobienia
- **MSU1 (format=zip) układany LUŹNO, nie jako `<gra>.zip`.** Placement rebuildera
  nie patrzy na `store_format=="zip"` i wypakowuje każdy ROM osobno; tylko
  `convert_from_source` pakuje zip (i tylko dla gier w pełni „do zbudowania" —
  stąd 1/~600 spakowana). Poprawne „jeden zip na grę" wymaga modelowania całej
  gry format=zip jako JEDNEGO archiwum w matcher+rebuilder (dziecko linkuje jeden
  `.zip`, nie per-.pcm) — planowane jako osobna, przetestowana zmiana.

## [0.6.46] — 2026-09-16

### Dodano (nieznane katalogi → ToSort)
- **Katalogi/pliki BEZ DAT-a (np. „MAME") są przenoszone do ToSort** podczas
  naprawy (gdy włączone „sprzątanie nieznanych"). Dawniej sprzątanie działało
  TYLKO wewnątrz katalogów-celów DAT-ów, więc folder bez żadnego DAT-a zostawał w
  katalogu docelowym na zawsze — trzeba było czyścić ręcznie. Teraz „sieroty"
  (rodzeństwo zarządzanych platform) lądują w ToSort z zachowaniem względnej
  ścieżki (`ToSort\<tier>\<nazwa>`), gdzie kolejny skan może je gdzieś dopasować.
  `Rebuilder.sweep_orphans` używa **WSZYSTKICH odkrytych DAT-ów** (także
  WYŁĄCZONYCH), więc platforma tylko odznaczona na ten przebieg NIE jest ruszana;
  nie schodzimy w żaden target_dir ani w tier-przodka. Widoczne w podglądzie
  („Znajdź naprawy") jako `NIEZNANY→ToSort (brak DAT-a): …`.

### Naprawiono (puste katalogi po konwersji)
- **Po konwersji ze źródła (ISO→CHD itd.) opróżniony katalog źródła jest usuwany —
  dla KAŻDEJ platformy, także gier JEDNOPLIKOWYCH** (PSP `<gra>/<gra>.iso`, GC/Wii
  RVZ). Dawniej `deferred_dirs` kasował podkatalog tylko przy `n_roms > 1`, więc po
  konwersji pojedynczego ISO zostawał pusty katalog do ręcznego czyszczenia. Teraz
  po skasowaniu źródeł usuwamy puste katalogi-rodziców wszystkich zabranych plików
  (`rmdir` — tylko puste, nigdy nie ruszy katalogu platformy ani gry z plikami).

## [0.6.45] — 2026-09-16

### Dodano (logowanie do pliku + eksport list)
- **Logi zapisywane do pliku, osobno dla każdej operacji, ze znacznikiem czasu
  rozpoczęcia.** Każda operacja z paskiem postępu (skan, „Znajdź naprawy",
  „Napraw", rebuild CHD, wymuś pełny skan…) tworzy własny, datowany plik
  `<baza>\logs\<operacja>_RRRR-MM-DD_GG-MM-SS.log`. Każda linia z godziną; plik
  jest flushowany na bieżąco (awaria/przerwanie nie gubi logu). Skan i rebuild
  trafiają do ODDZIELNYCH plików (rozróżnia je tytuł operacji). Ścieżka pliku
  wypisywana na końcu w oknie. (Wcześniej log był tylko w okienku, znikał po
  zamknięciu — nie dało się diagnozować przebiegów po fakcie.)
- **Eksport list gier („📄 Eksport list…").** Z ostatniego skanu/raportu zapisuje
  trzy datowane pliki w `logs`: `have_*.txt` (komplet), `do_naprawy_*.txt`
  (WRONG_NAME/ELSEWHERE/CREATABLE, ze ścieżką źródło → cel), `brak_*.txt`
  (MISSING/NO_HASH). Do przejrzenia stanu kolekcji poza programem.

### Uwaga
- Diagnostyka hierarchii PSP/PS2 (naprawione CHD w tierze-rodzicu ROMS a linki
  w dzieciach No-intro/1G1R) wymaga logu z przebiegu — teraz jest już zapisywany.

## [0.6.44] — 2026-09-16

### Naprawiono (regresja 0.6.39)
- **Wcześniej naprawione CHD były WYNOSZONE do ToSort przy kolejnej naprawie.**
  Fix 0.6.39 pomijał konwersję gry już na zweryfikowanym CHD (dodawał do `done`),
  ale NIE rejestrował tego CHD jako kanonicznego (`on_converted`/`add_canonical`).
  rb.run pomijał grę → jej CHD nie trafiał do `_canonical` → faza sprzątania
  `_clean_dir` uznawała go za „obcy" i przenosiła do ToSort (kierunek: kolekcja →
  ToSort). Teraz pominięcie rejestruje istniejący `<gra>.chd` jako kanoniczny —
  plik zostaje na miejscu. (Objaw: `TOSORT Z:\ROMS\ROMS\saturn\… .chd -> ToSort`.)

## [0.6.43] — 2026-09-15

### Naprawiono (symlinki na SMB)
- **Poprawne symlinki na udziale SMB były KASOWANE jako „zerwane".**
  `remove_broken_links` sprawdzał `path.exists()`, które PODĄŻA za linkiem — a przy
  wyłączonej ocenie remote→remote (R2R) Windows nie podąża za linkiem na SMB, więc
  `exists()` zwraca False nawet dla POPRAWNEGO linku → dobre linki dzieci (1G1R→
  rodzic) znikały, dzieci wracały „do naprawy". Teraz „zerwany" liczymy po CELU
  (`os.readlink` → `os.path.lexists(cel)`), niezależnie od podążania. Nowe:
  `linker.link_target`, `linker.link_is_broken`.
- **Przestań przepinać poprawny link co przebieg** — `_relink_if_stale` też używał
  `link_path.exists()` (podążanie); teraz sprawdza istnienie CELU.
- Matcher `_link_satisfies` już wcześniej sprawdzał cel (bez podążania) — bez zmian.

Uwaga: tworzenie symlinków wciąż wymaga uprawnienia (admin / Tryb dewelopera) —
błąd WinError 1314 to brak uprawnień, nie problem SMB.

## [0.6.42] — 2026-09-15

### Naprawiono
- **„KOLIZJA DAT" błędnie zwijała identyczny DAT z RÓŻNYCH tierów (ROMS vs
  No-Intro) do jednego — i wybierała No-Intro zamiast ROMS.** To nie kolizja: ten
  sam DAT w ROMS i No-Intro to CELOWY układ (ROMS = rodzic z nazwami
  EmulationStation, No-Intro = dziecko z nazwami Redump; pliki linkowane, bez
  podwójnego miejsca). Teraz dedup DAT-ów działa TYLKO w obrębie tego samego
  tieru (przypadkowy duplikat w jednym katalogu); identyczny DAT w różnych
  tierach → OBA zostają (ROMS wraca jako rodzic).
- **Hierarchia rodzic/dziecko liczona po TIERZE katalogu (odporna).** Gdy w
  platformie najwyższy tier (ROMS) ma JEDEN DAT → on rodzic, reszta dzieci (np.
  Atari Jaguar: ROMS `J64` rodzic, No-Intro `JAG` + 1G1R dzieci — mimo różnych
  kwalifikatorów). Gdy najwyższy tier ma WIELE wariantów i NIE ma nad nimi ROMS
  (np. Apple II: No-Intro `A2R`/`Waveform`/`WOZ`) → platforma dzielona PO
  WARIANCIE: każdy wariant to osobny rodzic swojego 1G1R (Retool), a nie dziecko
  sąsiada. Dawniej wszystkie warianty zlepiały się w jeden „apple ii" i pierwszy
  (A2R) fałszywie stawał się rodzicem Waveform/WOZ. Nowe: `datstore.variant_key`,
  `group_by_platform(entries, rules, dat_root)`.

## [0.6.41] — 2026-09-15

### Dodano (format arcade per DAT — matcher + rebuilder, split)
- Wspólny helper `mamesets.effective_roms(entry, game)` — oczekiwana zawartość
  zipa gry wg `entry.arcade_format`; MATCHER i REBUILDER liczą to samo (brak pętli
  „przepakuj"). `apply_rule_targets` ustawia `entry.arcade_format` (jak store_format).
- **Split (domyślny):** klon (z rodzicem obecnym w DAT) = zip z TYLKO ROM-ami
  unikalnymi (bez `merge=`); współdzielone bierze emulator z rodzica. Skutki:
  - klon w split (same unikalne) → **HAVE** (zielony), koniec fałszywego
    „niekompletny"/„nadzbiór do przepakowania";
  - merged/pełny zip klona → przepakowywany DO split (unikalne), potem HAVE — raz.
  - W split gry NIE zawierają ROM-ów BIOS-u (BIOS osobno) → znika błędny dedup
    BIOS-ów (pgm/skns/cchip) przeciw grom (występował w merged/non-merged).
- non-merged = pełna lista (bez zmian); merged (klon w rodzicu) — do zrobienia.
- Zwykrywanie arcade po `cloneof/romof/isbios`; DAT-y bez parent/clone bez zmian.

## [0.6.40] — 2026-09-15

### Dodano (fundament: format zestawów arcade per DAT)
- Model DAT czyta `isbios` (BIOS-y jak pgm/neogeo/skns); `cloneof/romof/merge` już były.
- `core/mamesets.py` — czysta, przetestowana logika składania setów arcade:
  `plan_sets(games, fmt)` (co ma zawierać każdy zip w **split**/merged/non-merged),
  `families()` (grupowanie parent+klony, BIOS osobno), `has_parent_clone()`.
- Reguła per DAT **`arcade_format`** (`split` domyślnie) w `_reguly.json`, edytowalna
  w „Ustawienia DAT-a…" — dropdown pokazywany TYLKO dla DAT-ów z logiką parent/clone.
  Na razie tylko ZAPIS preferencji; matcher/rebuilder skorzystają z niej w kolejnym
  kroku (podgląd „Znajdź naprawy" przed wykonaniem). Zero zmiany zachowania naprawy.

## [0.6.39] — 2026-09-15

### Naprawiono
- **Ponowna naprawa po przerwaniu budowała CHD od nowa dla gier JUŻ zrobionych.**
  Naprawa działa „z przepisu" — ze statusów z OSTATNIEGO skanu. Po przerwaniu i
  ponowieniu (bez skanu) status gry bywa nieaktualny („luźna"), więc
  `convert_from_source` konwertował ją ponownie, mimo że zweryfikowany
  `<gra>.chd` już istniał. (Postęp BYŁ zapisywany — plik na dysku + indeks
  commitowany na bieżąco — ale planista naprawy o tym nie wiedział.) Dodano żywy
  strażnik na wejściu pętli konwersji: jeśli indeks ma fizyczny `<gra>.chd` z
  `data_sha1 == game_profile`, gra jest pomijana i oznaczana jako zrobiona.
  Odbudowa kontenerów CD→DVD (`rebuild_bad_chds`) już wcześniej sprawdzała stan
  na żywo (re-probe), więc jej to nie dotyczyło.

## [0.6.38] — 2026-09-15

### Naprawiono / Zmieniono
- **„Wymuś pełny skan katalogu" hashował plik po pliku (1 wątek).** Ten przycisk
  wołał `idx.scan(full=True)` BEZ `workers=`, więc na NAS czytał serialnie —
  wielokrotnie wolniej niż zwykły skan (8 wątków).
- **Ujednolicono skanowanie: „skan to skan".** Były TRZY osobne implementacje
  pętli skanu (raport kolekcji, wymuszony pełny skan, skan zakładki Indeks) —
  różniły się i dryfowały (stąd wymuszony zgubił równoległość). Wydzielono jeden
  wspólny rdzeń `scan_paths()`: równoległe hashowanie wg nośnika (NAS/SSD wiele,
  HDD 1), sloty postępu, size-cap per katalog (gdzie dotyczy), oversize→ToSort.
  Wszystkie trzy przyciski korzystają teraz z tej samej ścieżki kodu, więc mają
  identyczne własności wydajnościowe.

## [0.6.37] — 2026-09-15

### Naprawiono
- **Po PRZERWANEJ naprawie sam odpalał się pełny, głęboki skan całej kolekcji.**
  `done()` rozpoznaje przerwanie po `stats.cancelled`, ale flaga przerwania była
  tylko na obiekcie `Rebuilder` (`rb.cancelled`), a `RebuildStats` w ogóle nie
  miał takiego pola — więc `getattr(stats, "cancelled", False)` zawsze dawało
  `False`, gałąź „PRZERWANO" nie wchodziła i sterowanie leciało do
  `_collection_report()` (dwufazowy skan FS + deep-probe CHD). Dodano pole
  `RebuildStats.cancelled` i ustawiamy je przed zwrotem (`rb.cancelled` lub
  `cancel.is_set()`). Teraz przerwanie kończy się komunikatem „zrób skan i ponów",
  bez automatycznego przemiatania NAS-a i głębokiej identyfikacji CHD.

## [0.6.36] — 2026-09-15

### Naprawiono
- **Odbudowa CHD „stała" na 100% po zejściu pliku na NAS.** `_rb_upload` (i
  seryjne `_rebuild_*_one`) liczyły sumy z pliku DOCELOWEGO na NAS PO
  przeniesieniu — czyli PONOWNIE czytały cały CHD przez SMB (pasek na 100% po
  „przenoszę…", a proces po cichu minutami czytał z sieci). Teraz sumy liczymy z
  pliku w SCRATCHU (RAM) PRZED podmianą (treść identyczna, już po round-tripie).
- **Duże DVD w odbudowie mieliły jednowątkowo** (regresja z 0.6.34: `threads=1`
  na zadanie dla równoległości). Przy dużych DVD do RAM mieści się ~1 na raz →
  zero zysku z równoległości, a chdman dostawał 1 wątek → ~12 MB/s, „jakby
  zawieszone". Teraz **pula wątków dzielona dynamicznie**: `wątki_na_CHD =
  pula // ile_takich_zmieści_się_w_budżecie_RAM`. Duży DVD (1 na raz) → cała pula
  (do 8); małe CD (kilka na raz) → pula podzielona (np. 4×2). Zgodnie z zasadą
  użytkownika: „8 do dyspozycji — 1 CHD=8, 2 CHD=po 4, 4 CHD=po 2".

## [0.6.35] — 2026-09-15

### Naprawiono
- **FBNeo/arcade: te same ZIP-y „przepakowywały się" co przebieg naprawy.**
  `PRZEPAKUJ x.zip -> x.zip (poprawne nazwy wewn.)` / `WYPAKUJ ...` padały z
  „There is no item named 'X' in the archive", bo nazwę członka brano z INDEKSU
  (`member_name_in`), a dla MAME merged/parent bywa nieaktualna (nazwa w indeksie
  ≠ nazwa w pliku). Skutkiem repack się nie udawał, ścieżka kanoniczna nie była
  zajmowana, a że placement leci raz na KAŻDY ROM gry — ta sama próba wracała
  kilkanaście razy w jednym przebiegu i przy każdej kolejnej naprawie. Teraz:
  - `_rebuild_zip` i `_extract_member` **dobierają członka z RZECZYWISTEGO
    archiwum po CRC+rozmiar** (central directory, bez dekompresji), gdy nazwa z
    indeksu nie istnieje w pliku; treść nadal weryfikowana SHA-1. ROM obecny pod
    inną nazwą jest teraz poprawnie odczytany; ROM-a naprawdę nieobecnego nie
    fabrykujemy (błąd raz, bez pętli).
  - **Umieszczenie archiwum gry próbowane RAZ na ścieżkę kanoniczną**, nie raz na
    ROM (`_archive_tried`) — koniec kilkunastu identycznych prób repacku na grę.

### Znane (do zrobienia)
- Pełna świadomość MAME merged/parent/BIOS/device: gry rozbite między
  `mario.zip`+`marioe.zip`, oraz dedup zestawów device (`pgm/skns/cchip`) dający
  `KONFLIKT: ... zajęte zwykłym plikiem` — wymaga rekonstrukcji zestawów wg
  cloneof/romof/device (większy temat).

## [0.6.34] — 2026-09-15

### Zmieniono
- **Odbudowa kontenerów CHD (CD→DVD / zły układ ścieżek) idzie teraz RÓWNOLEGLE**
  — kilka `chdman` naraz, jak główna konwersja. Dotąd `rebuild_bad_chds` robiło
  gry pojedynczo, mimo że reszta konwersji korzysta z potoku. Gdy jest RAM-dysk
  (i nie podgląd), praca leci przez `StagePipeline` (gather I/O → build CPU →
  upload I/O), liczba równoległych = ustawienie `convert_workers` lub auto
  (min. 8, ~½ rdzeni logicznych), a REALNĄ równoległość ogranicza BUDŻET RAM
  (0,85 wolnego RAM-dysku; wielkie DVD 11–13 GB → zwykle 2–3 naraz). Bez
  RAM-dysku — jak dotąd, seryjnie. Zapisy do indeksu (SQLite) nadal wyłącznie w
  wątku właściciela (finalize potoku).
- **Przerwanie odbudowy CHD jest ŁAGODNE** — rozpoczęte konwersje DOKAŃCZAJĄ się
  i są zatwierdzane (round-trip → atomowa podmiana → wpis do indeksu → zdjęcie
  flagi `bad_container`), zamiast ubijać `chdman` w locie. Przerwanie wstrzymuje
  tylko PODAWANIE nowych zadań; `chdman` nie dostaje już `cancel_event` (spójnie
  z głównym potokiem konwersji). **Status przerwanego pliku:** nierozpoczęte CHD
  zostają z `bad_container=1` i następny przebieg je WZNAWIA; oryginał nie jest
  kasowany, dopóki nie powstanie zweryfikowany zamiennik (brak plików częściowych).

## [0.6.33] — 2026-09-15

### Dodane
- **Priorytet katalogów DAT-ów przez przesuwanie w drzewie.** Prawy klik na
  katalogu → „⬆ Wyżej / ⬇ Niżej" (albo Ctrl+↑ / Ctrl+↓). Katalog wyżej ma
  pierwszeństwo nad niższymi: jego DAT-y są naprawiane pierwsze i trzymają pliki
  fizycznie, identyczne pliki w niższych katalogach dostają symlinki — np.
  ROMS → No-intro → 1G1R. Katalogi mają w drzewie numer pozycji („📁 1. ROMS"),
  kolejność wyświetlania = kolejność przetwarzania. Zapis w `_kolejnosc.json`
  obok `_reguly.json`; DAT-y i przepis naprawy przestawiają się od razu, bez
  ponownego skanu. Bez zapisanej kolejności działa jak dawniej (katalogi
  z „rodzice platform" na górze), a nowe katalogi nie przeskakują ustalonej
  kolejności. `_priorytet.txt` rozstrzyga już tylko w obrębie jednego katalogu;
  kolekcje tłumaczeń zostają pulą wariantów (rola `translations`).

### Naprawione
- **Struktura DatRoot odzwierciedla się w rom_root także przy `naming: es`.**
  Konwencja ES układała płasko (`<rom_root>/<system>`), gubiąc katalog-grupę
  DAT-a: `DatRoot/ROMS/…` lądował w `Z:/ROMS/atari2600` zamiast
  `Z:/ROMS/ROMS/atari2600`. Teraz `<rom_root>/<katalog DAT-a>/<es-folder>` —
  konwencja decyduje tylko o nazwie liścia. Ręcznie wybrany `rom_root`
  (reguła, np. No-Intro) zostaje płaski. Pliki w starym płaskim układzie są
  nadal skanowane (druga konwencja) i naprawa przeniesie je na nowe miejsce.
- **Skan z zaznaczonym DAT-em kartridżowym identyfikował CHD innych platform.**
  Zaznaczona pula tłumaczeń [T-En] nigdy nie jest „kompletna", więc skan zawsze
  przechodził do Fazy 2, a ta uruchamiała głęboką identyfikację CHD dla
  WSZYSTKICH włączonych DAT-ów (PS1/PS2 z `Z:\ROMS`, ToSort) — z ekstrakcją
  obrazów z NAS-a. Teraz:
  - identyfikacja CHD rusza tylko dla DAT-ów PŁYTOWYCH (format chd/rvz albo
    cue/gdi/iso/chd w treści DAT-u); bez nich — jedna linia w logu i koniec,
  - przy zaznaczonej platformie dotyczy wyłącznie zaznaczonych DAT-ów
    (Faza 2 nadal doskanowuje pliki, ale nie mieli CHD innych platform).
- **Log CHD pokazuje źródło.** Pełne ścieżki w „CHD głęboko / OK / BRAK /
  info / POMIJAM" i w sondzie nagłówka przy skanie; na starcie identyfikacji
  podsumowanie „CHD do sprawdzenia: N w K katalogach" z listą katalogów i DAT-ów.
  Co 200 plików skan loguje pełną ścieżkę zamiast samej nazwy.
- **Odznaczony DAT tracił zapamiętany raport.** Stan raportu był jednym plikiem
  `report_state_cache.pkl`, nadpisywanym po każdym skanie samymi WŁĄCZONYMI
  DAT-ami, a widok po skanie czyścił zapamiętane stany — odznaczenie DAT-u (żeby
  skan był szybszy) kasowało jego wynik. Teraz raport jest zapisywany OSOBNO
  per DAT (`report_states\<hash>.pkl`): skan zapisuje tylko przeskanowane DAT-y,
  wyłączony zostaje nietknięty i dalej pokazuje ostatni stan. Stary wspólny
  plik jest jednorazowo rozbijany na pliki per DAT (sam plik zostaje). Indeks
  plików nie był dotknięty — sumy i identyfikacja CHD zawsze się zachowywały.

## [0.6.32] — 2026-09-15

### Naprawione
- **Podmiana na tłumaczenie ignorowała format katalogu.** Slot dostawał nazwę
  ROM-u z DAT-u („… (Japan).rom"), więc w katalogu z formatem `zip` powstawał
  link `.rom` wskazujący na archiwum `.zip` tłumaczenia, a oryginalny
  `<gra>.zip` zostawał obok i to on się uruchamiał (MSX2: Metal Gear 2,
  Gekitotsu Pennant Race 2). Teraz slot wynika twardo z ustawienia katalogu:
  - `zip` / `7z` / `chd` / `rvz` → `<gra>.<ext>`, `extract` → luźny ROM,
    `keep` → forma tłumaczenia;
  - oryginał w KAŻDEJ formie (luźny ROM, `.zip`, `.7z`) trafia do
    `to sort\translated\<system>` — bez duplikatu obok tłumaczenia;
  - rzadki rozjazd form: luźne tłumaczenie w katalogu `zip` jest pakowane do
    `<gra>.zip`, zip w katalogu `extract` — wypakowany; innych przejść
    (np. do 7z/CHD) nie robi, a oryginał zostaje nietknięty.
- **Zip tłumaczenia w innej metodzie kompresji niż ustawiona** (np. ZSTD przy
  deflate) nie jest linkowany, tylko kopiowany do slotu i przepakowany
  z weryfikacją SHA-1. Link przeniósłby niezgodny zip do kolekcji, a
  normalizacja kompresji w naprawie linków nie dotyka.
- Matcher nie uznaje już starej podmiany (link `.rom` → `.zip`, luźny ROM
  w katalogu `zip`) za spełnioną — gra traci 🌐 i można ją podmienić ponownie.
  Porównanie sumy slotu-archiwum bierze też sumę ROM-u w środku.
- „Cofnij podmianę" obsługuje wszystkie formy gry, slot zbudowany
  z tłumaczenia (spakowany/przepakowany) oraz stan po starej podmianie.

## [0.6.31] — 2026-09-14

### Naprawione (z code review — druga partia)
- **RAM dysk mógł oddać niesformatowany wolumin RAW jako scratch.** `_ready`
  (a więc `active_root`/`reuse_if_exists`) uznawał dysk za gotowy po samym
  write-probe, który na świeżym RAW potrafi mylnie „przejść" — chdman pisał
  wtedy w RAW/temp na NVMe. Teraz gotowość na Windows wymaga też realnej nazwy
  systemu plików (`GetVolumeInformationW`).
- **`remount` po nieudanym mkdir mógł SFORMATOWAĆ dysk w trakcie równoległych
  ekstrakcji.** Przejściowy błąd zapisu jednego wątku (R: chwilowo zajęty)
  uruchamiał `create()`, które formatowało istniejące urządzenie ImDisk —
  niszcząc trwające ekstrakcje innych wątków. Teraz formatujemy TYLKO wolumin
  naprawdę RAW (brak FS); sformatowany-ale-zajęty jest uznawany za gotowy.
- **Symlink dziecka mógł wskazać rodzica, którego jeszcze nie ma.** W trybie
  potoku `final_by_profile` wskazuje rodzica ustawionego PRZY ZLECENIU (async,
  albo build padł) — dziecko dostawało wiszący symlink. `_link_child_to_parent`
  wymaga teraz, by rodzic realnie ISTNIAŁ (inaczej dziecko budowane jest samo).
- **Skan (odczyt) mógł po cichu przenieść ZNANE ROM-y do ToSort.** Reguła
  „za duży dla platformy → ToSort" ruszała też pliki JUŻ zaindeksowane (np.
  dopasowane do platformy teraz wyłączonej). Teraz auto-przenoszone są tylko
  pliki NIEZNANE indeksowi (`row is None`).
- **Finalizacja kasowała źródła, gdy hash finału się nie powiódł.**
  `_conv_finalize_phase` zapisywał wpis w indeksie tylko przy udanym haszu, ale
  źródła kasował ZAWSZE — plik na dysku bez wpisu, a źródła skasowane. Teraz
  kasowanie/odroczenie źródeł tylko po udanym zapisie; dodatkowo `_conv_upload_phase`
  ponawia hash raz (przejściowa blokada AV/indeksera).
- **Skan wysypywał się na jednym błędnym pliku i porzucał pulę wątków.**
  `_drain` łapał tylko `HashAborted`/`OSError`; inny wyjątek (np. `MemoryError`)
  wywracał cały „Znajdź naprawy" i zostawiał wiszące wątki. Teraz błąd
  pojedynczego pliku jest logowany i pomijany, a pula wątków jest ZAWSZE
  domykana (`try/finally`).
- **Szybki `rename` między udziałami UNC tego samego serwera.** `same_volume`
  zwracał `False` dla `\\nas\a` vs `\\nas\b` (różne „dyski"), wymuszając wolne
  kopiowanie. Teraz dopuszcza próbę `rename` w obrębie tego samego serwera
  (bezpiecznie — `os.rename` nie kopiuje, przy różnych woluminach padnie).

## [0.6.30] — 2026-09-14

### Naprawione (z code review)
- **Podmiana na tłumaczenie mogła zostawić kanoniczną ścieżkę PUSTĄ.**
  `apply_substitution` przenosił oryginał do `translated/` PRZED utworzeniem
  symlinku; brak uprawnień (albo `make_links=False`) zwracał `False` bez
  przywrócenia. Teraz: sprawdzenie `make_links` PRZED ruszeniem oryginału
  (fail-fast) + ROLLBACK (przywrócenie oryginału) gdy `create_link` padnie.
- **Fałszywe „komplet" dla tłumaczenia.** Matcher uznawał zapisaną podmianę za
  HAVE po samym `os.path.lexists` kanonicznej ścieżki — wiszący symlink
  (skasowany cel) lub obcy plik dawały fałszywy komplet. Teraz cel musi ISTNIEĆ
  (`os.path.exists`, odrzuca wiszący link), a gdy indeks zna treść — musi
  zgadzać się z zapisanym wyborem (`rec["sha1"]`).
- **Aktualizacja gry mogła zostawić stan częściowy.** `apply_update` usuwał
  starą wersję przed potwierdzeniem kopii nowej, a nieudane przeniesienia tylko
  logował (fałszywy sukces). Teraz: nowe pliki są STAGE'owane i weryfikowane
  OBOK celu przed ruszeniem starych (porażka kopii = nic nie ruszone), zatwierdzenie
  atomowe (`os.replace`), a każde nieudane przeniesienie jest PROPAGOWANE (zwraca
  `False` + jasny komunikat).
- **Przewidywalny plik tymczasowy repacka ZIP.** `repack_zip` pisał do
  `<archiwum>.chdbuddy_repack.zip` (przewidywalna nazwa) przez `ZipFile("w")` —
  inny proces mógł podstawić tam symlink i spowodować nadpisanie celu. Teraz
  `mkstemp` (O_EXCL, losowa nazwa) obok archiwum.

## [0.6.29] — 2026-09-11

### Zmieniono
- **Skan nie przemiata drugi raz katalogu-rodzica pokrywającego platformy z
  Fazy 1** (np. `Z:\No-Intro` = rom_root reguły No-Intro, a Faza 1 skanowała już
  `Z:\No-Intro\<platforma>`). Dotąd Faza 2 skanowała goły `Z:\No-Intro` w całości,
  przechodząc PONOWNIE przez dziesiątki tysięcy plików już zeskanowanych w Fazie 1
  (na NAS realny koszt — pełny obchód SMB). Teraz `idx.scan` przyjmuje `skip_dirs`
  i NIE schodzi w poddrzewa Fazy 1 (pre-count `count_files` też je pomija, więc
  pasek dobija do 100%). **Pokrycie i linkowanie nienaruszone:** reszta rodzica
  jest skanowana normalnie, a pliki z pominiętych poddrzew nie są oznaczane jako
  brakujące (`_mark_missing` wyklucza je po normcase) — więc ROMS/1G1R nadal
  linkują do No-Intro (część z tych plików to już linki z ROMS).

## [0.6.28] — 2026-09-11

### Naprawiono
- **Licznik plików skanu przebijał total (np. „128159/90143 plików").** Skan
  dwufazowy (Faza 1 = wybrana platforma, Faza 2 = reszta kolekcji) liczy pasek
  względem OSOBNEGO `grand` dla każdej fazy, ale akumulator `base` nie był
  zerowany między fazami — więc numerator Fazy 2 startował od liczby plików
  Fazy 1 (43334) i rósł ponad mianownik reszty (90143). Teraz `_scan_list`
  zeruje akumulator na wejściu → każda faza pokazuje poprawne „X z Y". Sam skan
  i indeks działały dobrze; to była wyłącznie wartość na pasku/logu.

## [0.6.27] — 2026-09-10

### Zmieniono
- **Naprawa idzie teraz KATALOG PO KATALOGU (z góry na dół) i DOMYKA każdy
  katalog zanim ruszy dalej.** Dotąd naprawa była globalnymi fazami przez całą
  kolekcję (najpierw sprzątanie po wszystkich DAT-ach, potem konwersja po
  wszystkich, potem placement po wszystkich…), przez co program „robił Saturn",
  gdy Atari Jaguar i FinalBurn Neo miały jeszcze zaległości. Teraz dla każdego
  katalogu po kolei wykonujemy pełny cykl: (1) sprzątnięcie pozostałości obok
  gotowych CHD, (2) IN-PLACE — konwersja ze źródła (luźne bin/cue/iso → CHD/RVZ)
  + placement (rename/repack) + konwersja-fallback + naprawa złych kontenerów
  CHD, (3) uzupełnienie braków z ToSort, (4) sprzątanie tego katalogu (zmiecenie
  nie-kanonicznych do ToSort, kasowanie źródeł, puste podkatalogi). Dzięki temu
  **przerwanie zostawia górne katalogi w pełni gotowe**, a nie w połowie.
- **DEDUP (kopie→symlinki dziecko→rodzic między platformami) odroczony na jeden
  końcowy przebieg** (`Rebuilder.finalize_global`). Jest z natury globalny —
  dziecko (1G1R) może zlinkować do rodzica dopiero, gdy rodzic jest już zrobiony;
  pełny rodzic (ROMS) dedupu nie potrzebuje. Leci raz, po domknięciu wszystkich
  katalogów; pomijany przy przerwaniu (jak dotąd sprzątanie/dedup). Kasowanie
  zbędnych archiwów i pustych katalogów w ToSort również przeniesione do finału
  (operacje na całym ToSort, nie na jednym katalogu). Nowy tryb `rb.run(...,
  defer_global=True)` + `rb.finalize_global(done_reports, …)`.

## [0.6.26] — 2026-09-10

### Naprawiono
- **Sprzątanie obok gotowych CHD „nic nie robiło" na dużych kolekcjach** (np.
  dreamcast: 265 CHD, ~1220 luźnych `.bin` zostawało nietkniętych). Przyczyna:
  ochrona współdzielonych torów (`needed_sha1`) traktowała jako „potrzebującą"
  KAŻDĄ grę niezaspokojoną — w tym gry BRAKUJĄCE (MISSING/NO_HASH), których i
  tak nie da się zbudować. Przy tysiącach brakujących gier dreamcast
  współdzielących tory audio (Track 04–10) `needed_sha1` puchło (7233 wpisów) i
  chroniło praktycznie wszystko → 0 skasowanych. Zgodnie z zasadą usera
  („nie trzymamy torów dla gier brakujących”): tor chroni już tylko gra
  **budowalna** — niezaspokojona ORAZ mająca komplet torów DANYCH (roms spoza
  `.cue/.gdi/.toc`) obecnych (nie MISSING/NO_HASH). Repro na kopii realnego
  indeksu: `needed_sha1` 7233→4, skasowanych 0→1415 (dreamcast).

## [0.6.25] — 2026-09-10

### Naprawiono
- **Przerwana naprawa nie sprzątała pozostałości obok GOTOWYCH CHD.** Po
  „Przerwij" rebuilder pomija zmiatanie do ToSort i dedup (słusznie — przy
  niepełnym dopasowaniu mogłyby uznać znany plik za śmieć), a kasowanie luźnych
  torów gry-już-na-CHD działo się dotąd tylko W TRAKCIE konwersji danej gry —
  więc przerwanie na „DAT 0/47" zostawiało cały bałagan. Nowy, samodzielny,
  PRZERYWALNY przebieg `purge_loose_on_verified_chd` leci TERAZ NA POCZĄTKU
  naprawy i kasuje — per gra, o udowodnionej redundancji (treść żyje w
  ZWERYFIKOWANYM CHD: `data_sha1==game_profile`) — luźne `.bin/.cue/.gdi` oraz
  `<gra>.zip/.7z` leżące obok CHD, wraz z opustoszałym podkatalogiem `<gra>\`.
  Bezpieczny nawet przy bardzo wczesnym przerwaniu (NIE wymaga pełnego obrazu
  kolekcji, więc NIE jest pomijany jak zmiatanie/dedup). Sprząta pozostałości po
  starych przebiegach (CHD z ToSort, docelowe tory nietknięte).

## [0.6.24] — 2026-09-10

### Naprawiono
- **Po konwersji/sprzątaniu na CHD zostawał PUSTY podkatalog `<gra>\`** (bin/cue
  leżały w podfolderze pod katalogiem platformy; pliki znikały, katalog nie).
  Teraz wszystkie trzy ścieżki kasowania w `convert_from_source` usuwają
  opustoszały katalog gry: `_defer_or_purge_game_sources` (źródła unikalne),
  `purge_source_files` (współdzielone, kasowane na końcu naprawy) oraz
  `_purge_child_loose_duplicates` (luźne tory gry już-na-CHD z wcześniejszych
  przebiegów). Nowy helper `_rmdir_if_empty` kasuje katalog TYLKO gdy pusty
  (katalog platformy ma świeży .chd + inne gry → nigdy nie zniknie). Pozostałość
  po starych przebiegach (CHD z ToSort, a docelowe bin/cue nietknięte) sprząta
  się teraz sama: nierozpoznany CHD + luźne tory → konwersja w miejscu (0.6.22)
  buduje zweryfikowany CHD i kasuje tory wraz z katalogiem.

## [0.6.23] — 2026-09-10

### Zmieniono
- **Kolejność konwersji: NAJPIERW w miejscu, POTEM z ToSort.** W obrębie każdego
  DAT-u gry, których źródło jest już w katalogu docelowym (naprawa w miejscu — zła
  nazwa/format/opakowanie po zmianie ustawień DAT), są przetwarzane PRZED grami ze
  źródłem w ToSort (uzupełnianie braków). Bez tego kopia z ToSort mogła zostać
  keeperem odcisku przed własną kopią kolekcji, a to kolekcja jest źródłem prawdy.
  `sorted` stabilne → kolejność DAT-u zachowana w obrębie grupy; rodzic-przed-
  dzieckiem (kolejność MIĘDZY raportami) nietknięte. Zweryfikowane: dla dreamcast
  231 kandydatów „w miejscu" idzie przed czymkolwiek z ToSort.

## [0.6.22] — 2026-09-10

### Naprawiono
- **Naprawa W MIEJSCU dla płyt luźnych: bin/cue/iso → CHD, gdy DAT ma „płyty jako
  CHD".** Dotąd komplet luźnych torów gry w katalogu docelowym był traktowany jako
  HAVE („zaspokojona bez konwersji") i naprawa go NIE ruszała — konwertowały się
  głównie rzeczy z ToSort. To sprzeczne z ustawieniem formatu (fmt=chd): skoro
  ustawienie mówi CHD, to luźne bin/cue to ZŁY FORMAT (naprawa), nie „gotowe".
  Teraz `convert_from_source` dla platform dyskowych (fmt=chd) NIE pomija gier
  „HAVE-luzem" — konwertuje je w miejscu (źródłem są luźne pliki z kolekcji), a po
  zweryfikowanym CHD luźne tory sprząta istniejący blok po konwersji. Formaty
  jednoplikowe już w docelowym (.rvz) i zip/keep nadal traktowane jak zaspokojone.
  Dotyczy m.in. dreamcast/saturn trzymanych jako bin/cue.

## [0.6.21] — 2026-09-10

### Naprawiono
- **Skan „stoi" po „doskanowuję resztę kolekcji" (Faza 2 dublowała Fazę 1).**
  Gdy wybrana platforma wyszła NIEKOMPLETNA, Faza 2 liczyła (`_count`) i skanowała
  `roots` = WSZYSTKIE katalogi platform + ToSort — czyli te SAME katalogi, które
  Faza 1 (priorytet) właśnie przeszła. Ciche `_count` całej kolekcji (dziesiątki
  tysięcy plików po SMB, bez logów) wyglądało jak zawieszenie, a potem następował
  redundantny ponowny skan tych samych katalogów. Teraz Faza 2 pomija katalogi już
  przeskanowane w Fazie 1 (`prio`) i doskanowuje TYLKO resztę (zwykle ToSort /
  nadpisania rom_root). Koniec z podwójnym obchodem drzewa i „staniem" po Fazie 1.

## [0.6.20] — 2026-09-10

### Naprawiono
- **Bardzo wolny PODGLĄD naprawy („Znajdź naprawy") na NAS.** Objaw jak przy
  skanie: sieć ~2%, CPU <5%, ~1 gra/s — sama latencja SMB. Przyczyna: dla KAŻDEJ
  gry planowanej do przeniesienia z ToSort robiliśmy 1–2 rundy SMB na dysk, choć
  świeży indeks znał odpowiedź:
  - matcher `_link_satisfies` wołał `os.path.islink` na ścieżce kanonicznej
    (przy przenosinach z ToSort ona jeszcze nie istnieje → i tak False);
  - rebuilder `_clear_dest` wołał `os.path.lexists`/`is_link` NAWET w dry-run.
  Teraz w PODGLĄDZIE odpowiada INDEKS (po skanie jest źródłem prawdy), bez
  dotykania dysku: `_link_satisfies(…, index)` kończy na `lookup`, a `_clear_dest`
  w dry-run czyta stan z indeksu. Faza EXECUTE nadal robi prawdziwe sprawdzenie
  FS (bezpieczeństwo). Podgląd naprawy dużej kolekcji spada z minut do sekund.

## [0.6.19] — 2026-09-10

### Naprawiono
- **Bardzo wolny skan PRZYROSTOWY dużej kolekcji ZIP-ów (regresja 0.6.16).**
  Objaw: „policzono 0" (nic nie hashowane), a skan „stoi" — sieć ~2%, CPU <5%,
  sama latencja. Przyczyna: gałąź „bez zmian" dla KAŻDEGO `.zip` z
  `bad_zip_method == -1` otwierała centralny katalog ZIP-a (`_zip_method_flag`)
  SZEREGOWO w głównym wątku = jedna runda SMB na plik (przy 108k zipów → minuty
  czekania na round-tripy, mimo puli 8 wątków do hashowania). Usunięto to
  otwieranie ze skanu. `bad_zip_method` ustawia `_index_members` przy
  indeksowaniu członków (nowe/zmienione zipy oraz upgrade bez SHA-1), więc flaga
  i tak powstaje, gdy ZIP jest otwierany z realnego powodu — bez dodatkowej rundy
  SMB per plik. Zipy z programu są deflate; niezgodne (zstd/lzma) z zewnątrz
  przychodzą jako NOWE → nadal łapane. Skan przyrostowy wraca do dawnej szybkości.

## [0.6.18] — 2026-09-10

### Naprawiono
- **KRYTYCZNE: naprawa przenosiła do ToSort POPRAWNE, dopasowane pliki gier
  jednoplikowych (regresja — całe kolekcje RVZ GameCube/Wii wylądowały w ToSort).**
  Przyczyna: gra jednoplikowa w podfolderze `<gra>/<gra>.rvz` (poprawny układ
  RomVault) dostawała status **HAVE** poprawnie, ale `_process` rejestrował w
  zbiorze chronionym `_canonical` ścieżkę KANONICZNĄ **płaską** (`<gra>.rvz`),
  podczas gdy realny plik leży w PODFOLDERZE. Faza sprzątania `_clean_dir`
  porównywała realną ścieżkę z indeksu — nie znajdowała jej w `_canonical` →
  uznawała plik za „nieznany" i przenosiła do ToSort (mimo aktywnego DAT-u RVZ
  i statusu HAVE, w TYM SAMYM przebiegu). Teraz gałąź HAVE/HAVE_CHD chroni też
  REALNĄ ścieżkę pliku (`source_path`) — układu podfolderowego NIE spłaszczamy.
  Dotyczy każdej gry jednoplikowej trzymanej w `<gra>/<plik>` (RVZ/CHD/inne).

## [0.6.17] — 2026-09-10

### Naprawiono
- **Wolny skan PO naprawie (pliki tworzone/przenoszone przez program hashowane od
  nowa).** Przyczyna: `index.rename` (wołane przy KAŻDYM przeniesieniu w naprawie)
  ruszał tylko wpis w `files`, a NIE przenosił CZŁONKÓW archiwum (`members`). Po
  przeniesieniu ZIP-a z ToSort do kolekcji indeks nie miał dla nowej ścieżki żadnych
  członków → następny skan wypakowywał i hashował całą zawartość każdego ruszonego
  zipa (drogie na NAS), choć plik ruszył sam program. Teraz `rename` przenosi też
  `members` (mtime pliku po `os.replace`/`copystat` jest zachowany, więc wpis jest
  aktualny → skan uznaje plik za świeży, zero re-hashu).
- **ZIP-y TWORZONE przy konwersji** (pakowanie luźnych źródeł) indeksują teraz od
  razu także członków (`reindex_archive`), więc następny skan ich nie wypakowuje.
  (CHD bez zmian — miały `data_sha1`; RVZ przez `record_file`.)
- Efekt: po `Napraw` kolejny skan jest szybki, o ile nie pojawiły się FAKTYCZNIE
  nowe pliki z zewnątrz — zgodnie z oczekiwaniem.

## [0.6.16] — 2026-09-10

### Zmieniono
- **Wykrywanie złej metody ZIP przeniesione do SKANU (koniec re-skanu w naprawie).**
  0.6.15 usunął automatyczną „normalizację kompresji" (otwierała WSZYSTKIE zipy w
  każdej naprawie — wieszało się przy 100%). 0.6.16 robi to poprawnie: wykrywa
  metodę w SKANIE (tanio, z centralnego katalogu ZIP-a, bez dekompresji) i
  zapisuje flagę `bad_zip_method` w indeksie. Wzorzec jak `bad_container`:
  - **skan** (`fileindex`): nowa kolumna `bad_zip_method` (migracja `ALTER TABLE`);
    ustawiana przy indeksowaniu archiwum + tani jednorazowy backfill istniejących
    zipów. Metoda ≠ store/deflate (ZSTD 93 / LZMA 14 / bzip2 …) → `1`.
  - **matcher**: `<gra>.zip` o złej metodzie w katalogu docelowym → HAVE
    degradowane do „do naprawy" (flaga na statusie).
  - **naprawa** (`rebuilder`): dla OZNACZONYCH przepakowuje ZIP w miejscu na
    `zip_method` (deflate), aktualizuje sumy, kasuje flagę. Zero skanu kolekcji.
  - **GUI**: ikona 🗜 + nota „zła metoda ZIP".
- LZMA jako metoda ZIP odrzucona — ta sama niezgodność co ZSTD (emulatory czytają
  w .zip tylko store/deflate). Deflate zostaje standardem.

## [0.6.14] — 2026-09-10

### Naprawiono
- **Naprawa „wisiała" przy 100% (cicha faza po dedupie).** Po „dedup / sprzątanie
  kopii" (pasek 100%) uruchamiała się `_normalize_target_zip_compression`, która
  OTWIERA KAŻDY kompletny ZIP na NAS, by sprawdzić metodę kompresji — przy
  dziesiątkach tysięcy gier to wiele minut, BEZ paska i BEZ możliwości przerwania
  (etykieta paska nadal pokazywała „dedup / sprzątanie kopii" — stąd wrażenie
  zawieszenia). Teraz:
  - normalizacja ma WŁASNĄ etykietę „normalizacja kompresji ZIP" + postęp co 200
    plików i jest PRZERYWALNA (`Przerwij`),
  - `_prune_empty_dirs` (walk po ToSort/kolekcji) też przerywalny + etykieta
    „puste katalogi",
  - `cancel` trzymany na `self` (fazy po głównej pętli mogą przerwać).
  Uwaga: normalizacja wciąż skanuje CAŁĄ kolekcję co przebieg (do rozważenia:
  ograniczyć do zipów ruszanych w danym przebiegu / osobny przycisk).

## [0.6.13] — 2026-09-10

### Naprawiono
- **Duplikaty po konwersji na CHD (zip/bin/cue obok chd) — sprzątane OD RAZU.**
  W katalogach dyskowych (np. 3DO: 241× zip+chd, Dreamcast: bin/cue+chd) po
  konwersji zostawały pozostałości tej samej gry. Powód: sprzątanie do ToSort/
  dedup działa DOPIERO na końcu `Napraw` i jest POMIJANE przy „Przerwij" — a
  przebiegi bywały przerywane. Teraz `convert_from_source` po zbudowaniu CHD robi
  cykl czyszczący PER GRA (odporny na przerwanie):
  - kasuje REDUNDANTNE archiwum `<gra>.zip/.7z` w katalogu docelowym, gdy
    `<gra>.chd` jest ZWERYFIKOWANY (`data_sha1 == game_profile`) i tory danych
    archiwum ⊆ tory gry (bezpiecznik: nie rusza nadzbioru/cudzego archiwum),
  - kasuje LUŹNE tory `.bin/.cue/.gdi` tej gry (Dreamcast itp.), gdy jest na CHD,
  - nie rusza sum jeszcze POTRZEBNYCH innym grom (`needed_sha1`); FIZYCZNY dowód
    istnienia CHD przed skasowaniem; `dry_run` tylko „(podgląd)".
  Nowa metoda `FileIndex.members_of`; helpery `_disc_on_verified_chd` /
  `_purge_redundant_target_archives`.

## [0.6.12] — 2026-09-10

### Zmieniono
- **Liczba równoległych konwersji konfigurowalna; domyślnie 4** (było auto ≈ 8).
  8 naraz bywa za dużo (strumienie I/O na NAS, zajętość RAM-dysku). Nowe ustawienie
  `convert_workers` (Settings): `0` = auto (min(8, rdzenie//2)), inaczej dokładna
  liczba. Domyślnie **4**. Można stroić bez przebudowy (brak klucza w JSON →
  przyjmuje domyślne 4; zapis dopisze pole).

## [0.6.11] — 2026-09-10

### UI
- **Osobny pasek postępu na KAŻDĄ równoległą konwersję** (jak przy skanowaniu CHD).
  Dotąd 8 równoległych kompresji dzieliło JEDEN pasek `detail` (skakał, nie było
  widać ile realnie idzie). Teraz każdy wątek build ma swój SLOT (0..N-1) i własny
  pasek „Pliki liczone równolegle:" w oknie postępu:
  - `StagePipeline`: każdy wątek build dostaje numer slotu; przekazywany do fazy
    build przez `payload["_pipe_slot"]` (bez zmiany generycznego kontraktu).
  - `_conv_build_phase(slot=…)`: postęp kompresji idzie na własny slot; slot
    zwalniany (pasek chowany) po zakończeniu zadania.
  - Zadanie naprawy przyjmuje sygnał `slot` (5. parametr) i przekazuje go do
    `convert_from_source`. Tryb seryjny nadal używa wspólnego paska `detail`.

## [0.6.10] — 2026-09-10

### Naprawiono
- **Dedup TYLKO w obrębie platformy + katalog-rodzic zawsze fizyczny.** Wykryto na
  realnej kolekcji: 3 pary gier o BAJT-IDENTYCZNEJ treści na RÓŻNYCH platformach
  (MSX↔Master System „Super Boy", Master System↔Mega Drive „Phantasy Star",
  PS3 PSN DLC↔Updates „Lair"). Dotąd dedup działał GLOBALNIE po odcisku treści
  (`game_profile`) i jedna z par stawała się cross-platformowym SYMLINKIEM do
  drugiej (SMS→MSX) — „wojna między katalogami". Reguła usera: **wszystko w
  katalogu oznaczonym `parent_priority` (np. ROMS) ZAWSZE fizyczne, nawet
  identyczna treść na różnych platformach; linkują tylko katalogi-DZIECI (np.
  1G1R) do rodzica; tłumaczenia osobno.** Zmiany:
  - `convert.py`: klucz dedup = **(platforma, odcisk)** zamiast samego odcisku;
    gra z katalogu-RODZICA (`parent_priority`) **nigdy nie linkuje** (zawsze
    konwertuje/zostaje fizyczna) — dotyczy ścieżki „ze źródła", HAVE_CHD relink
    i CHD z archiwum. Rejestracja keepera nadal działa, by DZIECI mogły linkować.
  - `rebuilder.py`: placement (`_process`) — gra rodzica dostaje WŁASNĄ kopię
    fizyczną zamiast symlinku do innej kolekcji; dedup (`_dedup_confirmed`) —
    gdy OBIE kopie są w katalogu-rodzicu, obie zostają fizyczne (`parent_prefixes`).
  - Efekt na kolekcji usera: po zawężeniu do platformy zostaje **1** kolizja
    (PS3 PSN, oba w rodzicu) → **oba fizyczne, ZERO linków**; reszta (136k+ gier)
    bez zmian. Prawdziwy dedup dziecko→rodzic (1G1R, ta sama platforma) działa jak
    dotąd.

## [0.6.9] — 2026-09-10

### Naprawiono
- **Potok równoległy: bramka PER GRA zamiast „wszystko albo nic".** W 0.6.8 potok
  włączał się tylko gdy w CAŁEJ partii NIE było ani jednego współdzielonego odcisku
  (`any(c > 1)`). W praktyce wystarczał JEDEN kolizyjny fingerprint (np. wpisy
  arcade/GD-ROM Naomi z identycznymi torami, zdublowana gra) i cały przebieg spadał
  na konwersję SERYJNĄ — łącznie z dyskami CD 3DO/PS1/Saturn, które można robić 8
  naraz. Objaw u usera: 0.6.8 mimo „8 równoległych" konwertowała pojedynczo
  (`KONWERSJA(ze źródła)→CHD` po kolei). Teraz:
  - Potok jest **ZAWSZE włączony** (gdy jest budżet RAM-dysku).
  - Seryjnie (blokująco) idą **tylko gry ze WSPÓŁDZIELONYM odciskiem** — rodzic
    grupy rodzic→dziecko, żeby dziecko linkowało do FIZYCZNIE gotowego pliku
    rodzica (potok finalizuje poza kolejnością i ustawia ścieżkę finału PRZED
    sukcesem, więc link mógłby wisieć). `final_by_profile` dla takiego rodzica
    ustawiane dopiero PO sukcesie konwersji.
  - Cała reszta (UNIKATOWE odciski — typowe dyski CD) leci **potokiem 8-równolegle**.
  - Gdy wybrane są same DAT-y „rodzice" (bez relacji dziecko/rodzic) → zero kolizji
    → wszystko równolegle.

## [0.6.8] — 2026-09-10

### Wydajność
- **Potok konwersji RÓWNOLEGŁY — N konwersji naraz.** Diagnoza usera (CPU 3%,
  skoki do 90% co 2–3 s, LAN i RAM też falują): jedna konwersja na raz nie sycił
  zasobów, zwłaszcza MAŁE gry na CD (3DO/PS1/Saturn) — jeden chdman ledwo
  drażni CPU/sieć. Teraz `StagePipeline` ma **N wątków build** (chdman/DolphinTool)
  zamiast jednego:
  - Liczba równoległych konwersji = ~połowa rdzeni logicznych, maks. 8 (na maszynie
    usera: 8 rdzeni wydajnych bez HT + 12 energooszczędnych → **8 konwersji**).
  - **Każda konwersja dostaje 1 wątek chdman (`-np 1`)** — 8 konwersji ≈ 8 rdzeni
    WYDAJNYCH, zamiast jednej gry ciągnącej wszystkie rdzenie i reszty czekającej.
    Bez przeciążenia (nie 8 × wszystkie rdzenie).
  - **Finalizacja poza kolejnością** (`ordered=False`): potok włącza się TYLKO gdy
    brak współdzielonych odcisków (żadne dziecko nie linkuje do rodzica → zero
    zależności rodzic→dziecko), więc zadania można finalizować w kolejności
    ukończenia, nie zgłoszenia. Finalizacja (indeks/SQLite, kasowanie źródeł) nadal
    WYŁĄCZNIE w wątku właściciela (SQLite jednowątkowe) — równoległa jest tylko
    kompresja i I/O.
  - **Budżet RAM-dysku** dalej ogranicza, ile realnie biegnie: `feed()` rezerwuje
    `cost` per gra, więc duża gra idzie sama, a małe nakładają się do wyczerpania
    budżetu R:. Tryb szeregowy (`build_workers=1, ordered=True`) bez zmian — pełna
    zgodność wsteczna (rodzic→dziecko przy współdzielonych odciskach).

## [0.6.7] — 2026-09-08

### Wydajność
- **Sprawdzanie CHD (`deep_probe_chds`) RÓWNOLEGŁE.** Diagnoza z telemetrii usera
  (CPU 7%, sieć 50%, RAM = ramdysk): żaden zasób nie wysycony → wąskim gardłem
  była SERIALIZACJA i pojedynczy strumień SMB (round-tripy: otwórz → czytaj
  nagłówek/wypakuj → następny, po kolei). Pętla sondy była ściśle szeregowa.
  Teraz dwustopniowo i równolegle:
  - **(A) tani nagłówek** (`chdman info` — mały odczyt, dopasowanie `data_sha1`)
    idzie pulą wątków wg nośnika (NAS 8 / SSD 4 / HDD 1 — kilka strumieni SMB
    wypełnia łącze; RAM≈0),
  - **(B) głęboka ekstrakcja** (`deep_identify` — pełny obraz na scratch/RAM-dysk)
    równolegle, ale ograniczona liczbą, która MIEŚCI się na RAM-dysku
    (`deep_workers = wolne_na_ramdysku // 9 GB`, min. 1) — chroni przed
    zapchaniem; wybór/remount scratchu pod lockiem (bez wyścigu o RAM-dysk).
  - **Zapisy do indeksu (SQLite jednowątkowy) tylko w wątku wołającym** — wątki
    liczą i zwracają wynik (bez wyścigu bazy). Każda głęboka ekstrakcja pisze do
    UNIKALNEGO podkatalogu (`mkdtemp`), więc równoległość jest bezpieczna.
  - **Pasek per plik** (slot 0..deep_workers-1) dla równoległych ekstrakcji.
  - Przerwanie responsywne (cancel co futuru); porażki głębokiej identyfikacji
    nadal zapamiętywane (`deep_fail`), rozpoznane z cache pomijane.
  Wynik dopasowania IDENTYCZNY jak w wersji szeregowej (te same sumy, te same
  stany) — zmiana czysto wydajnościowa. CLI bez zmian (domyślnie 1 wątek).
- **Domyślny RAM-dysk 30 → 40 GB.** User ma 64 GB RAM z zapasem → większy scratch
  mieści więcej równoległych ekstrakcji CHD. RAM-dysk odmontowywany przy
  zamknięciu → następny start tworzy świeży 40 GB.
- **Głęboka ekstrakcja: BUDŻET scratcha zamiast sztywnej liczby wątków** — każda
  ekstrakcja rezerwuje tyle miejsca, ile REALNIE potrzebuje (~2 GB gra CD, ~9 GB
  DVD), a nie sztywne 9 GB/wątek. Sztywny dzielnik zaniżał do 1–2 równoległych
  przy małych grach CD (user widział „tylko 2 naraz"), choć R: miał dziesiątki GB
  wolne. Teraz w tym samym budżecie mieści się ~6 małych gier naraz (więcej
  strumieni z NAS → wyżej LAN). **Budżet = WOLNE MIEJSCE NA RAM-DYSKU R:** (do
  ~rozmiaru ramdysku), NIE wolny fizyczny RAM: RAM-dysk ma DEDYKOWANĄ pamięć
  (proces System trzyma jego rozmiar), więc zapis w wolne miejsce R: reużywa już
  przypisanego RAM-u i nie uszczupla „Dostępnej". (Pośrednia wersja liczyła
  `avail_phys` i dławiła do ~2, bo podwójnie liczyła pamięć oddaną ramdyskowi —
  poprawione.) Admisja przez `threading.Condition`; gra większa niż budżet idzie
  sama (bez zakleszczenia). Górny cap współbieżności = liczba wątków nagłówka.

### Wydajność (konwersja)
- **Potok konwersji (nakładanie NAS I/O na kompresję) włączał się prawie nigdy.**
  Warunkiem był dysk z „największa gra × 10" wolnego — przy jednej wielkiej grze
  (PS2 ~34.8 GB → 348 GB) żaden dysk tyle nie miał → potok OFF → konwersja czysto
  seryjna (pobierz→kompresuj→wyślij po kolei, NAS i CPU na zmianę). Odłączono
  potok od ×10: teraz włącza się na **budżecie RAM-dysku**, a **scratch dobierany
  PER GRA** (RAM gdy gra się mieści, inaczej dysk fizyczny — duże PS2 nie
  przepełnią R:). StagePipeline rezerwuje per-zadanie (gra > budżet idzie sama),
  więc małe gry (3DO/PS1/CD) nakładają pobieranie/wysyłkę na kompresję → realnie
  szybciej na NAS. Wyłączenie potoku tylko przy współdzielonych odciskach
  (dziecko→rodzic) — bez zmian (bezpieczeństwo kolejności). Zniknął mylący gate
  „Budżet miejsca ×10 = 348 GB".

### Naprawione (format)
- **PC Engine HuCard (kartridż `.pce`) szło na CHD i było POMIJANE.** `auto`
  mapował system „PCENGINE" na CHD (jest w DISC_SYSTEMS), ale PC Engine ma DWA
  media pod jednym skrótem: HuCard (kartridż) i CD. Każdy `.pce` trafiał w ścieżkę
  CHD i lądował na „POMIJAM: brak cue" → gry nie były układane. Fix: `auto` dla
  systemu płytowego sprawdza TREŚĆ DAT-u (`_dat_is_cartridge`) — brak plików
  płytowych (cue/iso/gdi/toc/chd) → ZIP; są płyty → CHD. Działa dla obu DAT-ów PC
  Engine (HuCard→ZIP, CD→CHD) bez ręcznej konfiguracji.

### Wydajność / stabilność
- **„Start…" Naprawy stał ~2 min w ciszy i blokował wyjście z programu.** W fazie
  wstępnej REALNej Naprawy leciały DWA pełne `os.walk` po całej kolekcji na NAS
  (100k+ plików), bez cancel i prawie bez logu: `purge_temp_artifacts` (śmieci po
  konwersjach) i `remove_broken_links` (zerwane symlinki). Stąd „Start…" wisiał, a
  Przerwij nie działał (worker nie sprawdzał cancel) — proces zostawał żywy po
  zamknięciu okna, bo wątek nie kończył się. Poprawki:
  - **Zamiatanie temp TYLKO na scratchu** (RAM-dysk / scratch_dir / work_dir) —
    duże śmieci po przerwanych konwersjach żyją TAM, nie w kolekcji; pełny walk po
    NAS-owej kolekcji był bez sensu (drobne resztki w katalogach docelowych i tak
    nadpisze ponowna konwersja / wyłapie skan).
  - **`remove_broken_links` PO INDEKSIE** — `exists()` woła się tylko na znanych
    linkach (is_link), nie na każdym z 100k plików; fallback os.walk gdy brak
    indeksu.
  - **Cancel + heartbeat** w obu — Przerwij działa od razu, faza pokazuje postęp,
    proces wychodzi czysto po zamknięciu.

### Bezpieczeństwo
- **Pewność naprawy PRZED kasowaniem z ToSort (fizyczne potwierdzenie kopii).**
  Kasowanie luźnych kopii z ToSort (`_dedup_confirmed`) już wcześniej sprawdzało,
  że plik kanoniczny FIZYCZNIE istnieje (`is_file`) — teraz TA SAMA gwarancja w
  purge'u ARCHIWÓW (`_content_placed_outside`): w REALNEJ naprawie archiwum ToSort
  jest kasowane tylko, gdy `lexists` potwierdzi, że kopia treści realnie leży w
  kolekcji (nie tylko wg indeksu). W dry-run bez tego stat-u (podgląd nic nie
  kasuje). Kolejność bezpieczna: placement/konwersja → dopiero potem purge ToSort;
  źródła konwersji ze źródła kasowane na SAMYM KOŃCU (po całej naprawie).
- **Dry-run („Znajdź naprawy") wyraźnie oznaczony jako podgląd.** Linie kasowania
  z ToSort dostały prefiks „(podgląd)" w dry-run (dawniej pisały samo „KASUJ",
  choć nic nie kasowały) — audyt potwierdził, że KAŻDA operacja plikowa rebuildera
  honoruje dry_run (mkdir/move/symlink/unlink/replace/copy/extract/dedup/purge).

### Naprawione
- **Faza „sprzątanie ToSort (zbędne archiwa)" wyglądała na zawieszoną.**
  `_purge_redundant_tosort_archives` sprawdzała tysiące archiwów ToSort BEZ
  własnego paska — bar stał na 100% z fazy dedup, więc przy dużym ToSort (dziesiątki
  tys. archiwów) „Znajdź naprawy" wyglądało na zwis (user: „program stoi"). Dodano
  postęp „sprzątanie ToSort (zbędne archiwa) X/Y" (dwuprzebiegowo: zbierz archiwa
  → sprawdzaj z licznikiem) i responsywne przerwanie (cancel co archiwum).
- **Spurious „KONFLIKT: <gra>.chd zajęte zwykłym plikiem" dla CHD ze złym
  kontenerem (bad_container).** Gry DVD zrobione jako CD (createcd) mają plik .chd
  NA MIEJSCU (kanoniczna ścieżka), zły jest tylko kontener. Rebuilder próbował je
  w placemencie „umieścić"/zlinkować → setki spurious KONFLIKT-ów (a linku i tak
  nie wolno robić w katalogu-rodzicu). Fix: `_process` POMIJA bad_container w
  placemencie (zostawia plik na miejscu) — naprawia je ZINTEGROWANY z Naprawą krok
  `rebuild_bad_chds` (przekontenerowanie CD→DVD w miejscu, tuż po placemencie).
  Nowy licznik `RebuildStats.bad_container` w podsumowaniu.
- **„Znajdź naprawy"/Naprawa stała minutami (O(gry²) na katalogach CHD).**
  `_purge_child_loose_duplicates` (sprząta luźne tory dziecka gdy gra jest na CHD)
  robił `index.all_under(target_dir)` PER GRA via_chd — dla katalogu z tysiącami
  CHD (PS1/PS2/Saturn/Dreamcast) to O(gry²) zapytań: ~3 min zanim pokazała się
  pierwsza pozycja i kolejne „przystanki" między platformami. Fix: mapa
  sha1→[ścieżki] luźnych plików budowana RAZ per katalog docelowy (cache
  `_loose_by_sha1`) i reużywana przez wszystkie gry tego katalogu → O(gry).
- **Konwersja/Naprawa: scratch szedł na dysk budżetu (NAS Z:), nie na RAM-dysk —
  błędne „348 GB potrzeba".** Reguła „×10 największej gry" (jednorazowa decyzja
  „nie pytać o miejsce per gra") była zlana z WYBOREM lokalizacji scratcha:
  `_conv_scratch_for` zwracał od razu dysk z budżetu (który musiał mieć
  największa×10 = np. 34.8 GB×10 = 348 GB → tylko NAS Z:), więc NAWET mała gra
  budowała się na NAS zamiast na RAM-dysku (log: „RAM dysk R:\ ZA MAŁY — 39.9 GB
  < 348.1 GB potrzeba"). Fix: scratch liczony PER GRA (`rozmiar × (factor+1)`),
  RAM-dysk w priorytecie gdy gra się mieści; dysk z budżetu to tylko FALLBACK dla
  gier ZA DUŻYCH na RAM. Reguła ×10 nadal działa jako gate „nie pytam per gra",
  ale nie wymusza już lokalizacji.
- **Scratch CHD lądował na NVMe zamiast na RAM-dysku (nic nie szło na R:).**
  `pick_scratch_root` szuka ramdysku WYŁĄCZNIE przez `ramdisk.active_root()`, a
  ta zwracała None, gdy `_ACTIVE` nie było ustawione w procesie skanu (create()
  szedł w tle i skan ruszył wcześniej; albo relaunch elewacji zaczynał od nowa) —
  mimo że R: był zamontowany. chdman dostawał wtedy ścieżkę na NVMe i pisał tam
  wielkie temp (user: „nic nie ląduje na R:, wielki plik w temp"). Fix:
  `active_root()` gdy `_ACTIVE` puste WYKRYWA zamontowany RAM-dysk po zapamiętanej
  literze (R: istnieje + zapisywalny → uznaj za aktywny i zapamiętaj). Dzięki temu
  scratch wraca na RAM-dysk niezależnie od momentu/procesu.
- **Przerwanie sondy CHD zatrzymywało tylko JEDNĄ ekstrakcję — reszta jechała
  dalej w tle.** `deep_probe` na przerwaniu robił `shutdown(wait=False)` i wracał
  natychmiast: dopasowanie startowało nad wciąż żywymi ekstrakcjami, a przy
  zamknięciu programu ramdysk bywał zajęty (chdman-y nie zdążyły się zamknąć).
  Teraz na przerwaniu CZEKAMY (`wait=True`) aż wszystkie wątki w locie się
  zatrzymają — chdman jest zabijany od razu (`_stream` sprawdza cancel co linię),
  `deep_identify` przerywa pętlę metod, więc kończą się w sekundy; kolejkowane
  (`cancel_futures`) porzucane. Dopasowanie rusza dopiero po realnym zatrzymaniu.
- **~2-min „zamrożenie" GUI na starcie sondy CHD (faza nagłówków).** Przy dużej
  kolekcji CHD, gdy nic nie trafiało tanim nagłówkiem (np. PS2-jako-CD nie pasuje
  do DVD-DAT → wszystko szło w deep), pass `chd.info` (8 wątków, odczyt nagłówków
  z NAS) trwał minutami BEZ postępu w GUI (dyski NAS na maxa, pasek stał). Dodano
  osobny postęp fazy nagłówków („nagłówki CHD X/Y") i głębokiej („głęboka
  identyfikacja CHD X/Y") — widać, że trwa.
- **Zbędny `prune_ghosts` w fazie priorytetowej (tysiące lexists na NAS).** Przy
  wyborze jednej platformy prune duchów biegł PRZED sprawdzeniem kompletności, a
  gdy platforma była niekompletna, pełny skan i tak robił własny prune → podwójna
  praca (na NAS ~1–2 min). Teraz prune fazy priorytetowej tylko gdy platforma
  wyjdzie KOMPLETNA (kończymy bez pełnego skanu); inaczej robi go pełny skan.
- **`prune_ghosts` mielił 100k+ wpisów na NAS przy skanie PODZBIORU platform.**
  Gdy skanowano tylko kilka platform, indeks miał 100k+ wpisów SPOZA skanowanych
  korzeni (inne platformy z trwałego indeksu) → `lexists` per PLIK = 100k+ zapytań
  SMB w ciszy (skan „stał"). Teraz sprawdzanie PO KATALOGACH (memoizacja): duch =
  zniknięty KATALOG/korzeń, każdy katalog `lexists` raz. Redukuje zapytania z
  liczby PLIKÓW do liczby KATALOGÓW. Pojedynczy skasowany plik w istniejącym,
  nieskanowanym katalogu złapie skan tego katalogu (`_mark_missing`).
- **Przeplot logów równoległej sondy CHD.** Linie z `deep_identify` (Próba/✔/✗)
  z kilku wątków przeplatały się bez nazwy pliku — „✔ == DAT 'X'" wyglądała, jakby
  należała do sąsiedniego „CHD głęboko: Y". Dodano prefiks `[nazwa.chd]` do każdej
  podlinii w trybie równoległym → log jednoznaczny i weryfikowalny (dopasowanie
  plik→gra było i jest poprawne; problem był wyłącznie w czytelności logu).
- **RAM-dysk tworzony jako RAW (bez formatu) — trzeba było formatować RĘCZNIE.**
  Po udanym `imdisk -a` kod uznawał R: za gotowy na podstawie samego write-probe;
  goły `imdisk.exe` (bez ImDisk Toolkit) IGNORUJE `-p /fs` i zostawia dysk RAW, a
  probe potrafi „przejść" na świeżym woluminie, który Explorer i tak pokazuje jako
  RAW/bez pojemności. Teraz create() po udanym `-a` czeka tylko aż URZĄDZENIE się
  pojawi, a potem ZAWSZE formatuje jawnie (`Format-Volume`, na pustym ulotnym
  dysku szybki) i uznaje R: za gotowy dopiero po udanym formacie (inaczej ponawia
  / fallback na dysk fizyczny). „Twórz od razu z formatowaniem".
- **RAM-dysk nie znikał przy zamknięciu, gdy R: był jeszcze zajęty.** `remove()`
  wołał `imdisk -D` bez sprawdzania wyniku — gdy po świeżo zakończonych 4
  równoległych ekstrakcjach na R: wisiały jeszcze uchwyty/procesy chdman,
  wymuszony detach „odbijał się", a błąd był POŁYKANY → R: zostawał zamontowany.
  Teraz `remove()` sprawdza kod wyniku i istnienie woluminu, PONAWIA (do 3× z
  krótką przerwą) i loguje wynik. Gdy się nie da (uchwyty własnego, jeszcze
  niezakończonego procesu) — zwolnią się przy wyjściu, a następny start i tak
  przejmie/sformatuje istniejący R: (create() obsługuje reuse/RAW).

## [0.6.6] — 2026-09-08

### Sprzątanie (bez zmiany zachowania)
- Usunięto martwy kod w `core/convert.py`: nieużywana funkcja `_free_bytes`
  (0 wywołań w repo) oraz 3 zbędne lokalne importy (`hashlib` w
  `_gather_track_to_ram`; `shutil`/`tempfile` w `convert_from_source` — po
  refaktorze na fazy `_conv_*`). pyflakes czysty; 262 testy bez zmian.

## [0.6.5] — 2026-09-08

### Naprawione
- **Skan „stał i nic nie robił" po ToSort (na NAS) — naprawa.** Po zeskanowaniu
  wszystkich katalogów `prune_ghosts` robił `lexists` po CAŁYM indeksie (100k+
  wpisów) — na dysku sieciowym to 100k+ zapytań SMB w CISZY (bez postępu), przez
  co skan wyglądał na zawieszony i nie kończył się. A to redundantne: skan
  per-katalog (`_mark_missing`) już oznaczył braki w odwiedzonych katalogach.
  Teraz `prune_ghosts(skip_roots=…)` POMIJA wpisy pod świeżo przeskanowanymi
  katalogami i sprawdza tylko te SPOZA (realne duchy po zniknięciu korzenia) —
  z widocznym postępem. Test `test_prune_ghosts_skips_scanned_roots`.

## [0.6.4] — 2026-09-08

### Dodane
- **Zamiatanie zaległych `_MEI*` z %TEMP% przy starcie.** Warning „Failed to
  remove temporary directory: _MEI…" pochodzi z auto-podnoszenia do admina:
  pierwsza (nie-admin) instancja onefile rozpakowuje `_MEI`, natychmiast
  relaunchuje się jako admin i ginie — bootloader nie zdąża skasować `_MEI`
  (w onefile nieusuwalne). Zostajemy przy onefile (wybór usera), ale przy każdym
  starcie sprzątamy STARE `_MEI*` z Temp: pomijamy BIEŻĄCY `_MEIPASS` i te
  zablokowane przez żywą instancję (rmtree pada → zostawiamy) — więc nie
  zalegają. Tylko w buildzie (`main._sweep_stale_mei`, no-op w źródłach).

## [0.6.3] — 2026-09-08

### Zmienione
- **Czyste domknięcie pracy w tle przy zamykaniu okna** (diagnoza `Failed to
  remove temporary directory: _MEI…`). Zamknięcie, gdy wciąż działa skan/
  konwersja (wątek + podproces chdman/imdisk), kończyło proces „nieczysto" i
  bootloader PyInstaller nie mógł skasować katalogu `_MEI…`. Teraz `closeEvent`
  prosi o przerwanie i CZEKA na zakończenie zadań (do 10 s), zanim wyjdzie —
  pliki są zwolnione czysto. Do logu trafia diagnostyka: ile zadań wciąż działa,
  żywe wątki i ścieżka `_MEI`, by namierzyć ewentualną blokadę. (Zostajemy przy
  onefile; jeśli warning będzie się powtarzał mimo tego — rozważymy onedir.)

## [0.6.2] — 2026-09-08

### Naprawione
- **RAM-dysk R: tworzony jako RAW (niesformatowany) → naprawa.** Objaw: „ImDisk
  zwrócił 3: Za mało zasobów pamięci" w pętli prób, a R: kończył jako
  niesformatowany — mimo 64 GB RAM (to NIE była realna n/pamięć). Przyczyna:
  zaległy wolumin RAW na literze R: (po crashu/nieudanym formacie, m.in. z
  auto-remountu 0.6.1) blokował literę; `imdisk -a` na zajętą literę zwraca
  mylący błąd 3, a stary kod próbował tylko tworzyć od nowa (w kółko). Teraz:
  gdy R: istnieje jako urządzenie ImDisk, ale jest RAW → **formatujemy je**
  (`Format-Volume`, bez promptów) zamiast tworzyć na zajętej literze; po świeżym
  `imdisk -a`, jeśli `-p /fs` nie sformatował (goły imdisk.exe bez Toolkitu) —
  formatujemy sami. Cofnięto błędne zmniejszanie rozmiaru RAM-dysku „z powodu
  pamięci" (30 GB przy 64 GB RAM jest OK). Testy `test_ramdisk_formats_existing_raw`
  + zaktualizowane retry/give-up.
- **Krzaki w logu z ImDisk → polskie znaki.** Wyjście ImDisk dekodujemy teraz
  jako OEM (konsolowa strona kodowa, cp852), a nie UTF-8 — koniec „Za ma�o
  zasob�w".

## [0.6.1] — 2026-09-08

### Naprawione
- **Znikający RAM-dysk w trakcie nie wywala już skanu/naprawy.** Gdy ImDisk
  odmontuje RAM-dysk (R:) w środku operacji, `pick_scratch_root` wcześniej zdążył
  go wybrać, a chwilę później `mkdtemp` padał: `[WinError 3] … R:\chdbuddy_scratch
  \chddeep_…`. Teraz katalog roboczy jest tworzony TUŻ przed użyciem, a gdy się nie
  da (scratch zniknął) — operacja spada na SYSTEMOWY temp (dysk fizyczny) i leci
  dalej, zamiast rzucać wyjątkiem. Dotyczy głębokiej identyfikacji CHD
  (`deepcheck.deep_identify`) i fazy pobierania konwersji (`_conv_gather_phase`).
  Kolejne pliki i tak same wybiorą dysk fizyczny (`ramdisk.active_root()` po
  zniknięciu R: zwraca None). Test `test_deep_identify_survives_scratch_vanishing`.
- **Auto-odtwarzanie RAM-dysku, gdy zniknie w trakcie.** Zamiast od razu schodzić
  na temp fizyczny, przy zniknięciu R: próbujemy raz go ODTWORZYĆ z zapamiętanych
  parametrów (`ramdisk.remount` — rozmiar+litera z ostatniego `create`), by
  odzyskać szybkość RAM na resztę przebiegu; dopiero gdy się nie uda — systemowy
  temp. Wspólny helper `scratch.resilient_dir(preferred)` (używają go deep-probe
  i konwersja): utwórz `preferred` → odtwórz RAM → temp fizyczny.

## [0.6.0] — 2026-09-07

### Dodane
- **Potokowa konwersja (pobierz → konwertuj → wyślij), jak potok w CPU.** Gdy plik
  N jest wysyłany na NAS, kolejny (N+1) już się konwertuje, a następny (N+2)
  pobiera. Na dysku sieciowym ukrywa latencję I/O pod konwersją CPU — w stanie
  ustalonym czas/plik ≈ max(pobranie, konwersja, wysyłka) zamiast sumy.
  - Konwersja zawsze 1 na raz (chdman/DolphinTool i tak biorą wiele rdzeni);
    nakładane są tylko POBIERANIE i WYSYŁANIE (I/O) na KONWERSJĘ (CPU).
  - Nowy `core/convert_pipeline.py` (`StagePipeline`): 3 etapy jako łańcuch kolejek
    FIFO → wynik zachowuje kolejność zgłoszeń; FINALIZACJA (zapisy do indeksu/
    SQLite, kasowanie źródeł) WYŁĄCZNIE w wątku właściciela (SQLite jednowątkowe);
    BUDŻET RAM (bajty) — pobieranie czeka, aż zwolni się miejsce.
  - Konwersja rozbita na fazy `_conv_prepare`/`_conv_gather_phase`/
    `_conv_build_phase`/`_conv_upload_phase`/`_conv_finalize_phase` (te same fazy
    napędzają serial i potok — zero rozjazdu logiki).
  - **Bezpiecznie:** potok włącza się TYLKO gdy jest budżet RAM (scratch) i BRAK
    współdzielonych odcisków treści (żadne dziecko nie linkuje do rodzica w tym
    przebiegu → zero zależności kolejnościowych). Inaczej — konwersja SERYJNA jak
    dotąd. Nieudane zadanie cofa się z „done" → fallback placement je dokończy.
  - Testy: `test_convert_pipeline.py` (kolejność, budżet RAM, pomijanie, wait,
    cancel) + `test_convert_from_source_pipeline_many_games` (6 gier end-to-end).

## [0.5.8] — 2026-09-07

### Zmienione
- **Wolne miejsce sprawdzane RAZ na całą naprawę, nie per gra.** Zmiana nazwy/
  katalogu (rebuilder) miejsca NIE potrzebuje — pyta tylko KONWERSJA (budowa
  CHD/RVZ/ZIP na scratchu, zwykle RAM). Teraz na starcie naprawy liczymy
  NAJWIĘKSZĄ grę i sprawdzamy scratch RAZ: jeśli zapas ≥ największa ×10 (mieści
  się nawet równolegle), NIE pytamy o miejsce per gra (`scratch_override`).
  Dopiero gdy ciasno — wracamy do sprawdzania per gra (bezpiecznie). Eliminuje
  resztę wolnych zapytań `disk_usage`/`prefer=NAS` w realnej naprawie
  (`convert_from_source` liczy budżet raz; `_convert_game_from_source` go
  używa). W RAM-dysku mieszczącym budżet — zero zapytań do NAS o miejsce.

## [0.5.7] — 2026-09-07

### Naprawione
- **„Znajdź naprawy" nie zacina się już na dysku sieciowym (NAS/SMB).** Podgląd
  (dry-run) robił PER GRA blokujące zapytania do NAS, co dawało „co chwilę się
  zatrzymuje i wygląda na zawieszony". Usunięto dwa źródła:
  1. **Zapytanie o wolne miejsce** (`pick_scratch_root` → `disk_usage`) było
     wołane per gra także w podglądzie — teraz TYLKO przy faktycznej naprawie
     (w podglądzie sam plan, bez sprawdzania miejsca).
  2. **`os.path.isfile`/lstat własnego CHD** per gra CHD (tysiące gier PS2/PSX =
     tysiące zapytań SMB) — teraz stan czytany z INDEKSU (lokalny SQLite, świeży
     po skanie); faktyczny relink i tak re-weryfikuje obecność i treść rodzica
     przed jakąkolwiek zmianą (bezpieczeństwo bez zmian).

## [0.5.6] — 2026-09-07

### Naprawione
- **Gry jednoplikowe w podfolderze per gra są HAVE, nie „do naprawy"/konwersja.**
  Kolekcje trzymane jako `<katalog>/<gra>/<gra>.rvz` (np. 610 RVZ GameCube, układ
  RomVault) świeciły na WRONG_NAME, a konwersja logowała „KONWERSJA(ze źródła)→
  RVZ" (choć pliki są poprawne, tylko w podfolderze). Teraz plik gry
  JEDNOPLIKOWEJ w katalogu nazwanym DOKŁADNIE jak gra jest uznawany za poprawnie
  umiejscowiony (HAVE). Gry wieloplikowe bez zmian (układ steruje `subdir_per_game`).
  `matcher.match_rom(game_single=…)`; test
  `test_single_file_game_in_pergame_subfolder_is_have`.
- **„Znajdź naprawy" nie zacina się już na poprawnych plikach w podfolderach.**
  Skutek uboczny powyższego: te gry (HAVE) są pomijane w konwersji, więc znika
  wolne zapytanie o miejsce na NAS per gra, które powodowało „co chwilę
  zatrzymuje się i wygląda na zawieszony".

## [0.5.5] — 2026-09-06

### Naprawione
- **„Przerwij" reaguje NATYCHMIAST, także w środku wielkiego pliku.** Dotąd
  `hash_file` czytał multi-GB plik (CHD/ISO/RVZ) bez sprawdzania przerwania, więc
  klik „Przerwij" nie działał, aż plik się doczytał. Teraz cancel sprawdzany co
  blok (4 MiB) → `HashAborted`. W trybie równoległym pula porzuca zadania od razu.
- **Widać postęp na wielkich plikach RVZ/CHD w trybie równoległym.** Dodanie puli
  wątków (0.5.3) zabrało bajtowy podpostęp; wielkie RVZ „stały". Wrócił —
  patrz niżej (paski per plik).

### Dodane
- **Kilka pasków postępu — po jednym na każdy równolegle liczony plik.** Okno
  postępu pokazuje teraz sekcję „Pliki liczone równolegle" z osobnym paskiem
  (nazwa + %) dla każdego z N wątków skanu. Widać dokładnie, które wielkie pliki
  (RVZ/CHD/ISO) są właśnie liczone i jak szybko. Paski tworzone leniwie, chowane
  po zakończeniu pliku (`ProgressDialog.set_slot`; nowy sygnał `slot`;
  `fileindex.scan(slot_progress=…)` z pulą slotów 0..workers-1). Testy
  `test_hash_file_cancel_aborts`, `test_scan_parallel_reports_slots`.

## [0.5.4] — 2026-09-06

### Dodane
- **Obce (za duże) pliki od razu do ToSort podczas skanu — ale tylko gdy to
  „darmowy" ruch.** Plik surowy większy niż limit platformy jest na pewno „nie
  z tej platformy". Jeśli katalog i ToSort są na TYM SAMYM woluminie, taki plik
  jest przenoszony do ToSort natychmiast (`os.rename` — bez czytania, bez
  hashowania), gdzie zostanie policzony (ToSort bez capa). Jeśli ToSort na INNYM
  woluminie — przeniesienie oznaczałoby wolne kopiowanie, więc plik zostaje na
  miejscu (jak dotąd, tylko nie jest hashowany). Chroni .m3u i linki; kolizje
  nazw → sufiks; każdy ruch w logu (`ScanStats.oversize_moved`,
  `fileindex._move_to_tosort`, `storage.same_volume`; test
  `test_scan_oversize_moves_foreign_to_tosort`).

## [0.5.3] — 2026-09-06

### Dodane
- **Równoległe hashowanie w skanie (pula wątków) — szybszy pierwszy skan na
  NAS/SSD.** Skan czyta kilka plików naraz; na dysku sieciowym (SMB) i SSD/NVMe
  ukrywa to latencję/kolejkę i mocno przyspiesza pierwszy skan TB. Zapis do
  SQLite zawsze w JEDNYM wątku (baza jednowątkowa); przy przerwaniu zadania w
  locie są porzucane i przeliczą się przy kolejnym skanie. Na pojedynczym HDD
  równoległość szkodzi (skakanie głowicy) → 1 wątek. `fileindex.scan(workers=…)`;
  test `test_scan_parallel_matches_serial` (wynik identyczny jak serial).
- **Przełącznik nośnika PER KATALOG na głównym panelu** (Katalog ROM-ów, ToSort):
  Auto / 🌐 NAS/sieć / ⚡ SSD/NVMe / 💽 HDD. Dobiera liczbę wątków skanu dla tego
  katalogu (NAS=8, SSD=4, HDD=1 — konfigurowalne w Settings). „Auto" wykrywa dysk
  sieciowy (typ dysku Windows / ścieżka UNC). Obsługuje scenariusz „baza na NAS,
  późniejsza praca na lokalnym NVMe" — każdy katalog skanowany optymalnie.
  `core/storage.py` (`storage_kind`, `workers_for_kind`); `Settings.
  scan_workers_nas`/`scan_workers_ssd`/`storage_overrides`; testy
  `test_storage_kind_override_and_workers`.

## [0.5.2] — 2026-09-06

### Dodane
- **Limit rozmiaru pliku w skanie (size cap) — szybszy skan dużych kolekcji.**
  Limit liczony PER KATALOG platformy: dla katalogu danej platformy = największy
  ROM DAT-ów, które w niego celują (+margines). Nowy plik surowy większy nie może
  być żadnym z nich (dopasowanie surowego pliku wymaga równości bajtów → równości
  rozmiaru), więc skan go NIE czyta. Dzięki temu skan katalogu kartridżowego
  (Atari 2600, SNES…) odrzuca pliki wielkości płyty NAWET gdy równocześnie
  włączona jest platforma płytowa (PS2) — globalny limit = rozmiar płyty i nic by
  nie odcinał. ToSort i katalogi wspólne dostają limit GLOBALNY (największy ROM
  wśród włączonych), bo trzymają pliki każdej platformy. Nie dotyczy archiwów
  (mogą mieścić wiele małych ROM-ów) ani plików JUŻ znanych (zostają w indeksie,
  nie są oznaczane jako „brak"). `fileindex.scan(max_size=…)`; testy
  `test_scan_max_size_*`. **ToSort skanowany BEZ capa** (worek na wszystko —
  nie wiadomo do jakiego DAT-u trafią pliki, więc pełne, dokładne skanowanie).

### Zmienione
- **Wyniki widoczne po przerwaniu skanu.** Dotąd przerwanie skanu dawało PUSTY
  raport (pętla dopasowania ubijała się od razu). Teraz po przerwaniu skanu i tak
  wykonujemy dopasowanie z cache (szybkie) — od razu widać, co już zebrano.
  Wyraźny komunikat i pasek postępu „⏹ przerwano — dopasowuję zebrane"; przy
  wielkiej kolekcji ta faza może potrwać do ~30 s, można ją przerwać ponownie.

## [0.5.1] — 2026-09-06

### Zmienione
- **Zakres skanu = tylko WŁĄCZONE platformy** (naprawa: skan przemiatał obce
  platformy). Dotąd skan leciał po CAŁYM `rom_root`, więc przy włączonym (checkbox)
  tylko PS1/PS2 i tak skanował pliki RVZ (GameCube/Wii) itd. Teraz skanujemy
  katalogi włączonych platform w OBU konwencjach nazw — Redump (`Sony -
  PlayStation 2`) i EmulationStation (`ps2`, `psx`) — plus ToSort i własne
  `rom_root`-y dzieci; NIE cały `rom_root` (`dirrules.platform_scan_roots`).
  Realne katalogi (ps2/psx) są znajdowane wprost, więc dawny „skan całości" jest
  zbędny. Dopasowanie nadal po TREŚCI; pozostałe platformy mają raport z TRWAŁEGO
  indeksu. Test `test_platform_scan_roots_excludes_other_platforms`.

### Dodane
- **Priorytet skanu dla zaznaczonej platformy.** Gdy w drzewie zaznaczysz
  (podświetlisz) platformę — DAT albo cały katalog-grupę — i klikniesz „Skanuj i
  raportuj", jej katalogi skanowane są NAJPIERW, w OBU konwencjach: skonfigurowany
  cel z reguł (naming/target) jako pierwszy, a jako fallback wariant Redump i
  EmulationStation. Gdy nie ma katalogu wybranej konwencji, ale istnieje drugiej —
  zostaje użyty ten istniejący (`dirrules.platform_scan_dirs`; wybór platformy z
  zaznaczenia: `suite_window._selected_platform_keys`). Rozróżnienie: **checkbox =
  co skanować**, **podświetlenie = priorytet kolejności**.
- **Wczesne zakończenie skanu.** Jeśli podświetlona platforma wyjdzie KOMPLETNA w
  swoich katalogach (wszystkie gry HAVE/HAVE_CHD), reszta nie jest doskanowywana.
  Gdy czegoś brakuje — reszta jest doskanowywana, by znaleźć luźne pliki. Test
  `test_platform_scan_dirs_prefers_configured_then_alt_convention`.
- **Okno pamięta pozycję i rozmiar** między sesjami (`Settings.ui_geometry`,
  `saveGeometry`/`restoreGeometry`) — koniec z ustawianiem okna po każdym starcie.
- **Drzewo DAT-ów pamięta zwinięte grupy** między sesjami
  (`Settings.ui_collapsed_groups`; sygnały `itemExpanded`/`itemCollapsed`) — grupy
  zwinięte raz zostają zwinięte po ponownym uruchomieniu.

## [0.5.0] — 2026-09-05

### Dodane
- **Wykrywanie ZŁEGO KONTENERA CHD w skanie** (gra DVD spakowana jako CD i
  odwrotnie). Dotąd matcher patrzył tylko na TREŚĆ (`data_sha1==profil`), więc
  DVD zrobione przez `createcd` — o ile treść po deframe się zgadzała —
  pokazywało się jako „komplet" i było niewidoczne. Teraz deep-probe zapisuje
  `files.bad_container` (typ kontenera z nagłówka vs medium w DAT), a matcher
  degraduje taki CHD z HAVE_CHD do „do naprawy"; w liście gier nota „🧩 zły
  kontener CHD". Tani check (bez ekstrakcji), raz per plik (kolumna -1/0/1,
  backfill dla już zindeksowanych). Wymaga chdman. Test
  `test_match_flags_bad_container_chd`.
- **Naprawa kontenera wpięta w „Napraw"**: gdy zaznaczone „konwertuj do formatu
  docelowego", „Napraw" uruchamia też `rebuild_bad_chds` (CD→DVD w miejscu +
  CD o złym układzie wg cue) — więc skan wykryje, a naprawa sama poprawi także
  pliki, o których nie wiadomo, że są błędne. Po naprawie flaga `bad_container`
  jest zerowana (raport od razu „komplet"). Osobny przycisk **„Odbuduj CHD wg
  cue"** zostaje do ręcznego uruchamiania poza kolejnością.
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
- **Skan indeksuje CAŁY `rom_root`, nie tylko katalogi docelowe DAT-ów.** Dotąd
  skanowane były wyłącznie foldery wywodzone z nazw DAT-ów (+ ToSort), więc
  kolekcja w układzie ES-style (`ps2`, `psx`, `dreamcast`…) — nieodpowiadającym
  `naming=dat` — była CAŁKOWICIE pomijana (indeks 0 plików pod `Z:\ROMS`, mimo
  tysięcy CHD). Teraz skan bierze korzenie z `scan_roots` (rom_root + rom_root
  z reguł + ToSort) i indeksuje rekurencyjnie — „nieznany plik musi być
  zindeksowany NIEZALEŻNIE od katalogu; dopasowanie jest po TREŚCI".
  (`suite_window._collection_scan`).
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
