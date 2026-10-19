# Zmiany

Numeracja wersji: `X.Y.Z`. Wydanie na GitHubie powstaje automatycznie po zmianie wersji w
`manifest.json` na gałęzi `main`, a jego opis to odpowiednia sekcja tego pliku.
Wersje do 2.1.4 włącznie: [oryginał balgerion/ha_Pstryk](https://github.com/balgerion/ha_Pstryk).

Kod polecający Pstryk: **1ML2X7**.

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
