# Changelog — ROM Kombajn (chd_buddy)

Format: [semver](https://semver.org). Najnowsze na górze.

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
