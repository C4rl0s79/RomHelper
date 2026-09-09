# Changelog — ROM Kombajn (chd_buddy)

Format: [semver](https://semver.org). Najnowsze na górze.

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

### Naprawione
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
