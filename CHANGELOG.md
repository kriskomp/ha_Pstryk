# Zmiany

Numeracja wersji: `X.Y.Z`. Wydanie na GitHubie powstaje automatycznie po zmianie wersji w
`manifest.json` na gałęzi `main`, a jego opis to odpowiednia sekcja tego pliku.
Wersje do 2.1.4 włącznie: [oryginał balgerion/ha_Pstryk](https://github.com/balgerion/ha_Pstryk).

Kod polecający Pstryk: **1ML2X7**.

## 2.3.0

- **Zakup na równi ze sprzedażą.** Nowe encje (dane już były w pobieranych odpowiedziach, **bez dodatkowych
  zapytań do API**):
  - `sensor.pstryk_monthly_buy_cost`, `sensor.pstryk_yearly_buy_cost` (PLN),
  - `sensor.pstryk_monthly_energy_bought`, `sensor.pstryk_yearly_energy_bought` (kWh; nazwy „Monthly/Yearly
    Buy Volume”),
  - `sensor.pstryk_buy_total_average` – średnia cena kupna od 01.10.2024 (odpowiednik
    `sensor.pstryk_sell_total_average`),
  - `sensor.pstryk_total_financial_balance` – bilans od 01.10.2024 (koszt zakupu minus przychód ze sprzedaży,
    dodatni = koszt netto, jak w bilansie dziennym, miesięcznym i rocznym),
  - `sensor.pstryk_daily_energy_balance`, `_monthly_`, `_yearly_` – bilans energii w kWh dokładnie tak, jak
    podaje go API Pstryka (pole `energy_balance`; za rok suma miesięcy), bez własnego przeliczania. Ujemny,
    gdy sprzedano więcej niż kupiono. Pole przychodzi w tych samych odpowiedziach co reszta, więc bez nowych
    zapytań. Zaraz po aktualizacji z 2.2.x (dane zapisane przed 2.3.0 go nie mają) te trzy encje mają
    wartość nieznaną do najbliższego pobrania kosztów o pełnej godzinie :05:30.
  Nazwy w szyku „okres → kierunek → wielkość”, ikony według zasady z 2.2.5 (`mdi:transmission-tower` dla
  bilansu energii).
- **Średnie ceny nie zapisują się już do bazy co 30 sekund.** Sześć encji średnich (`sensor.pstryk_buy_daily_average`,
  `_monthly_`, `_yearly_` i odpowiedniki `sell`) nie miało wyłączonego odpytywania (błąd z oryginału), więc Home
  Assistant odświeżał je co 30 s, a zmieniający się atrybut „Last updated” robił z każdego odświeżenia nowy wiersz
  w historii (ok. 17 000 na dobę). Teraz aktualizują się tylko przy nowych danych kosztów, jak pozostałe encje.
- **Dane dzienne pobierane przed miesięcznymi** (start i każde godzinne pobranie). Gdy limit 3 zapytań na
  godzinę ma miejsce tylko na jedno, dostają je encje dzisiejsze; miesięczne, roczne i sumy `total` są
  dociągane przy najbliższym wolnym miejscu. Dotąd było odwrotnie: po świeżej instalacji encje dzienne były puste
  przez ok. godzinę (sprawdzenie klucza, ceny i dane miesięczne zajmowały cały limit).
- **Przejęcie z działającego Pstryk AiO nie sprawdza klucza API osobnym zapytaniem** – AiO właśnie go używa.
  Dzięki temu w pierwszej godzinie mieszczą się ceny, dane dzienne i miesięczne. Klucz AiO, które nie jest
  załadowane (wyłączone, błąd startu), jest sprawdzany jak dotąd.
- **Średnie ceny liczone tylko z energii rozliczonej przez Pstryk** (koszt/przychód > 0): miesiące sprzed umowy mają odczyty licznika, ale zerowy koszt, i zaniżały średnią (np. 0,05 zł/kWh). Wolumeny zostają dosłowne; dane zapisane przez 2.2.x dają średnią nieznaną do następnego przeliczenia kosztów.
- **Wszystkie sześć średnich cen znów włączone domyślnie**, tak jak w oryginale. Wersja 2.2.1 wyłączyła cztery
  (`sensor.pstryk_buy_daily_average`, `_buy_monthly_`, `_buy_yearly_`, `sensor.pstryk_sell_daily_average`) pod
  kątem samej sprzedaży; przy zakupie nie ma do tego powodu. **Po aktualizacji** integracja włącza te
  encje, które wyłączyła sama; wyłączone przez Ciebie ręcznie zostają wyłączone.
- **Kreator przejęcia Pstryk AiO** ([szkocot/Pstryk-all-in-one](https://github.com/szkocot/Pstryk-all-in-one)).
  AiO i ta integracja czytają to samo API (limit 3 zapytań na godzinę), więc nie mogą działać obok siebie.
  Kreator przy dodawaniu integracji (albo w *Konfiguruj → Przejmij Pstryk AiO*, jeśli fork jest już dodany):
  - przejmuje **klucz API z AiO** (bez zapytania, gdy AiO działa; inaczej sprawdzany jednym zapytaniem) – nic
    nie trzeba wpisywać,
  - pokazuje przed zatwierdzeniem, co zrobi, i każe wybrać: przejmij i **wyłącz** AiO, przejmij i **usuń**
    AiO albo nie przejmuj (zwykła konfiguracja); żadna opcja nie jest ustawiona z góry,
  - zatrzymuje AiO (inaczej oba czytałyby API naraz) i **przenosi 14 encji** AiO do forka z zachowaniem
    identyfikatora, nazwy (etykiety), obszaru, historii i statystyk; nazwa i wyłączenie ustawione przez
    użytkownika zostają,
  - **usuwa 2 encje bez zastosowania** („Cena zakupu / sprzedaży prądu (jutro)” – to cena tylko pierwszej godziny
    jutra, a wszystkie godziny są w atrybutach sensorów cen i w sensorach JSON); innych encji AiO nie rusza,
  - jeśli fork był już dodany obok AiO, usuwa jego angielskie encje o tym samym znaczeniu, a w ich miejsce
    wstawia starsze z AiO (dłuższa historia); niczego nie zostawia w stanie pośrednim,
  - nie przejmuje, gdy klucze API różnią się (inny licznik),
  - zostawia podsumowanie w *Naprawach*.
  Opis, tabela encji i uwagi: README → „Przejście z Pstryk AiO”.
- Testy: kreator i przejęcie na atrapach rejestrów Home Assistanta (przeniesienie, nazwy, wyłączenia, konflikt,
  powtórzenie, oba warianty AiO, przepływ konfiguracji i opcji), nowe sensory, identyfikatory i nazwy. Testy
  na prawdziwym Home Assistancie nie były uruchamiane w środowisku, w którym powstała zmiana (brak dostępu do PyPI).

## 2.2.6

- **Nazwy encji w jednym szyku „okres → kierunek → wielkość”.** Home Assistant układa encje urządzenia
  alfabetycznie po nazwie; dotąd średnie z oryginału („Pstryk Buy Daily Average”) stały osobno, a zakup
  i sprzedaż jednego dnia były przemieszane. Teraz każdy okres (Daily, Monthly, Yearly, Total) to jeden
  blok: zakup, bilans, sprzedaż. Zmienione nazwy (13 encji):
  - `*_buy_*_average` / `*_sell_*_average`: „Pstryk Buy Daily Average” → „Pstryk Daily Buy Price Average”
    (analogicznie Monthly, Yearly, Sell oraz „Pstryk Total Sell Price Average”),
  - `*_energy_bought`: „Energy Bought” → „Buy Volume”, `*_energy_sold`: „Energy Sold” → „Sell Volume”.
- **Identyfikatory encji i `unique_id` bez zmian** – automatyzacje, karty, recorder i statystyki działają
  dalej. Nazwa zmieniona ręcznie w UI zostaje. Test pilnuje, żeby żaden identyfikator się nie zmienił.

## 2.2.5

- **Spójne ikony w całej integracji** – zasada „rodzaj wielkości + kierunek”:
  - ceny (PLN/kWh, bieżące i wszystkie średnie): zakup `mdi:tag-arrow-down`, sprzedaż `mdi:tag-arrow-up`
    (wcześniej domyślne „oko” HA, a `sensor.pstryk_sell_total_average` miał `mdi:cash-check`),
  - energia (kWh): zakup `mdi:transmission-tower-import`, sprzedaż `mdi:transmission-tower-export` (bez zmian),
  - pieniądze (PLN): koszt `mdi:cash-minus`, przychód `mdi:cash-plus` – także `sensor.pstryk_total_sell_revenue`
    (wcześniej `mdi:cash-multiple`),
  - bilans (`sensor.pstryk_*_financial_balance`): stała ikona `mdi:scale-balance`. Oryginał dobierał ikonę
    według znaku, ale odwrotnie: dodatni bilans Pstryka to koszt, a dostawał `cash-plus`.
  - Ikona ustawiona ręcznie w UI nadal ma pierwszeństwo.
- **Wydania automatyczne:** po zmianie wersji w `manifest.json` na `main` GitHub Actions uruchamia testy
  i publikuje wydanie z opisem z tego pliku. Testy (Python 3.14) i walidacja HACS/hassfest przy każdym PR.
- **Porządki pod walidację** (bez wpływu na działanie): `manifest.json` bez kluczy, których Home Assistant
  nie zna (`logo`, `platforms`, `diagnostics`), klucze w wymaganej kolejności; `hacs.json` bez kluczy, których
  HACS nie zna; tekst powiadomienia o braku MQTT przeniesiony w tłumaczeniach do sekcji `issues`.

## 2.2.4

### Zmiany względem v2.2.3

- **Pełny limit API przy pobieraniu cen to nie błąd:** jeden wpis informacyjny z godziną zaplanowanego pobrania zamiast dwóch błędów (spójnie z kosztami).
- **Ceny mają pierwszeństwo** także przed dociąganiem danych kosztów.
- **Dociąganie kosztów anulowane przy przeładowaniu integracji** (np. po zmianie opcji) – bez błędów ze starych timerów.
- **Zmiana czasu (25.10.2026):** harmonogram liczony w UTC – powtórzona godzina 02:00–03:00 nie jest pomijana; sensor ceny pokazuje w niej właściwą cenę.

## 2.2.3

### Zmiany względem v2.2.2

- **Pamięć cen w `/config/.storage`** (`pstryk_price_cache_buy`, `pstryk_price_cache_sell`) zamiast w folderze integracji, który HACS podmienia przy każdej aktualizacji. Start po aktualizacji integracji nie zużywa już zapytania o ceny z limitu API.
- Stare pliki `cache_buy.json` / `cache_sell.json` z folderu integracji są przenoszone automatycznie i usuwane.
- Przy samej aktualizacji do tej wersji ceny mogą zostać pobrane jeden raz (HACS kasuje stare pliki przed pierwszym uruchomieniem nowego kodu).

## 2.2.2

### Poprawka względem v2.2.1

- Usunięte ostrzeżenie `SyntaxWarning: 'return' in a 'finally' block` (energy_cost_coordinator.py) zgłaszane przez Home Assistant na Pythonie 3.14 – pozostałość starego kodu po przebudowie w v2.2.1. Działanie integracji bez zmian.
- Nowe testy statyczne kodu, które wyłapują takie pozostałości niezależnie od wersji Pythona.

## 2.2.1

### Zmiany względem v2.2.0

- **Dociąganie brakujących danych kosztów** zaraz po zwolnieniu miejsca w limicie API (np. po kilku restartach w ciągu godziny), zamiast czekania do następnego :05:30. Dotyczy tylko brakujących danych – integracja wraca potem do rytmu :05:30.
- **Najpierw zapytanie miesięczne** (dane miesięczne, roczne i wszystkie sumy `total`), potem dzienne.
- **Pełny limit API to nie błąd:** wpis informacyjny zamiast ostrzeżenia w dzienniku. Nieudane pobranie kosztów zachowuje ostatnie wartości (encje nie przechodzą w „niedostępny”).
- **Średnie z oryginału zostają.** Domyślnie włączone tylko `sensor.pstryk_sell_monthly_average` i `sensor.pstryk_sell_yearly_average`; `sensor.pstryk_buy_daily_average`, `_buy_monthly_average`, `_buy_yearly_average` i `sensor.pstryk_sell_daily_average` domyślnie wyłączone (do włączenia w ustawieniach encji).
- **Bez dubli:** średnia cena sprzedaży miesięczna/roczna to średnie oryginału; średnia od początku sprzedaży: `sensor.pstryk_sell_total_average`.

### Przy aktualizacji z v2.2.0
Usuń w *Ustawienia → Urządzenia i usługi → Encje* encje, których ta wersja już nie dostarcza:
`sensor.pstryk_monthly_average_sell_price`, `sensor.pstryk_yearly_average_sell_price`, `sensor.pstryk_total_average_sell_price`.

## 2.2.0

Pierwsze wydanie forka [balgerion/ha_Pstryk](https://github.com/balgerion/ha_Pstryk) (2.1.4). Domena `pstryk` i encje oryginału bez zmian – fork instaluje się w miejsce oryginału bez utraty encji i historii. Szczegóły: sekcja **„Czym ten fork różni się od oryginału”** w README.

### Nowe encje
- **Dzień:** `sensor.pstryk_daily_energy_bought`, `sensor.pstryk_daily_energy_sold` (kWh), `sensor.pstryk_daily_buy_cost`, `sensor.pstryk_daily_sell_revenue` (PLN)
- **Sprzedaż miesięczna / roczna:** `*_sell_revenue` (PLN), `*_energy_sold` (kWh), `*_average_sell_price` (PLN/kWh)
- **Sumy od 01.10.2024 (nie zerują się, bezstratne statystyki):** `sensor.pstryk_total_energy_bought`, `sensor.pstryk_total_buy_cost`, `sensor.pstryk_total_energy_sold`, `sensor.pstryk_total_sell_revenue`, `sensor.pstryk_total_average_sell_price`
- `button.pstryk_refresh_prices`, `sensor.pstryk_prices_fetched`
- Średnia cena sprzedaży = przychód ÷ kWh z tego samego okresu (rzeczywista, ważona).

### Limit API i harmonogram
- Pilnowany limit Pstryk: 3 zapytania/h na endpoint (z PR #30 autorstwa mnarozny).
- Jeden rytm co godzinę o :05 – ceny o :05:00 (tylko gdy potrzebne), koszty o :05:30, każdej godziny doby.
- Ceny na jutro od 12:05, co 20 min do skutku; odświeżenie cen o 00:05.
- Koszty od razu po starcie, gdy brak aktualnych danych (pierwsza instalacja, długa przerwa); zwykły restart bez zapytań.

### Ceny
- Składniki ceny w `sensor.pstryk_json_buy` / `sensor.pstryk_json_sell` (`tge_price`, dystrybucja, opłata, VAT, akcyza; z PR #29 autorstwa mnarozny). Pola `time` i `price` bez zmian.

### Przy przejściu z oryginału
- Wyłącz automatyzacje wywołujące co godzinę `homeassistant.update_entity` na sensorach Pstryk – każde wywołanie zabiera miejsce w limicie API. Do ręcznego odświeżenia: `button.pstryk_refresh_prices`.
