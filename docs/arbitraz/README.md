# Arbitraż cenowy magazynu energii (ładowanie)

Po publikacji cen na kolejny dzień (`event.pstryk_next_day_prices`, od 2.4.0) układ sprawdza, czy opłaca się **kupić
energię taniej i sprzedać ją później z zyskiem**. Gdy tak, wysyła powiadomienie z oknem zakupu, mocą, ilością energii
i szacowanym zyskiem, a przycisk „Zaplanuj ładowanie” dodaje ładowanie do kalendarza magazynu. Falownikiem steruje
dalej wyłącznie kalendarz (`calendar.ladowanie_magazynu` i istniejąca automatyzacja sterowania wg kalendarza).

To są skrypty i automatyzacje do wklejenia w interfejsie Home Assistanta (edytor YAML), nie część integracji. Autor
używa ich z inwerterem SolaX; nazwy encji falownika i kalendarzy są w nich na stałe (lista niżej).

**Zakres tego etapu:** planowane jest tylko **ładowanie**. Sprzedaż (rozładowanie, feed-in) jest w powiadomieniu
wyłącznie informacją, żeby było widać, po co się ładuje. Automatyczne planowanie sprzedaży jest do zrobienia później
(brak decyzji, bo nakłada się na zysk z PV).

## Jak liczy planista

1. Ceny godzinowe z `sensor.pstryk_json_buy` i `sensor.pstryk_json_sell` (`prices_today` i `prices_tomorrow`) na dany
   dzień; kwadranse są uśredniane do godziny.
2. Zysk z pary „kupno o godzinie A, sprzedaż o godzinie B (później tego samego dnia)”:
   `cena sprzedaży(B) − cena zakupu(A) × 1,24`. Mnożnik 1,24 to straty ładowania i rozładowania z falownika
   (0,873 × 0,925 ≈ 0,81), nie z licznika Pstryk. Okazja jest, gdy zysk wynosi **co najmniej 1,00 zł/kWh**.
3. Okno zakupu: godziny, dla których istnieje opłacalna późniejsza sprzedaż; ciągły przedział wokół najtańszej
   godziny.
4. **Ile kupić:** `wolne miejsce do 95% − 50% prognozy Solcast na ten dzień`. Wolne miejsce to
   `pojemność × 95% − energia w baterii teraz`. Przykład: wolne 20 kWh, prognoza 5 kWh daje 17,5 kWh. Poniżej 1 kWh
   ładowania się nie planuje.
5. **Moc:** energia podzielona przez długość okna, zaokrąglona w górę do kroku pomocnika
   `input_number.magazyn_moc_ladowania` (500 W), w granicach 1000 W do 11000 W. Czas trwania wynika z mocy
   (zaokrąglony w górę do 5 minut), a wydarzenie jest ustawiane w najtańszym miejscu okna (początek na pełnej godzinie).
6. **Zysk:** `sprzedane kWh × (średnia cena sprzedaży − średnia cena zakupu × 1,24)`, gdzie sprzedane kWh to energia
   z baterii × 0,925. Okno sprzedaży to najdroższe godziny po zakończeniu ładowania, tyle, ile potrzeba przy limicie
   eksportu z `number.solax_inverter_export_limit`.

Wszystkie parametry (mnożnik, próg zysku, sprawności, 95%, 50% prognozy, minimum 1 kWh, 11000 W) są w pierwszym
kroku `variables` skryptu planisty.

## Instalacja (wszystko w interfejsie, bez zmian w plikach YAML)

1. **Pomocnik** *Ustawienia → Urządzenia i usługi → Pomocnicy → Utwórz → Tekst*: nazwa `Pstryk sell arbitraz plan`
   (identyfikator `input_text.pstryk_sell_arbitraz_plan`), długość maksymalna **255**. Nazwa pasuje do wzorca
   `input_*.pstryk_sell_*` z wykluczeń recordera, więc nic nie trafia do bazy.
2. **Skrypt `Kalendarz – Dodaj ładowanie`** (istniejący): *Edytuj w YAML* i wklej zawartość
   `kalendarz_dodaj_ladowanie.yaml`. Zmiany względem poprzedniej wersji:
   - nowe opcjonalne pola `start`, `koniec`, `moc` (bez nich skrypt działa z pomocników jak dotąd),
   - koniec może wypaść w kolejnym dniu: jeśli data w `magazyn_koniec_ladowania` jest **późniejsza** niż data startu,
     jest brana wprost; jeśli taka sama lub starsza, działa dotychczasowa reguła (data startu + godzina końca),
   - sprawdzanie istniejących wydarzeń obejmuje dni od startu do końca.
3. **Skrypt** *Ustawienia → Automatyzacje i sceny → Skrypty → Dodaj skrypt → Edytuj w YAML*, wklej
   `pstryk_arbitraz_plan.yaml` (identyfikator `script.pstryk_arbitraz_plan`).
4. **Skrypt** `pstryk_arbitraz_zaplanuj.yaml` (identyfikator `script.pstryk_arbitraz_zaplanuj`).
5. **Automatyzacja** `pstryk_arbitraz_koordynator.yaml` (identyfikator `automation.pstryk_arbitraz_koordynator`).
   Usługa powiadomień jest na stałe `notify.mobile_app_pixel_9a`; przyciski działają w aplikacji Home Assistanta
   na Androidzie.
6. **Dashboard:** karta z `dashboard_karta.yaml` (podgląd planu i przyciski).

Po zapisaniu sprawdź identyfikatory w *Ustawienia → Encje*: powinny być takie, jak wyżej. Jeśli któryś się różni,
popraw odwołania w pozostałych plikach.

## Test krok po kroku

1. *Narzędzia deweloperskie → Akcje* → `script.pstryk_arbitraz_plan` → *Uruchom akcję*: w odpowiedzi jest cały wynik
   (`ok`, `powod`, `tekst`, `zapis`). Nic nie jest zapisywane.
2. Jeśli jutro nie ma okazji (zdarza się zwykle raz w tygodniu), odpowiedź podaje najlepszy zysk, np. „Najlepszy zysk
   0,65 zł/kWh (kupno 02:00, sprzedaż 16:00) przy progu 1,00”. Żeby sprawdzić resztę, tymczasowo zmień w planiście
   `marza_zl: 1.0` na `0.6` i uruchom ponownie.
3. Przycisk **Przelicz plan** na dashboardzie (uruchamia koordynatora) zapisuje plan w pomocniku i wysyła
   powiadomienie, także gdy okazji nie ma.
4. Przycisk **Podgląd** (`pstryk_arbitraz_zaplanuj` z `podglad: true`) pokazuje powiadomienie systemowe z tym, co
   zostałoby dodane, bez zapisu.
5. Dopiero potem **Zaplanuj ładowanie**: wydarzenie „Ładowanie” z opisem `MOC:-<W>` pojawia się w
   `calendar.ladowanie_magazynu`, a plan dostaje stan „zaplanowano”.
6. Po testach przywróć `marza_zl: 1.0`.

## Zachowanie w sytuacjach brzegowych

- Powiadomienie po publikacji cen przychodzi **tylko, gdy jest okazja**. Brak okazji nie wysyła nic (powód widać
  w karcie na dashboardzie i po ręcznym „Przelicz plan”).
- Drugie kliknięcie „Zaplanuj” nie dubluje wydarzenia. Po dodaniu skrypt sprawdza w kalendarzu, że wydarzenie
  naprawdę powstało (czas i moc), i dopiero wtedy zmienia stan planu.
- Jeśli w oknie jest już jakiekolwiek wydarzenie w kalendarzu ładowania, rozładowania lub feed-in (poza identycznym
  ładowaniem), nic nie jest dodawane, a powiadomienie podaje, z czym jest kolizja. Przyciski są wtedy ukryte.
- Gdy okno już się zaczęło, początek przesuwa się na „teraz”. Gdy do końca zostaje mniej niż 10 minut, plan wygasa.
- Po restarcie Home Assistanta stare zdarzenie nie uruchamia planowania (liczy się tylko `published_at` nie starsze
  niż 10 minut).
- Jeśli przed oknem zakupu jest w kalendarzu rozładowania wydarzenie, planista liczy wolne miejsce od minimalnego SOC
  (`input_number.solax_discharge_min_soc`) i pisze o tym w powiadomieniu.
- Pole `podglad` w skrypcie planowania działa tak samo jak w `solax_zaplanuj_feed_in_na_jutro`.

## Założenia i czego ten etap nie robi

- **Test ograniczony:** szablony przeszły testy w symulatorze szablonów (testy w repozytorium, z porównaniem do
  niezależnej implementacji na losowych dniach), ale nie w prawdziwym Home Assistancie. Pierwsze uruchomienie
  sprawdź według kroków wyżej.
- **SOC jest z chwili liczenia** (około 12:05), nie z początku okna zakupu. Bateria zwykle zużyje się do tego czasu,
  więc plan jest raczej zaniżony niż zawyżony. Zużycia domu nie prognozujemy.
- **95% to cel planu**, a nie ustawienie falownika: `number.solax_inverter_battery_charge_max_soc` zostaje, jak jest.
  Twarda granica ładowania z kalendarza to nadal SOC ≥ 99% (istniejący skrypt SolaX).
- **Prognoza Solcast:** połowa całodziennej prognozy (`prognoza_na_jutro`, a gdy plan dotyczy dzisiaj,
  `prognoza_na_dzisiaj`), bez odejmowania zużycia domu.
- **Moc ładowania bez kalibracji.** Przy rozładowaniu Twój skrypt koryguje moc wzorem `(kW·1000+67)/1,0737`; przy
  ładowaniu takiej korekty nie ma i planista jej nie dodaje. Rozładowania ten układ nie dotyka.
- Plan używa **całego ciągłego przedziału** opłacalnych godzin (z niższą mocą), a nie tylko najtańszych godzin z wyższą
  mocą. Kosztem jest nieco wyższa średnia cena zakupu. Wydarzenie jest ustawiane w najtańszym miejscu przedziału,
  początek wypada na pełnej godzinie.
- W dniach zmiany czasu (23 i 25 godzin) godziny są liczone jak w doby 24-godzinnej, wynik może być niedokładny.
- Dostępne, a nieużywane: `tge_price`, `dist_price`, `is_cheap`/`is_expensive` w sensorach JSON, odchylenia
  `estimate10`/`estimate90` i `detailedHourly` w Solcast, stan zdrowia baterii.
- Powiadomienia idą na jeden telefon (`notify.mobile_app_pixel_9a`).

## Lista encji używanych na stałe

`sensor.pstryk_json_buy`, `sensor.pstryk_json_sell`, `event.pstryk_next_day_prices`,
`sensor.solax_inverter_battery_soc`, `sensor.solax_inverter_battery_energy`,
`sensor.solax_inverter_battery_system_installed_capacity`, `number.solax_inverter_export_limit`,
`input_number.solax_discharge_min_soc`, `input_number.magazyn_moc_ladowania`,
`sensor.solcast_pv_forecast_prognoza_na_jutro` i `..._na_dzisiaj`, `calendar.ladowanie_magazynu`,
`calendar.rozladowanie_magazynu`, `calendar.feed_in_magazynu`, `script.kalendarz_dodaj_ladowanie`,
`input_text.pstryk_sell_arbitraz_plan`, `notify.mobile_app_pixel_9a`.
