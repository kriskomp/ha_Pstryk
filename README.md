dev support:
💡 Odbierz 50 zł na prąd w Pstryk!
Użyj mojego kodu 1ML2X7 w koszyku w aplikacji. Bonus trafi do Twojego Portfela Pstryk po pierwszej opłaconej fakturze!

# Integracja Home Assistant z Pstryk API

!!! Dedykowana Karta do integracji:
https://github.com/balgerion/ha_Pstryk_card

[![Wersja](https://img.shields.io/badge/wersja-2.2.3-blue)](https://github.com/kriskomp/ha_Pstryk/)

Integracja dla Home Assistant umożliwiająca śledzenie aktualnych cen energii elektrycznej oraz prognoz z platformy Pstryk.

## Czym ten fork różni się od oryginału

To jest fork integracji [balgerion/ha_Pstryk](https://github.com/balgerion/ha_Pstryk) (licencja MIT) – podziękowania dla autora oryginału. Domena integracji (`pstryk`) i wszystkie encje oryginału zostają bez zmian, więc fork można zainstalować w miejsce oryginału bez utraty encji i ich historii.

| | Oryginał (balgerion, 2.1.4) | Ten fork (kriskomp) |
|---|---|---|
| Limit API Pstryk (3 zapytania/h na endpoint) | nie liczony – restarty, ponowienia i automatyzacje z `update_entity` mogą go przekroczyć (błąd 429) | pilnowany: jeden licznik dla wszystkich zapytań, zapisywany na czas restartu (z [PR #30](https://github.com/balgerion/ha_Pstryk/pull/30) autorstwa mnarozny) |
| Ceny | z pamięci; zapytanie o 00:01 | z pamięci; zapytanie o 00:05 i przy sprawdzaniu cen na jutro |
| Ceny na jutro | od 14:00 (tryb 48h) albo dopiero o 00:01 | od 12:05, co 20 minut do skutku, w każdym trybie |
| Składniki ceny w `sensor.pstryk_json_buy` / `_sell` | brak | `tge_price`, dystrybucja, opłata, VAT, akcyza (z [PR #29](https://github.com/balgerion/ha_Pstryk/pull/29) autorstwa mnarozny) |
| Koszty, bilanse, średnie | co godzinę o :01 | co godzinę o :05:30 (dane godziny są w API do 3 min po jej końcu), po restarcie odtwarzane z pamięci |
| Koszty po starcie Home Assistanta | pobierane przy każdym starcie (po ok. 15 s) | pobierane od razu tylko wtedy, gdy brak aktualnych danych (np. pierwsza instalacja); inaczej z pamięci, bez zapytania (patrz [Pierwsze uruchomienie](#pierwsze-uruchomienie)) |
| Przepływy energii i pieniędzy | tylko w atrybutach bilansu | 13 nowych encji: dzienne kupno/sprzedaż (kWh, PLN), sprzedaż miesięczna/roczna (kWh, PLN), sumy od 01.10.2024 (kupno i sprzedaż, kWh i PLN) i średnia cena sprzedaży od początku – patrz [Encje przepływów i sprzedaży](#encje-przepływów-i-sprzedaży-fork-kriskompha_pstryk) |
| Pamięć cen (cache) | pliki `cache_buy.json` / `cache_sell.json` w folderze integracji – kasowane przy każdej aktualizacji przez HACS, więc po aktualizacji ceny są pobierane od nowa | `/config/.storage` (jak inne dane Home Assistanta) – przetrwa aktualizacje; stare pliki są przenoszone automatycznie |
| Odświeżanie ręczne | brak | `button.pstryk_refresh_prices` (pilnuje limitu) i `sensor.pstryk_prices_fetched` |
| Średnie ceny kupna/sprzedaży (6 encji) | wszystkie włączone | bez zmian w działaniu; domyślnie włączone tylko średnie sprzedaży miesięczna/roczna – patrz [Encje domyślnie wyłączone](#encje-domyślnie-wyłączone) |
| Średnia cena sprzedaży od początku | brak | `sensor.pstryk_sell_total_average` (nazwa w stylu oryginału) |

### Encje domyślnie wyłączone

Wszystkie encje oryginału zostają. Cztery średnie są w forku **domyślnie wyłączone** – przy nowej instalacji nie pojawiają się jako aktywne, ale można je włączyć w każdej chwili:

| Identyfikator encji | Nazwa w HA | Co pokazuje |
|---|---|---|
| `sensor.pstryk_buy_daily_average` | Pstryk Buy Daily Average | koszt zakupu ÷ kWh kupione, bieżący dzień (PLN/kWh) |
| `sensor.pstryk_buy_monthly_average` | Pstryk Buy Monthly Average | jw., bieżący miesiąc |
| `sensor.pstryk_buy_yearly_average` | Pstryk Buy Yearly Average | jw., bieżący rok |
| `sensor.pstryk_sell_daily_average` | Pstryk Sell Daily Average | przychód ze sprzedaży ÷ kWh sprzedane, bieżący dzień (PLN/kWh) |

Włączone zostają `sensor.pstryk_sell_monthly_average` i `sensor.pstryk_sell_yearly_average` – to rzeczywista średnia cena sprzedaży (przychód ÷ kWh) za miesiąc i rok; od początku sprzedaży: `sensor.pstryk_sell_total_average`.

Średnie liczone są wprost z rozliczenia Pstryk (koszt ÷ kWh). Przy bardzo małym poborze z sieci (np. dom zasilany z magazynu energii) dzienna średnia zakupu bywa bardzo wysoka – to koszt dnia podzielony przez kilka Wh.

**Włączenie:** *Ustawienia → Urządzenia i usługi → Encje* → wyszukaj encję (w filtrach włącz pokazywanie wyłączonych) → otwórz → ⚙ Ustawienia → **Włączone** → Aktualizuj.

**Przy przejściu z oryginału** Home Assistant zostawia te encje włączone (ustawienie domyślne dotyczy tylko nowo dodawanych encji). Żeby je wyłączyć: *Ustawienia → Urządzenia i usługi → Encje* → zaznacz encje z tabeli → ⋮ → **Wyłącz wybrane**.

## Status API

Integracja korzysta  z nowego endpointu `unified-metrics`

## Funkcje  
- Aktualna cena kupna i sprzedaży energii  
- Tabela 24h z prognozowanymi cenami dla sensora API  
- Tabela 48h z prognozowanymi cenami dla sensora MQTT  
- Konfigurowalna liczba "najlepszych godzin"  
- Konfigurowalna liczba "najgorszych godzin"  
- Cena w następnej godzinie  
- Średnia cena z pozostałej ilości godzin do końca doby  
- Średnia cena wschód/zachód  
- Automatyczna konwersja czasu UTC → lokalny  
- Ceny na jutro pobierane od 12:05; integracja pilnuje limitu 3 zapytań API na godzinę (patrz [Limit API i harmonogram pobierania](#limit-api-i-harmonogram-pobierania))  
- Przycisk do ręcznego odświeżenia cen i sensor z czasem ich pobrania  
- Konfiguracja z poziomu integracji  
- Walidacja klucza API / Cache danych / Zabezpieczenie przed timeoutem API  
- Integracja wystawia po lokalnym MQTT tablice cen w natywnym formacie EVCC  
- Średnia zakupu oraz sprzedaży - miesięczna/roczna (w forku domyślnie włączone tylko średnie sprzedaży miesięczna/roczna)  
- Średnia cena sprzedaży od początku sprzedaży (`sensor.pstryk_sell_total_average`)  
- Bilans miesięczny/roczny  
- Debug i logowanie  


## Instalacja

### Metoda 1: Via HACS
1. W HACS przejdź do `Integracje`
2. Kliknij `Dodaj repozytorium`
3. Wpisz URL: `https://github.com/kriskomp/ha_Pstryk`
4. Wybierz kategorię: `Integration`
5. Zainstaluj i zrestartuj Home Assistant

### Metoda 2: Ręczna instalacja
1. Utwórz folder `custom_components/pstryk` w katalogu konfiguracyjnym HA
2. Wgraj wszystkie pliki z repozytorium.
3. Zrestartuj Home Assistant

## Konfiguracja
1. Przejdź do `Ustawienia` → `Urządzenia i usługi`
2. Kliknij `Dodaj integrację`
3. Wyszukaj "Psrryk Energy"
4. Wprowadź dane:
- **Klucz API**: Twój klucz z platformy Pstryk
- **Liczba najlepszych cen kupna**: (domyślnie 5)
- **Liczba najlepszych cen sprzedaży**: (domyślnie 5)

## Scrnshoty

![{053A01E2-21A0-4D49-B0DB-3F7E650577AB}](https://github.com/user-attachments/assets/92c216e5-2a97-408a-aec4-c0cb50eba5fb)
![{9074A93F-0C5A-416F-BE58-A0C947A21781}](https://github.com/user-attachments/assets/e0cfd1d5-a35d-42aa-8ea4-d01b014b4fbc)
![{F57D03A2-95A1-4A08-B172-5C476C608624}](https://github.com/user-attachments/assets/de1bf119-6775-4c07-98b2-06db8a4f5b2c)
![{DAC0F8E9-63AB-4195-BB26-25C92E1D2270}](https://github.com/user-attachments/assets/e2f1b6ea-c6c9-49c9-a992-f3a759ea2ad8)





## Użycie
### Dostępne encje

| Nazwa encji                             | Opis                                         |
|-----------------------------------------|----------------------------------------------|
| `sensor.pstryk_current_buy_price`       | Aktualna cena kupna energii + tabela         |
| `sensor.pstryk_current_sell_price`      | Aktualna cena sprzedaży energii + tabela     |
| `sensor.pstryk_daily_financial_balance` | Dzienny bilans kupna/sprzedaży               |
| `sensor.pstryk_monthly_financial_balance`| Miesięczny bilans kupna/sprzedaży            |
| `sensor.pstryk_yearly_financial_balance` | Roczny bilans kupna/sprzedaży                |
| `sensor.pstryk_sell_monthly_average`    | Średnia miesięczna cena sprzedaży energii    |
| `sensor.pstryk_sell_yearly_average`     | Średnia roczna cena sprzedaży energii        |
| `sensor.pstryk_sell_total_average`      | Średnia cena sprzedaży od 01.10.2024 (fork)  |
| `sensor.pstryk_buy_daily_average`, `_monthly_`, `_yearly_` | Średnia cena kupna (domyślnie wyłączone) |
| `sensor.pstryk_sell_daily_average`      | Średnia dzienna cena sprzedaży (domyślnie wyłączona) |
| `sensor.pstryk_json_buy`                | Ceny kupna 48h w formacie JSON (opcjonalny)  |
| `sensor.pstryk_json_sell`               | Ceny sprzedaży 48h w formacie JSON (opcjonalny) |
| `sensor.pstryk_prices_fetched`          | Czas pobrania z API cen, które są teraz w użyciu |
| `button.pstryk_refresh_prices`          | Jednorazowe pobranie cen kupna i sprzedaży   |

### Encje przepływów i sprzedaży (fork kriskomp/ha_Pstryk)

Wszystkie wartości pochodzą z danych rozliczeniowych Pstryk (`unified-metrics`), bez dodatkowych zapytań do API.

| Okres | Energia kupiona (kWh) | Koszt zakupu (PLN) | Energia sprzedana (kWh) | Przychód ze sprzedaży (PLN) | Średnia cena sprzedaży (PLN/kWh) |
|---|---|---|---|---|---|
| Dzień | `sensor.pstryk_daily_energy_bought` | `sensor.pstryk_daily_buy_cost` | `sensor.pstryk_daily_energy_sold` | `sensor.pstryk_daily_sell_revenue` | – |
| Miesiąc | – | – | `sensor.pstryk_monthly_energy_sold` | `sensor.pstryk_monthly_sell_revenue` | `sensor.pstryk_sell_monthly_average` (oryginał) |
| Rok | – | – | `sensor.pstryk_yearly_energy_sold` | `sensor.pstryk_yearly_sell_revenue` | `sensor.pstryk_sell_yearly_average` (oryginał) |
| Całość | `sensor.pstryk_total_energy_bought` | `sensor.pstryk_total_buy_cost` | `sensor.pstryk_total_energy_sold` | `sensor.pstryk_total_sell_revenue` | `sensor.pstryk_sell_total_average` |

- **Całość** liczona jest od 01.10.2024 (start Pstryk); miesiące sprzed umowy API zwraca jako zera. Atrybuty sensorów `total` zawierają rozbicie per rok.
- **Średnia cena sprzedaży** = przychód ÷ kWh sprzedane w tym samym okresie (średnia ważona, rzeczywista). Gdy nic nie sprzedano, sensor nie ma wartości.
- **Do statystyk i wykresów długoterminowych używaj sensorów `total`.** Nie zerują się, więc nic nie ginie: dane godziny pojawiają się w API do 3 minut po jej zamknięciu i trafiają do statystyk z przesunięciem o jedną godzinę (ostatnia godzina doby wpada do statystyk następnego dnia). Sensory dzienne zerują się o północy i są podglądem bieżącej doby – ostatnia godzina doby nie zdąży do nich trafić.

### Limit API i harmonogram pobierania

Pstryk pozwala na 3 zapytania na godzinę na endpoint ([regulamin API](https://pstryk.pl/regulaminy?doc=regulamin-api)). Ceny i koszty korzystają z tego samego endpointu `unified-metrics`, więc integracja liczy każde wysłane zapytanie (także ponowienia i sprawdzenie klucza API przy konfiguracji) w jednym limicie z ostatnich 60 minut. Gdy limit jest wykorzystany, zapytanie nie jest wysyłane. Historia zapytań jest zapisywana, więc restart Home Assistanta jej nie zeruje. Wyjątek: po nagłym zatrzymaniu Home Assistanta (awaria, zanik zasilania) tuż po wysłaniu zapytania zapisany czas może być o kilka sekund wcześniejszy od rzeczywistego, więc na granicy godziny może wyjść czwarte zapytanie.

- **Ceny mają pierwszeństwo.** Pobranie cen może użyć każdego wolnego zapytania. Przy wykorzystanym limicie sensory cen zostają przy dotychczasowych danych, a pobranie rusza, gdy zwolni się miejsce.
- **Jeden rytm co godzinę o :05:** najpierw ceny (o :05:00, tylko gdy są potrzebne), potem koszty (o :05:30). Pstryk udostępnia dane zamkniętej godziny do 3 minut po jej końcu, a godzina w trakcie nie ma jeszcze danych.
- **Ceny na jutro** są sprawdzane o 12:05, 12:25, 12:45 i dalej co 20 minut, aż się pojawią. Jedno sprawdzenie to jedno zapytanie dla kupna i sprzedaży, bez ponowień. Działa to w każdym trybie i zastępuje sprawdzanie między 14:00 a 15:00.
- **O 00:05** odświeżane są ceny na nowy dzień (są już w pamięci jako wczorajsze „ceny na jutro”; nieudane odświeżenie ich nie kasuje).
- **Koszty, bilans i encje sprzedaży** są pobierane co godzinę o :05:30, każdej godziny doby. Po 12:00 czekają, aż ceny na jutro będą pobrane. W godzinach poprzedzających zapytanie o ceny (23: odświeżenie o 00:05; od 11 do pobrania cen na jutro: sprawdzenia od 12:05) koszty zostawiają jedno zapytanie wolne, żeby ich ponowienia nie zablokowały cen. Po restarcie dane kosztów są odtwarzane z pamięci bez zapytania.

- **Restart:** integracja wczytuje ceny z pamięci podręcznej (`/config/.storage/pstryk_price_cache_buy` i `…_sell`). Jeśli są w niej dzisiejsze ceny, nie wysyła zapytania. Jeśli brakuje tylko cen na jutro (po 12:05), wysyła jedno. Pamięć przetrwa aktualizację integracji przez HACS.
- **`button.pstryk_refresh_prices`** pobiera ceny kupna i sprzedaży jednym zapytaniem. Przy wykorzystanym limicie nic nie wysyła i pokazuje powiadomienie z godziną, o której zwolni się miejsce.
- **`sensor.pstryk_prices_fetched`** pokazuje, kiedy ceny będące teraz w użyciu zostały pobrane z API. Atrybut `tomorrow_available` mówi, czy są już ceny na jutro.

### Pierwsze uruchomienie

- **Po instalacji** (i po każdym starcie, gdy zapisane dane kosztów nie są już aktualne, np. Home Assistant był wyłączony przez noc) koszty są pobierane **od razu po starcie** – encje kosztowe i sprzedaży mają wartości po kilku sekundach.
- Wyjątek: jeśli do najbliższego :05:30 zostało mniej niż 10 minut, integracja czeka na to pobranie (bez dodatkowego zapytania).
- Najpierw idzie zapytanie miesięczne (zasila dane miesięczne, roczne i wszystkie sumy `total`), potem dzienne.
- Jeśli limit API nie ma miejsca na wszystko (np. kilka restartów w ciągu godziny), brakująca część jest **dociągana, gdy tylko zwolni się miejsce** w limicie (zwykle kilka–kilkadziesiąt minut), a nie dopiero o następnym :05:30. W dzienniku pojawia się wtedy informacja (nie błąd): `Cost data (...) will be fetched at HH:MM:SS, when the API limit frees`.
- Dociąganie dotyczy tylko danych, których brakuje. Gdy dane są aktualne, a jakieś pobranie się nie zmieści, czekają na najbliższe :05:30 – dzięki temu limit nie jest stale przepełniony i integracja wraca do rytmu :05:30.
- Restart przy aktualnych danych nie wysyła żadnego zapytania o koszty.

### Sensory JSON (opcjonalne)

Po włączeniu opcji **"Włącz sensory JSON z cenami"** w ustawieniach integracji pojawiają się sensory `sensor.pstryk_json_buy` i `sensor.pstryk_json_sell` z atrybutami `prices_today`, `prices_tomorrow` i `prices` (48h) w ustandaryzowanym formacie `{time, price}` — zgodnym z TGE/Nordpool i kompatybilnym z [EV Smart Charging](https://github.com/jonasbkarlsson/ev_smart_charging) czy [cheapest-energy-hours](https://github.com/TheFes/cheapest-energy-hours/).

Każdy wpis ma też składniki ceny z API dla danej godziny (zł/kWh, zaokrąglone do 7 miejsc po przecinku), a wpisy `json_buy` także znaczniki Pstryka:

| Pole | `json_buy` | `json_sell` |
|---|---|---|
| `tge_price` — cena energii | ✓ | ✓ |
| `dist_price` — opłata dystrybucyjna zmienna | ✓ | |
| `service_price` — opłata serwisowa | ✓ | |
| `vat_component` — VAT | ✓ | |
| `excise_component` — akcyza | ✓ | |
| `is_cheap`, `is_expensive` — tania / droga godzina wg Pstryka | ✓ | |

- Kupno: `tge_price + dist_price + service_price + vat_component + excise_component` to pełna cena brutto; `price` to ta sama cena zaokrąglona do 2 miejsc po przecinku.
- Sprzedaż: przy dodatnich cenach `price` to `tge_price × 1,23` (sprawdzone na danych z API). Godziny z ceną ujemną nie były jeszcze sprawdzane, więc tam tego wzoru nie należy zakładać.
- `is_cheap` / `is_expensive` są przepisane z API bez zmian. Pstryk podaje je dla ceny zakupu, dlatego nie ma ich we wpisach `json_sell`. Sposób ich wyznaczania nie jest znany.
- Godziny jeszcze nieopublikowane: w `json_buy` ich nie ma, a w `json_sell` są ukryte, dopóki Pstryk nie poda cen. Składniki mają wartość `null`, gdy brakuje `tge_price` (API podaje wtedy np. `dist_price: 0`, co nie oznacza darmowej dystrybucji).
- Jeśli po aktualizacji integracji pierwsze pobranie cen z API się nie uda, wpisy wczytane ze starej pamięci podręcznej mają składniki `null` aż do następnego udanego pobrania.

Przykładowy wykres cen 48h ([apexcharts-card](https://github.com/RomRider/apexcharts-card)):

```yaml
type: custom:apexcharts-card
header:
  show: true
  show_states: true
  colorize_states: true
graph_span: 48h
span:
  start: day
now:
  show: true
  label: teraz
series:
  - entity: sensor.pstryk_json_buy
    name: Buy Price
    float_precision: 2
    extend_to: false
    show:
      legend_value: false
      in_header: raw
    data_generator: |
      return entity.attributes.prices.map(i => [new Date(i.time).getTime(), i.price]);
  - entity: sensor.pstryk_json_sell
    name: Sell Price
    float_precision: 2
    extend_to: false
    show:
      legend_value: false
      in_header: raw
    data_generator: |
      return entity.attributes.prices.map(i => [new Date(i.time).getTime(), i.price]);
```

Nagłówek karty pokazuje aktualną cenę (stan sensora, odświeżany co godzinę), a pionowa linia "teraz" zaznacza bieżącą godzinę na osi 48h.

Przykładowa Automatyzacja:

Włączanie bojlera
![IMG_4079](https://github.com/user-attachments/assets/ccdfd05c-3b38-4af5-a8db-36fe7fd645ee)

```yaml
alias: Optymalne grzanie wody
description: ""
triggers:
  - minutes: "1"
    trigger: time_pattern
    hours: /1
conditions:
  - condition: template
    value_template: >
      {% set current_hour = now().replace(minute=0, second=0,
      microsecond=0).isoformat(timespec='seconds').split('+')[0] %}

      {% set best_hours = state_attr('sensor.pstryk_current_buy_price',
      'Best prices') | map(attribute='start') | list %}

      {{ current_hour in best_hours }}
actions:
  - variables:
      current_hour: >-
        {{ now().replace(minute=0, second=0,
        microsecond=0).isoformat(timespec='seconds').split('+')[0] }}
  - choose:
      - conditions:
          - condition: state
            entity_id: light.shellypro3_34987a49142c_switch_2
            state: "off"
        sequence:
          - target:
              entity_id: switch.shellypro3_34987a49142c_switch_2
            action: switch.turn_on
            data: {}
          - data:
              message: |
                Grzanie włączone! Godzina: {{ current_hour }}, Cena: {{
                  state_attr('sensor.pstryk_current_buy_price', 'Best prices')
                  | selectattr('start', 'equalto', current_hour)
                  | map(attribute='price')
                  | first
                }} PLN
            action: notify.mobile_app_balg_iphone
      - conditions:
          - condition: state
            entity_id: light.shellypro3_34987a49142c_switch_2
            state: "on"
        sequence:
          - delay:
              hours: 1
              minutes: 5
          - target:
              entity_id: switch.shellypro3_34987a49142c_switch_2
            action: switch.turn_off
            data: {}


```

## EVCC

### Scrnshoty

![{9EE9344A-DAA3-42C0-9084-D2F3B5AE1B08}](https://github.com/user-attachments/assets/1812343e-3fa7-4e44-9205-f8f0c524f771)
![{6B2DA5CA-5797-43FB-88DC-F908D9B72501}](https://github.com/user-attachments/assets/0a4a6e46-8b49-4a6b-8676-3e57bf272bf8)


### Konfiguracja

Taryfy:
```yaml
currency: PLN
grid:
  type: custom
  forecast:
    source: mqtt
    topic: energy/forecast/buy

feedin:
  type: custom
  forecast:
    source: mqtt
    topic: energy/forecast/sell
```
