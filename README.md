dev support:
💡 Odbierz 50 zł na prąd w Pstryk!
Użyj mojego kodu 1ML2X7 w koszyku w aplikacji. Bonus trafi do Twojego Portfela Pstryk po pierwszej opłaconej fakturze!

# Integracja Home Assistant z Pstryk API

!!! Dedykowana Karta do integracji (autora oryginału):
https://github.com/balgerion/ha_Pstryk_card

[![Wersja](https://img.shields.io/github/v/release/kriskomp/ha_Pstryk?label=wersja&color=blue)](https://github.com/kriskomp/ha_Pstryk/releases/latest)

Integracja dla Home Assistant umożliwiająca śledzenie aktualnych cen energii elektrycznej oraz prognoz z platformy Pstryk.

Lista zmian w kolejnych wersjach: [CHANGELOG.md](CHANGELOG.md) i [Releases](https://github.com/kriskomp/ha_Pstryk/releases) (wydanie powstaje automatycznie po zmianie wersji na `main`).

## Czym ten fork różni się od oryginału

To jest fork integracji [balgerion/ha_Pstryk](https://github.com/balgerion/ha_Pstryk) (licencja MIT) – podziękowania dla autora oryginału. Domena integracji (`pstryk`) i wszystkie encje oryginału zostają bez zmian, więc fork można zainstalować w miejsce oryginału bez utraty encji i ich historii.

| | Oryginał (balgerion, 2.1.4) | Ten fork (kriskomp) |
|---|---|---|
| Limit API Pstryk (3 zapytania/h na endpoint) | nie liczony – restarty, ponowienia i automatyzacje z `update_entity` mogą go przekroczyć (błąd 429) | pilnowany: jeden licznik dla wszystkich zapytań, zapisywany na czas restartu (z [PR #30](https://github.com/balgerion/ha_Pstryk/pull/30) autorstwa mnarozny) |
| Ceny | z pamięci; zapytanie o 00:01 | z pamięci; zapytanie o 00:05 i przy sprawdzaniu cen na jutro |
| Ceny na jutro | od 14:00 (tryb 48h) albo dopiero o 00:01 | od 12:05, co 20 minut do skutku, w każdym trybie |
| Kiedy pojawiły się ceny na jutro | brak informacji (tylko atrybut „Tomorrow prices available”, który wraca do `false` o północy) | `sensor.pstryk_next_day_prices_published` (data i godzina wykrycia, jedna na każdy dzień roku, zapamiętana po restarcie) i `event.pstryk_next_day_prices` (zdarzenie raz dziennie, do wyzwalania automatyzacji) – patrz [Publikacja cen na kolejny dzień](#publikacja-cen-na-kolejny-dzień) |
| Składniki ceny w `sensor.pstryk_json_buy` / `_sell` | brak | `tge_price`, dystrybucja, opłata, VAT, akcyza (z [PR #29](https://github.com/balgerion/ha_Pstryk/pull/29) autorstwa mnarozny) |
| Koszty, bilanse, średnie | co godzinę o :01 | co godzinę o :05:30 (dane godziny są w API do 3 min po jej końcu), po restarcie odtwarzane z pamięci |
| Brak miejsca w limicie API | – | wpis informacyjny w dzienniku (nie ostrzeżenie); brakujące dane kosztów dociągane zaraz po zwolnieniu miejsca, nie dopiero za godzinę |
| Nieudane pobranie kosztów | encje kosztowe przechodzą w „niedostępny” | encje zostają przy ostatnich wartościach do następnego udanego pobrania |
| Koszty po starcie Home Assistanta | pobierane przy każdym starcie (po ok. 15 s) | pobierane od razu tylko wtedy, gdy brak aktualnych danych (np. pierwsza instalacja); inaczej z pamięci, bez zapytania (patrz [Pierwsze uruchomienie](#pierwsze-uruchomienie)) |
| Przepływy energii i pieniędzy | tylko w atrybutach bilansu | 22 nowe encje: kupno i sprzedaż (kWh, PLN) dla dnia, miesiąca i roku, sumy od 01.10.2024 (kWh i PLN), średnie ceny od początku (kupno i sprzedaż), bilans od początku i bilans energii w kWh (dzień, miesiąc, rok) – patrz [Encje przepływów i sprzedaży](#encje-przepływów-i-sprzedaży-fork-kriskompha_pstryk) |
| Pamięć cen (cache) | pliki `cache_buy.json` / `cache_sell.json` w folderze integracji – kasowane przy każdej aktualizacji przez HACS, więc po aktualizacji ceny są pobierane od nowa | `/config/.storage` (jak inne dane Home Assistanta) – przetrwa aktualizacje; stare pliki są przenoszone automatycznie |
| Odświeżanie ręczne | brak | `button.pstryk_refresh_prices` (pilnuje limitu) i `sensor.pstryk_prices_fetched` |
| Średnie ceny kupna/sprzedaży (6 encji) | wszystkie włączone | tak samo, wszystkie włączone (wersje 2.2.1–2.2.6 wyłączały cztery z nich; od 2.3.0 znów są włączone – patrz [Średnie ceny](#średnie-ceny)) |
| Średnia cena od początku | brak | `sensor.pstryk_sell_total_average` i `sensor.pstryk_buy_total_average` (nazwy w stylu oryginału) |
| Zapis średnich cen do bazy (recorder) | co 30 s – HA odpytuje sześć encji średnich, a atrybut „Last updated” z sekundami robi z każdego odpytania nowy wiersz w historii | tylko przy nowych danych kosztów (co godzinę), jak pozostałe encje kosztowe – patrz [Średnie ceny](#średnie-ceny) |
| Przejęcie encji z Pstryk AiO | – | kreator przejmuje klucz API i encje (identyfikatory, nazwy i historia zostają) – patrz [Przejście z Pstryk AiO](#przejście-z-pstryk-aio) |
| Nazwy w HA | dwa szyki: „Pstryk Buy Daily Average” obok „Pstryk Daily Buy Cost” – lista encji urządzenia (alfabetyczna) przeplata okresy | jeden szyk „okres → kierunek → wielkość”; identyfikatory encji bez zmian – patrz [Nazwy encji](#nazwy-encji) |
| Ikony | tylko JSON i bilans (bilans według znaku, odwrotnie: koszt z `cash-plus`); reszta domyślna HA | jedna zasada „rodzaj + kierunek” – patrz [Ikony](#ikony) |

**Przejście z oryginału:** patrz [Instalacja → Przejście z oryginału (balgerion)](#przejście-z-oryginału-balgerion).

### Średnie ceny

Wszystkie encje oryginału zostają, w tym sześć średnich cen (zakup i sprzedaż, dzień, miesiąc, rok). Wszystkie są **domyślnie włączone**, tak jak w oryginale. Wersje 2.2.1–2.2.6 wyłączały cztery z nich (`sensor.pstryk_buy_daily_average`, `_buy_monthly_`, `_buy_yearly_`, `sensor.pstryk_sell_daily_average`); od 2.3.0 znów są włączone, bo zakup jest tak samo ważny jak sprzedaż.

Średnie liczone są wprost z rozliczenia Pstryk (koszt lub przychód ÷ kWh), ale tylko z energii godzin, które Pstryk rozliczył (koszt lub przychód większy od zera). Okres sprzed umowy ma w API odczyty licznika, lecz zerowy koszt – wliczony zaniżyłby średnią. Wolumeny (Buy/Sell Volume, sumy) pozostają dosłowne; atrybuty „Energy bought/sold” przy średnich pokazują energię użytą do średniej. Przy bardzo małym poborze z sieci (np. dom zasilany z magazynu energii) dzienna średnia zakupu bywa bardzo wysoka – to koszt dnia podzielony przez kilka Wh. Od początku doby, gdy jest mało godzin z danymi, dzienna średnia jest po prostu średnią z tego, co już rozliczono.

**Ostatnia wartość nie ginie.** Średnie (dzień, miesiąc, rok, a także `*_total_average`) są po restarcie przywracane z pamięci, a nowa wartość jest liczona obok: gdy da się ją policzyć, zastępuje przywróconą, a gdy nie (np. dane zapisane przez 2.2.x nie mają jeszcze energii rozliczonej, albo nowy dzień nie ma jeszcze rozliczonej godziny), zostaje poprzednia. Atrybut **„Value from”** (dd.mm.rrrr gg:mm:ss) pokazuje, z jakich danych jest wartość. Stara wartość zostaje tylko w obrębie swojego okresu: średnia z wczoraj nie jest dzisiejszą dzienną, więc na początku nowej doby, miesiąca lub roku średnia jest nieznana, aż Pstryk rozliczy pierwszą godzinę (historia wykresu zachowuje wczorajszą wartość). Sumy `total` nie mają końca okresu. Wartość bez daty (zapisana przez starą wersję bez atrybutu i bez czasu zapisu) nie jest przywracana.

**Aktualizacja średnich.** Średnie zmieniają się tylko wtedy, gdy przychodzą nowe dane kosztów (zwykle raz na godzinę o :05:30). Do wersji 2.3.0 (także w oryginale) Home Assistant dodatkowo odpytywał te sześć encji co 30 sekund; wartość się nie zmieniała, ale atrybut „Last updated” (z sekundami) tak, więc każde odpytanie zapisywało w bazie nowy stan – ok. 17 000 zbędnych wierszy na dobę. Od 2.3.0 encje średnich nie są odpytywane, a „Last updated” pokazuje chwilę ostatniego przeliczenia.

**Po aktualizacji do 2.3.0** integracja włącza te z czterech encji, które wyłączyła sama (w rejestrze encji mają powód „wyłączona przez integrację”). Encja wyłączona przez Ciebie ręcznie zostaje wyłączona. Żeby wyłączyć wybraną średnią: *Ustawienia → Urządzenia i usługi → Encje* → encja → ⚙ Ustawienia → **Włączone** (wyłącz) → Aktualizuj.

### Nazwy encji

Home Assistant układa encje urządzenia alfabetycznie po nazwie. W forku każda nazwa ma szyk **okres → kierunek → wielkość**, więc encje jednego okresu stoją razem: najpierw zakup, potem bilans, potem sprzedaż.

| Okres | Zakup | Bilans | Sprzedaż |
|---|---|---|---|
| Daily | Buy Cost, Buy Price Average, Buy Volume | Energy Balance, Financial Balance | Sell Price Average, Sell Revenue, Sell Volume |
| Monthly | Buy Cost, Buy Price Average, Buy Volume | Energy Balance, Financial Balance | Sell Price Average, Sell Revenue, Sell Volume |
| Yearly | Buy Cost, Buy Price Average, Buy Volume | Energy Balance, Financial Balance | Sell Price Average, Sell Revenue, Sell Volume |
| Total | Buy Cost, Buy Price Average, Buy Volume | Financial Balance | Sell Price Average, Sell Revenue, Sell Volume |

*Volume* = ilość energii (kWh), *Energy Balance* = bilans energii z API (kupione minus sprzedane, kWh), *Price Average* = średnia cena (PLN/kWh), *Cost* / *Revenue* / *Financial Balance* = PLN.

**Identyfikatory encji (`entity_id`) i `unique_id` nie zmieniają się** – automatyzacje, karty, recorder i statystyki działają dalej, a fork pozostaje zgodny z oryginałem. Dlatego nazwa i identyfikator nie zawsze mają ten sam szyk (np. „Pstryk Daily Sell Volume” to `sensor.pstryk_daily_energy_sold`). Nazwa zmieniona ręcznie w UI ma pierwszeństwo. Kto chce identyfikatory zgodne z nazwami u siebie, może je zmienić w UI (encja → ⚙ → Identyfikator encji) – historia i statystyki przechodzą automatycznie, trzeba tylko poprawić własne automatyzacje i karty.

### Ikony

| Rodzaj | Zakup | Sprzedaż |
|---|---|---|
| Cena PLN/kWh (bieżąca i wszystkie średnie) | `mdi:tag-arrow-down` | `mdi:tag-arrow-up` |
| Energia kWh | `mdi:transmission-tower-import` | `mdi:transmission-tower-export` |
| Pieniądze PLN | `mdi:cash-minus` (koszt) | `mdi:cash-plus` (przychód) |
| Bilans (`*_financial_balance`) | `mdi:scale-balance` | |
| Bilans energii kWh (`*_energy_balance`) | `mdi:transmission-tower` | |

Dodatni bilans Pstryk oznacza koszt, ujemny – zysk. Ikona ustawiona ręcznie w UI ma pierwszeństwo.

## Status API

Integracja korzysta z nowego endpointu `unified-metrics`

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
- Średnia zakupu oraz sprzedaży - dzienna/miesięczna/roczna  
- Średnia cena zakupu i sprzedaży od początku (`sensor.pstryk_buy_total_average`, `sensor.pstryk_sell_total_average`)  
- Bilans dzienny/miesięczny/roczny/od początku (PLN) i bilans energii w kWh  
- Przejęcie encji i klucza API z Pstryk AiO (kreator)  
- Debug i logowanie  


## Instalacja

### Metoda 1: Via HACS
1. W HACS kliknij **⋮** (prawy górny róg) → **Niestandardowe repozytoria**
2. Repozytorium: `https://github.com/kriskomp/ha_Pstryk`, typ: **Integracja** → **Dodaj**
3. Wyszukaj w HACS `ha_Pstryk` (autor **kriskomp**) → **Pobierz** → wybierz najnowszą wersję
4. Zrestartuj Home Assistant

### Przejście z oryginału (balgerion)
Domena integracji (`pstryk`) jest ta sama, więc konfiguracja (klucz API, opcje), encje i ich historia zostają.
1. Zrób kopię zapasową Home Assistanta.
2. HACS → **ha_Pstryk (balgerion)** → **⋮ → Usuń**. Usuwa to tylko pliki integracji. **Nie usuwaj** integracji w *Ustawienia → Urządzenia i usługi* – tam jest klucz API i konfiguracja.
3. Dodaj i pobierz fork wg Metody 1, potem restart.
4. Wyłącz automatyzacje wywołujące `homeassistant.update_entity` na sensorach Pstryk (patrz uwaga wyżej).
5. Od 2.3.0 wszystkie sześć średnich cen jest włączonych (patrz [Średnie ceny](#średnie-ceny)).

Po pierwszym starcie ceny są pobierane od nowa (pamięć cen oryginału jest kasowana przez HACS razem z jego plikami), a koszty – od razu po starcie (patrz [Pierwsze uruchomienie](#pierwsze-uruchomienie)).

### Przejście z Pstryk AiO

[Pstryk AiO](https://github.com/szkocot/Pstryk-all-in-one) (domena `pstryk_aio`) i ta integracja czytają to samo API Pstryka z limitem 3 zapytań na godzinę, więc nie mogą działać obok siebie. Kreator przejmuje po AiO klucz API i encje, więc **stare identyfikatory, nazwy (etykiety), historia i statystyki zostają**, a nic nie trzeba wpisywać od nowa.

1. Zrób kopię zapasową Home Assistanta.
2. Zainstaluj fork (Metoda 1) i zrestartuj Home Assistant. **Nie usuwaj** Pstryk AiO.
3. *Ustawienia → Urządzenia i usługi → Dodaj integrację → Pstryk Energy*. Kreator wykryje Pstryk AiO i pokaże, co zrobi (lista encji), a Ty wybierasz jedno z trzech: **przejmij i wyłącz AiO**, **przejmij i usuń AiO** albo **nie przejmuj** (zwykła konfiguracja z własnym kluczem). Żadna z opcji nie jest ustawiona z góry.
   - **Klucz API AiO jest przejmowany bez zapytania do API**, gdy AiO działa (jest załadowane): skoro AiO pobiera nim dane, klucz jest dobry. Dzięki temu wszystkie 3 zapytania z godzinnego limitu zostają dla cen, danych dziennych i miesięcznych, więc encje kosztowe mają wartości od razu po instalacji, a nie godzinę później. Gdy AiO nie działa (wyłączone albo jego start się nie powiódł), klucz jest sprawdzany jednym zapytaniem, jak wpisany ręcznie.
4. Jeśli integracja jest już dodana (np. testowo obok AiO): *Pstryk Energy → Konfiguruj → Przejmij Pstryk AiO*. Wymaga tego samego klucza API w obu integracjach; przy różnych kluczach (inne liczniki) nic nie jest zmieniane.
5. Po przejęciu odinstaluj Pstryk AiO w HACS. Podsumowanie zostaje w *Ustawienia → Naprawy*.

| Encja AiO | Co się z nią dzieje |
|---|---|
| Obecna cena zakupu / sprzedaży prądu | przejęta przez `Current Buy Price` / `Current Sell Price` |
| Dzienne koszty zużycia energii, Dzienne zużycie energii (kWh) | przejęte przez `Daily Buy Cost`, `Daily Buy Volume` |
| Dzienna wartość produkcji energii, Dzienna produkcja energii (kWh) | przejęte przez `Daily Sell Revenue`, `Daily Sell Volume` |
| Saldo rozliczeniowe dzienne / miesięczne (PLN) | przejęte przez `Daily` / `Monthly Financial Balance` |
| Saldo energetyczne dzienne / miesięczne (kWh) | przejęte przez `Daily` / `Monthly Energy Balance` |
| Miesięczne zużycie energii (kWh), Miesięczne koszty zużycia energii (PLN) | przejęte przez `Monthly Buy Volume`, `Monthly Buy Cost` |
| Miesięczna produkcja energii (kWh), Miesięczna wartość produkcji energii (PLN) | przejęte przez `Monthly Sell Volume`, `Monthly Sell Revenue` |
| Cena zakupu / sprzedaży prądu (jutro) | **usunięta** – to cena tylko pierwszej godziny jutra; wszystkie godziny jutra są w atrybutach sensorów cen i w sensorach JSON |

- **Nazwy zostają takie, jak w AiO** (np. „Dzienne koszty zużycia energii”): kreator zapisuje je w rejestrze encji. Nazwa, którą sam zmieniłeś, zostaje. Encja, którą wyłączyłeś, zostaje wyłączona.
- Encje AiO, których kreator nie zna (np. dodane w nowszej wersji AiO), nie są ruszane. Wybór „usuń AiO” skasuje je razem z wpisem; lista jest widoczna przed zatwierdzeniem.
- Jeśli obok AiO był już dodany fork, jego angielskie encje o tym samym znaczeniu są usuwane, a w ich miejsce wchodzą encje z AiO (z dłuższą historią). Nic nie jest „parkowane” ani zostawiane obok.
- Wyłączonego AiO **nie włączaj ponownie** – założyłby duplikaty z końcówką `_2` i zużywał limit API.
- Wartości mogą różnić się o grosze od AiO: AiO sumuje dobę z godzin zaokrąglonych do 2 miejsc, fork bierze dobę wprost z rozliczenia Pstryk.

#### Ujednolicenie identyfikatorów encji (opcjonalne, później)

Przejęcie **celowo zostawia** stare identyfikatory AiO (np. `sensor.pstryk_obecna_cena_zakupu_pradu`), żeby nic się nie zepsuło od razu. Gdy chcesz mieć identyfikatory tej integracji (`sensor.pstryk_current_buy_price`), albo zmienisz zdanie później: *Pstryk Energy → Konfiguruj → zaznacz „Ujednolić identyfikatory encji”* (pole pojawia się tylko, gdy jest co zmieniać; domyślnie wyłączone). Nic nie dzieje się bez Twojego wyboru:

1. **Podgląd** „stare → nowe” z oznaczeniem ✓ wolne, ⚠ kolizja, ✖ zajęte oraz liczbą odwołań znalezionych w automatyzacjach, skryptach i scenach (odwołania w szablonach nie są wykrywane).
2. **Wybór** (bez ustawienia domyślnego): *zostaw*, *zmień* (tylko te bez kolizji) albo *zmień także z kolizją*.
3. **Osobny przełącznik nazw:** „Wróć do angielskich nazw” usuwa nazwę zapisaną w rejestrze (np. polską etykietę AiO), więc encja dostaje nazwę z tej integracji. Dotyczy też nazw ustawionych ręcznie. Można go użyć bez zmiany identyfikatorów.

Co oznacza kolizja: pod nowym identyfikatorem zostały dane dawnej encji (statystyki, stany), np. po wcześniejszej instalacji forka obok AiO. „Zmień także z kolizją” kasuje **tylko te osierocone dane nowego identyfikatora** i dopiero wtedy zmienia nazwę; dane przenoszonej encji nie są kasowane. Identyfikator zajęty przez inną encję (✖) nigdy nie jest ruszany.

Warto wiedzieć przed zmianą:
- Statystyki długoterminowe (wykresy, panel Energia) idą za encją na nowy identyfikator. Historia stanów (domyślnie 10 dni) w niektórych wersjach Home Assistanta (2024.4+) może nie przejść; trwała historia to statystyki.
- Home Assistant **nie poprawia odwołań** w automatyzacjach, skryptach, scenach, kartach i ustawieniach panelu Energia. Po zmianie popraw je ręcznie według podglądu.
- Zrób kopię zapasową przed zmianą. Po zmianie integracja przeładowuje się sama.

### Metoda 2: Ręczna instalacja
1. Utwórz folder `custom_components/pstryk` w katalogu konfiguracyjnym HA
2. Wgraj wszystkie pliki z repozytorium.
3. Zrestartuj Home Assistant

## Konfiguracja
1. Przejdź do `Ustawienia` → `Urządzenia i usługi`
2. Kliknij `Dodaj integrację`
3. Wyszukaj "Pstryk Energy"
4. Wprowadź dane:
- **Klucz API**: Twój klucz z platformy Pstryk
- **Liczba najlepszych / najgorszych cen kupna i sprzedaży**: (domyślnie 5)
- **Sensory JSON z cenami**, **mostek MQTT (EVCC)**, **ponawianie zapytań** – opcjonalnie; wszystkie ustawienia można później zmienić w opcjach integracji

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
| `sensor.pstryk_buy_daily_average`, `_monthly_`, `_yearly_` | Średnia cena kupna |
| `sensor.pstryk_buy_total_average`       | Średnia cena kupna od 01.10.2024 (fork)      |
| `sensor.pstryk_sell_daily_average`      | Średnia dzienna cena sprzedaży               |
| `sensor.pstryk_total_financial_balance` | Bilans kupna/sprzedaży od 01.10.2024 (fork)  |
| `sensor.pstryk_daily_energy_balance`, `_monthly_`, `_yearly_` | Bilans energii: kupione minus sprzedane, kWh (fork) |
| `sensor.pstryk_json_buy`                | Ceny kupna 48h w formacie JSON (opcjonalny)  |
| `sensor.pstryk_json_sell`               | Ceny sprzedaży 48h w formacie JSON (opcjonalny) |
| `sensor.pstryk_prices_fetched`          | Czas pobrania z API cen, które są teraz w użyciu |
| `sensor.pstryk_next_day_prices_published` | Kiedy integracja znalazła ceny na kolejny dzień (znacznik czasu, fork) |
| `event.pstryk_next_day_prices`          | Zdarzenie „ceny na kolejny dzień opublikowane”, raz dziennie (fork) |
| `button.pstryk_refresh_prices`          | Jednorazowe pobranie cen kupna i sprzedaży   |

### Encje przepływów i sprzedaży (fork kriskomp/ha_Pstryk)

Wszystkie wartości pochodzą z danych rozliczeniowych Pstryk (`unified-metrics`), bez dodatkowych zapytań do API.

| Okres | Energia kupiona – Buy Volume (kWh) | Koszt zakupu – Buy Cost (PLN) | Energia sprzedana – Sell Volume (kWh) | Przychód – Sell Revenue (PLN) | Średnia cena sprzedaży – Sell Price Average (PLN/kWh) |
|---|---|---|---|---|---|
| Dzień | `sensor.pstryk_daily_energy_bought` | `sensor.pstryk_daily_buy_cost` | `sensor.pstryk_daily_energy_sold` | `sensor.pstryk_daily_sell_revenue` | `sensor.pstryk_sell_daily_average` (oryginał) |
| Miesiąc | `sensor.pstryk_monthly_energy_bought` | `sensor.pstryk_monthly_buy_cost` | `sensor.pstryk_monthly_energy_sold` | `sensor.pstryk_monthly_sell_revenue` | `sensor.pstryk_sell_monthly_average` (oryginał) |
| Rok | `sensor.pstryk_yearly_energy_bought` | `sensor.pstryk_yearly_buy_cost` | `sensor.pstryk_yearly_energy_sold` | `sensor.pstryk_yearly_sell_revenue` | `sensor.pstryk_sell_yearly_average` (oryginał) |
| Całość | `sensor.pstryk_total_energy_bought` | `sensor.pstryk_total_buy_cost` | `sensor.pstryk_total_energy_sold` | `sensor.pstryk_total_sell_revenue` | `sensor.pstryk_sell_total_average` |

Średnia cena kupna analogicznie: `sensor.pstryk_buy_daily_average`, `_monthly_`, `_yearly_` (oryginał) i `sensor.pstryk_buy_total_average` (od 2.3.0).

- **Całość** liczona jest od 01.10.2024 (start Pstryk); miesiące sprzed umowy API zwraca jako zera. Atrybuty sensorów `total` zawierają rozbicie per rok.
- **Średnia cena sprzedaży** = przychód ÷ kWh sprzedane w tym samym okresie (średnia ważona, rzeczywista). Gdy nic nie sprzedano, sensor nie ma wartości. Średnia cena kupna = koszt ÷ kWh kupione, tak samo.
- **Bilans** (`*_financial_balance`, PLN) = koszt zakupu minus przychód ze sprzedaży; dodatni to koszt netto, ujemny to zysk. `sensor.pstryk_total_financial_balance` liczy to od 01.10.2024 z sum rocznych.
- **Bilans energii** (`*_energy_balance`, kWh) za dzień, miesiąc i rok (kupione minus sprzedane). To wartość pola `energy_balance` z API Pstryka, bez własnego przeliczania (za rok suma miesięcy); ujemny, gdy sprzedano więcej niż kupiono. Zaraz po aktualizacji z 2.2.x jest nieznany do najbliższego pobrania kosztów (:05:30).
- **Do statystyk i wykresów długoterminowych używaj sensorów `total`.** Nie zerują się, więc nic nie ginie: dane godziny pojawiają się w API do 3 minut po jej zamknięciu i trafiają do statystyk z przesunięciem o jedną godzinę (ostatnia godzina doby wpada do statystyk następnego dnia). Sensory dzienne zerują się o północy i są podglądem bieżącej doby – ostatnia godzina doby nie zdąży do nich trafić.

### Limit API i harmonogram pobierania

Pstryk pozwala na 3 zapytania na godzinę na endpoint ([regulamin API](https://pstryk.pl/regulaminy?doc=regulamin-api)). Ceny i koszty korzystają z tego samego endpointu `unified-metrics`, więc integracja liczy każde wysłane zapytanie (także ponowienia i sprawdzenie klucza API przy konfiguracji) w jednym limicie z ostatnich 60 minut. Gdy limit jest wykorzystany, zapytanie nie jest wysyłane. Historia zapytań jest zapisywana, więc restart Home Assistanta jej nie zeruje. Wyjątek: po nagłym zatrzymaniu Home Assistanta (awaria, zanik zasilania) tuż po wysłaniu zapytania zapisany czas może być o kilka sekund wcześniejszy od rzeczywistego, więc na granicy godziny może wyjść czwarte zapytanie.

- **Ceny mają pierwszeństwo.** Pobranie cen może użyć każdego wolnego zapytania. Przy wykorzystanym limicie sensory cen zostają przy dotychczasowych danych, a pobranie rusza, gdy zwolni się miejsce – w dzienniku jest wtedy wpis informacyjny (nie błąd): `Buy prices wait for the API limit; fetching at HH:MM:SS`. Gdy ceny i koszty czekają na to samo miejsce, pierwsze idą ceny.
- **Zmiana czasu:** harmonogram liczony jest w czasie UTC, więc w dniu zmiany czasu żadna godzina (także powtórzona 02:00–03:00) nie jest pomijana ani dublowana.
- **Jeden rytm co godzinę o :05:** najpierw ceny (o :05:00, tylko gdy są potrzebne), potem koszty (o :05:30). Pstryk udostępnia dane zamkniętej godziny do 3 minut po jej końcu, a godzina w trakcie nie ma jeszcze danych.
- **Ceny na jutro** są sprawdzane o 12:05, 12:25, 12:45 i dalej co 20 minut, aż się pojawią. Jedno sprawdzenie to jedno zapytanie dla kupna i sprzedaży, bez ponowień. Działa to w każdym trybie i zastępuje sprawdzanie między 14:00 a 15:00.
- **O 00:05** odświeżane są ceny na nowy dzień (są już w pamięci jako wczorajsze „ceny na jutro”; nieudane odświeżenie ich nie kasuje).
- **Koszty, bilans i encje sprzedaży** są pobierane co godzinę o :05:30, każdej godziny doby. Po 12:00 czekają, aż ceny na jutro będą pobrane. W godzinach poprzedzających zapytanie o ceny (23: odświeżenie o 00:05; od 11 do pobrania cen na jutro: sprawdzenia od 12:05) koszty zostawiają jedno zapytanie wolne, żeby ich ponowienia nie zablokowały cen. Po restarcie dane kosztów są odtwarzane z pamięci bez zapytania.

- **Restart:** integracja wczytuje ceny z pamięci podręcznej (`/config/.storage/pstryk_price_cache_buy` i `…_sell`). Jeśli są w niej dzisiejsze ceny, nie wysyła zapytania. Jeśli brakuje tylko cen na jutro (po 12:05), wysyła jedno. Pamięć przetrwa aktualizację integracji przez HACS.
- **`button.pstryk_refresh_prices`** pobiera ceny kupna i sprzedaży jednym zapytaniem. Przy wykorzystanym limicie nic nie wysyła i pokazuje powiadomienie z godziną, o której zwolni się miejsce.
- **`sensor.pstryk_prices_fetched`** pokazuje, kiedy ceny będące teraz w użyciu zostały pobrane z API. Atrybut `tomorrow_available` mówi, czy są już ceny na jutro.

### Publikacja cen na kolejny dzień

Pstryk publikuje ceny na następny dzień po 12:00, raz o 12:05, raz o 12:20, raz o 14:00. API nie podaje godziny publikacji, więc integracja zapisuje **chwilę, w której po raz pierwszy znalazła komplet cen na kolejny dzień**. Wykrycie następuje przy sprawdzeniu o 12:05, 12:25, 12:45 i dalej co 20 minut, więc godzina jest dokładna z dokładnością do 20 minut. Niczego nie dodaje do zapytań do API.

**Komplet** oznacza cenę dla każdej godziny doby (23, 24 lub 25 godzin w dniach zmiany czasu) i `tge_price` w każdym wierszu. Przed publikacją Pstryk wysyła wiersze z ceną `null`, więc ceny kupna jednoznacznie odróżniają oba stany.

- **`sensor.pstryk_next_day_prices_published`** (znacznik czasu, `device_class: timestamp`): godzina wykrycia ostatniej publikacji. Jedna wartość na każdy dzień roku (365 lub 366), pierwsze wykrycie dnia zostaje i późniejsze pobrania go nie przesuwają. Wartość trzyma się do następnej publikacji, także po północy. Atrybuty: `prices_for` (dzień, którego ceny dotyczą, `2026-11-04`), `prices_for_display` (ten sam dzień jako `04.11.2026`), `late` (`true`, gdy ceny znaleziono dopiero po północy dnia, którego dotyczą), `next_day_available` (`true`, gdy `prices_for` to jutro). Sensor jest dostępny także przy awarii API.
- **`event.pstryk_next_day_prices`** (encja zdarzeń): zdarzenie `published` wysyłane **raz** na każdy dzień, z atrybutami `prices_for`, `prices_for_display`, `published_at` i `late`. Do wyzwalania automatyzacji służy zmiana stanu tej encji.

**Restart i przeładowanie:** zapis jest trzymany w `/config/.storage/pstryk_next_day_published` razem z identyfikatorem wpisu, więc restart Home Assistanta, przeładowanie integracji i aktualizacja przez HACS go zachowują, a zdarzenie nie powtarza się. Jeśli Home Assistant był wyłączony w chwili publikacji, godziną wykrycia jest pierwsze pobranie po starcie, a zdarzenie wysyłane jest dopiero po pełnym starcie Home Assistanta (wcześniej automatyzacje jeszcze nie nasłuchują). Zdarzenie dla dnia, który już minął, nie jest wysyłane.

**Pierwszy zapis po aktualizacji do 2.4.0** powstaje po cichu, bez zdarzenia: ceny na jutro, które już są w pamięci, dostają godzinę ich pobrania (może być późniejsza niż prawdziwa publikacja), a `late` jest wtedy puste. Pierwsze zdarzenie przyjdzie przy następnej publikacji.

**Przykładowa automatyzacja** (powiadomienie z rekomendacją po każdej publikacji; sensory JSON trzeba włączyć w opcjach integracji, a `notify.mobile_app_telefon` zamienić na własną usługę):

```yaml
alias: Pstryk – ceny na jutro opublikowane
description: Raz dziennie, zaraz po publikacji cen na kolejny dzień.
triggers:
  - trigger: state
    entity_id: event.pstryk_next_day_prices
conditions:
  # Zabezpieczenie: nie więcej niż raz dziennie, także gdyby Home Assistant po restarcie
  # odtworzył stan encji zdarzeń.
  - condition: template
    value_template: >
      {{ this.attributes.last_triggered is none
         or as_local(as_datetime(this.attributes.last_triggered)).date() != now().date() }}
actions:
  - variables:
      rows: "{{ state_attr('sensor.pstryk_json_buy', 'prices_tomorrow') | sort(attribute='price') }}"
  - action: notify.mobile_app_telefon
    data:
      title: "Pstryk: ceny na {{ trigger.to_state.attributes.prices_for_display }}"
      message: >
        Opublikowano o {{ as_local(as_datetime(trigger.to_state.attributes.published_at)).strftime('%H:%M') }}.
        Najtaniej {{ as_local(as_datetime(rows[0].time)).strftime('%H:%M') }}
        ({{ rows[0].price }} PLN/kWh), najdrożej {{ as_local(as_datetime(rows[-1].time)).strftime('%H:%M') }}
        ({{ rows[-1].price }} PLN/kWh).
```

Warunek `last_triggered` jest zabezpieczeniem, a nie wymogiem: samo zdarzenie przychodzi raz na dzień. Inny wariant bez zdarzenia: wyzwalacz `trigger: state` na `sensor.pstryk_next_day_prices_published` (zmienia się raz na dobę), ale taki wyzwalacz nie obejmie publikacji znalezionej, gdy Home Assistant dopiero się uruchamia.

Przykład wygenerujesz też na bieżąco: opisz asystentowi (np. Claude), co ma robić powiadomienie, podając nazwy encji z tej sekcji, a dostaniesz gotowy YAML do wklejenia w edytorze automatyzacji.

### Ponawianie zapytań

W opcjach (*Konfiguruj*) i przy pierwszej konfiguracji: **liczba prób** na jedno zapytanie (z pierwszą) i **opóźnienie** między próbami. Domyślnie 2 próby co 30 s, maksymalnie 3. Każda próba zużywa jedno z 3 zapytań na godzinę, więc więcej niż 3 nie ma sensu, a przy awarii API kolejne próby tylko zjadają limit. Zapisana wcześniej wartość większa niż 3 (stary domyślny wybór 5) jest używana jako 3; w *Konfiguruj* można ją ustawić ręcznie na 2.

### Encje sprzedaży, gdy nie sprzedajesz energii

12 encji dotyczy wyłącznie sprzedaży (przychód, energia sprzedana i średnia cena sprzedaży: dzień, miesiąc, rok, całość). Bez instalacji PV zostają zerowe lub nieznane, więc opcja **Encje sprzedaży** (*Konfiguruj*) decyduje, czy są włączone:

- **Automatycznie** (domyślnie, także po aktualizacji): encje są **wyłączone**, dopóki w danych nie widać żadnej sprzedaży (historia od 10.2024 oraz bieżący dzień, miesiąc i rok). Przy pierwszej sprzedaży integracja je włącza i dostajesz jedno powiadomienie; Home Assistant dodaje je w ciągu ok. 30 sekund (sam przeładowuje wpis po włączeniu encji). Do czasu pobrania historii nic nie jest wyłączane.
- **Zawsze włączone**: nigdy nie wyłącza.
- **Zawsze wyłączone**: zawsze wyłącza.

Wyłączone, a nie ukryte, bo ukryta encja nadal jest wypisana na stronie urządzenia (z dopiskiem „(ukryto)”). Nic nie ginie: wartości pochodzą z sum Pstryka, więc po włączeniu są poprawne od pierwszego pobrania, bez dziury. Wyłączone encje są w *Ustawienia → Urządzenia i usługi → Encje* (filtr „Pokaż wyłączone”). Integracja włącza z powrotem tylko to, co sama wyłączyła: encja wyłączona lub włączona ręcznie nie jest ruszana drugi raz. Bieżąca cena sprzedaży i sensory JSON ze sprzedażą zostają zawsze. Zmiana ustawienia zaczyna decyzję od nowa. W pierwszej wersji testowej 2.3.0 te encje były ukrywane; teraz są wyłączane, a po aktualizacji ukrycie jest zdejmowane.

### Diagnostyka

*Ustawienia → Urządzenia i usługi → Pstryk Energy → Pobierz diagnostykę* podaje m.in.: stan limitu API (użyte zapytania z ostatniej godziny, godzina zwolnienia miejsca, blokada po 429), stan cen i kosztów (kiedy pobrano, czy aktualne, wartości okresów), ostatni przebieg pobierania kosztów i zaplanowane dociąganie, ustawienia ponawiania, publikację cen na kolejny dzień (dla jakiego dnia, kiedy znaleziona, czy ogłoszona), encje bez wartości, wyłączone i ukryte oraz decyzję o encjach prosumenckich. Klucza API nie zawiera.

### Pierwsze uruchomienie

- **Po instalacji** (i po każdym starcie, gdy zapisane dane kosztów nie są już aktualne, np. Home Assistant był wyłączony przez noc) koszty są pobierane **od razu po starcie** – encje kosztowe i sprzedaży mają wartości po kilku sekundach.
- Wyjątek: jeśli do najbliższego :05:30 zostało mniej niż 10 minut, integracja czeka na to pobranie (bez dodatkowego zapytania).
- **Najpierw idzie zapytanie dzienne** (encje dzisiejsze), potem miesięczne (dane miesięczne, roczne i wszystkie sumy `total`). Ta sama kolejność obowiązuje w każdym godzinnym pobraniu. Gdy w limicie jest miejsce tylko na jedno zapytanie, dostają je dane dzisiejsze, które zmieniają się co godzinę; miesięczne są dociągane przy najbliższym wolnym miejscu (patrz niżej). Do 2.3.0 kolejność była odwrotna.
- **Ile zapytań zużywa instalacja.** Wpisanie klucza ręcznie: sprawdzenie klucza (1), ceny kupna i sprzedaży (1 wspólne), dane dzienne (1) – to cały limit godziny, więc dane miesięczne, roczne i sumy `total` przychodzą ok. godzinę później (dociąganie, patrz niżej). Przejęcie z działającego AiO nie sprawdza klucza osobnym zapytaniem, więc mieszczą się ceny, dane dzienne i miesięczne – wszystko od razu. Każde z tych zapytań pobiera już pełny zakres naraz (ceny na dziś i jutro, doba wczoraj–pojutrze, miesiące od 10.2024), więc nie da się ich połączyć: API przyjmuje jedną rozdzielczość (godzina, dzień, miesiąc) na zapytanie.
- Jeśli limit API nie ma miejsca na wszystko (np. kilka restartów w ciągu godziny), brakująca część jest **dociągana, gdy tylko zwolni się miejsce** w limicie (zwykle kilka–kilkadziesiąt minut), a nie dopiero o następnym :05:30. W dzienniku pojawia się wtedy informacja (nie błąd): `Cost data (...) will be fetched at HH:MM:SS, when the API limit frees`.
- Dociąganie dotyczy tylko danych, których brakuje. Gdy dane są aktualne, a jakieś pobranie się nie zmieści, czekają na najbliższe :05:30 – dzięki temu limit nie jest stale przepełniony i integracja wraca do rytmu :05:30.
- Restart przy aktualnych danych nie wysyła żadnego zapytania o koszty.

### Znane ograniczenia

- To, że ceny i koszty dzielą jeden limit 3 zapytań na godzinę, wynika z opisu API (jeden endpoint `unified-metrics`), a nie z potwierdzenia Pstryka – integracja przyjmuje wariant ostrożny.
- Po nagłym zatrzymaniu Home Assistanta tuż po wysłaniu zapytania na granicy godziny może wyjść czwarte zapytanie (szczegóły w sekcji o limicie).
- Ostatnia godzina doby nie trafia do sensorów dziennych (zerują się o północy) – trafia do sensorów `total` i ich statystyk.
- Wartości miesięczne i roczne zależą od tego, co Pstryk wlicza w koszt i przychód danego okresu; integracja pokazuje je bez przeliczania.

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

> **Format `start` od 2.3.1.** W atrybutach `All prices`, `Best prices` i `Worst prices` pole `start` ma czas lokalny z przesunięciem UTC, np. `2026-10-25T02:00:00+02:00` (do 2.3.0 bez przesunięcia). Dzięki temu dwie godziny 02:00 w dniu cofnięcia zegara (25 godzin w dobie) mają różny `start`. Automacje porównujące `start` z `now().replace(minute=0, second=0, microsecond=0).isoformat(timespec='seconds')` działają bez zmian, ale jeśli miały dopisane `.split('+')[0]`, trzeba to usunąć. Sensory JSON (`time`) miały przesunięcie od początku.

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
      microsecond=0).isoformat(timespec='seconds') %}

      {% set best_hours = state_attr('sensor.pstryk_current_buy_price',
      'Best prices') | map(attribute='start') | list %}

      {{ current_hour in best_hours }}
actions:
  - variables:
      current_hour: >-
        {{ now().replace(minute=0, second=0,
        microsecond=0).isoformat(timespec='seconds') }}
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
