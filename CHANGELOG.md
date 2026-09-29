# Changelog — ROM Kombajn (chd_buddy)

Format: [semver](https://semver.org). Najnowsze na górze.

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
