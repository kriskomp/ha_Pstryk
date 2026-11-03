"""Tests of the arbitrage YAML in docs/arbitraz (planner, executor, patched calendar script, dashboard)."""
import datetime as dt
import math
import random

import pytest

from ha_template import DOCS, TZ, load, make_env, native, render_variables, run_planner

NOW = dt.datetime(2026, 11, 3, 12, 10, tzinfo=TZ)

# Prices for 2026-11-04 as published on 2026-11-03 (best spread 0.65 zl/kWh: no opportunity at 1.00)
REAL_BUY = [1.5, 1.5, 1.45, 1.45, 1.5, 1.56, 2.15, 2.36, 2.23, 2.06, 1.87, 1.81, 1.73, 1.89, 2.3, 2.88, 2.92, 2.72, 2.87, 2.92, 2.78, 2.14, 1.76, 1.55]
REAL_SELL = [1.21, 1.21, 1.16, 1.17, 1.21, 1.27, 1.67, 1.89, 1.76, 1.59, 1.4, 1.34, 1.25, 1.42, 1.82, 2.41, 2.45, 2.24, 2.4, 2.44, 2.31, 1.66, 1.47, 1.26]
# A day with a real opportunity: cheap night, expensive evening
BUY = [0.6, 0.45, 0.30, 0.30, 0.35, 0.9, 1.5, 2, 2, 1.8, 1.5, 1.4, 1.3, 1.5, 1.9, 2.4, 2.8, 3.0, 3.0, 2.9, 2.6, 2, 1.4, 0.9]
SELL = [0.4, 0.3, 0.2, 0.2, 0.25, 0.7, 1.2, 1.6, 1.6, 1.4, 1.2, 1.1, 1.0, 1.2, 1.6, 2.0, 2.4, 2.5, 2.5, 2.4, 2.1, 1.6, 1.1, 0.7]


def prices(buy, sell, day="2026-11-04", step=60):
    def rows(arr):
        out = []
        for h, v in enumerate(arr):
            for m in range(0, 60, step):
                out.append({"time": f"{day}T{h:02d}:{m:02d}:00+01:00", "price": v})
        return out
    return {
        "sensor.pstryk_json_buy": {"prices_today": [], "prices_tomorrow": rows(buy)},
        "sensor.pstryk_json_sell": {"prices_today": [], "prices_tomorrow": rows(sell)},
        "input_number.magazyn_moc_ladowania": {"min": 1000, "max": 12000, "step": 500},
    }


def inverter(soc=65, energy=20.9, pv=11.774):
    return {
        "number.solax_inverter_export_limit": "12000",
        "sensor.solax_inverter_battery_system_installed_capacity": "32154",
        "sensor.solax_inverter_battery_soc": str(soc),
        "sensor.solax_inverter_battery_energy": str(energy),
        "input_number.solax_discharge_min_soc": "12",
        "sensor.solcast_pv_forecast_prognoza_na_jutro": str(pv),
        "sensor.solcast_pv_forecast_prognoza_na_dzisiaj": "24.2",
    }


def plan(buy=BUY, sell=SELL, kal=None, now=NOW, **kw):
    return run_planner(inverter(**{k: v for k, v in kw.items() if k in ("soc", "energy", "pv")}),
                       prices(buy, sell), kal or {}, now)


@pytest.mark.parametrize("name", ["pstryk_arbitraz_plan.yaml", "pstryk_arbitraz_zaplanuj.yaml",
                                  "pstryk_arbitraz_koordynator.yaml", "kalendarz_dodaj_ladowanie.yaml",
                                  "dashboard_karta.yaml"])
def test_yaml_files_parse(name):
    assert load(name)


# ---------------------------------------------------------------- planner
def test_real_prices_of_4_november_give_no_opportunity():
    r = run_planner(inverter(), prices(REAL_BUY, REAL_SELL), {}, NOW)
    assert r["ok"] is False
    assert "0,65" in r["powod"] and "02:00" in r["powod"] and "16:00" in r["powod"]
    assert r["zapis"].startswith("brak;2026-11-04;")


def test_threshold_lowered_turns_the_same_day_into_a_plan():
    r = run_planner(inverter(), prices(REAL_BUY, REAL_SELL), {}, NOW, replace={"marza_zl: 1.0 ": "marza_zl: 0.6 "})
    assert r["ok"] and r["start"] == "2026-11-04 02:00:00" and r["moc_w"] == 2000
    assert r["energia_kwh"] == 3.7  # 9.6 free to 95% minus half of the 11.774 kWh forecast


def test_opportunity_numbers():
    r = plan(pv=5.0)
    assert r["ok"]
    assert (r["start"], r["koniec"], r["moc_w"], r["energia_kwh"]) == ("2026-11-04 00:00:00", "2026-11-04 04:45:00", 1500, 7.1)
    assert r["sprzedaz"] == "17:00-18:00" and r["cena_sprzedazy"] == 2.5
    assert r["zapis"] == "2026-11-04 00:00:00;2026-11-04 04:45:00;1500;7.1;0.4;2.5;13.1;n;17:00-18:00"
    assert len(r["zapis"]) < 255


def test_no_room_in_battery_means_no_plan():
    r = plan(soc=90, energy=28.9, pv=5)
    assert r["ok"] is False and "nie ma miejsca" in r["powod"]


def test_missing_prices_and_battery_data():
    r = run_planner(inverter(), {"sensor.pstryk_json_buy": {}, "sensor.pstryk_json_sell": {}}, {}, NOW)
    assert r["ok"] is False and r["powod"].startswith("Brak cen")
    broken = inverter()
    broken["sensor.solax_inverter_battery_soc"] = "unavailable"
    broken["sensor.solax_inverter_battery_energy"] = "unavailable"
    r = run_planner(broken, prices(BUY, SELL), {}, NOW)
    assert r["ok"] is False and "baterii" in r["powod"]


def test_quarter_hour_prices_are_averaged_per_hour():
    attrs = prices(BUY, SELL, step=15)
    r = run_planner(inverter(pv=5.0), attrs, {}, NOW)
    assert r["ok"] and r["moc_w"] == 1500


def test_planned_discharge_before_window_starts_from_min_soc():
    kal = {"calendar.rozladowanie_magazynu": {"events": [
        {"summary": "Rozładowanie", "start": "2026-11-03T18:00:00+01:00", "end": "2026-11-03T21:00:00+01:00"}]}}
    r = plan(kal=kal, pv=0)
    assert r["ok"] and "przed oknem jest planowane rozładowanie" in r["tekst"]
    assert r["energia_kwh"] > 20


def test_calendar_collision_is_reported_and_identical_event_is_not_a_collision():
    event = {"summary": "Feed-in", "start": "2026-11-04T03:00:00+01:00", "end": "2026-11-04T04:00:00+01:00"}
    r = plan(kal={"calendar.feed_in_magazynu": {"events": [event]}}, pv=0)
    assert "Feed-in 03:00-04:00" in r["kolizja"]
    base = plan(pv=0)
    same = {"summary": "Ładowanie", "start": base["start"].replace(" ", "T") + "+01:00",
            "end": base["koniec"].replace(" ", "T") + "+01:00"}
    assert plan(kal={"calendar.ladowanie_magazynu": {"events": [same]}}, pv=0)["kolizja"] == ""


def test_window_too_short_for_the_energy_is_capped_at_max_power():
    buy, sell = [1.5] * 24, [1.0] * 24
    buy[3] = 0.2
    sell[18] = sell[19] = 2.5
    r = plan(buy, sell, soc=12, energy=3.9, pv=0)
    assert r["moc_w"] == 11000 and r["energia_kwh"] == 11.0 and "za krótkie" in r["tekst"]


def reference(buy, sell, energy, pv, f=1.24, margin=1.0, cap=32.154, max_soc=95, share=0.5):
    """Independent re-implementation of the planner (same rules, plain Python)."""
    ok, hmin = [], None
    for h in range(24):
        later = max(sell[h + 1:], default=None)
        good = later is not None and later - buy[h] * f >= margin - 1e-6
        ok.append(good)
        if good and (hmin is None or buy[h] < buy[hmin]):
            hmin = h
    if hmin is None:
        return None
    a = b = hmin
    while a > 0 and ok[a - 1]:
        a -= 1
    while b < 23 and ok[b + 1]:
        b += 1
    n = b - a + 1
    target = int((max(cap * max_soc / 100 - energy, 0) - pv * share) * 10) / 10
    if target < 1.0:
        return "noroom"
    power = min(max(math.ceil(target / n * 1000 / 500 - 1e-12) * 500, 1000), 11000)
    if power * n / 1000 < target - 1e-4:
        target = int(power * n / 1000 * 10) / 10
    dur = min(int(math.ceil(target / (power / 1000) * 60 / 5 - 1e-12)) * 5, n * 60)
    best = None
    for k in range(a, b + 1):
        if k * 60 + dur > (b + 1) * 60:
            continue
        w = c = 0
        for j in range(k, b + 1):
            ov = min(k * 60 + dur, (j + 1) * 60) - max(k * 60, j * 60)
            if ov > 0:
                w += ov
                c += ov * buy[j]
        avg = c / w
        s0 = (k * 60 + dur + 59) // 60
        if any(sell[s] - avg * f >= margin - 1e-6 for s in range(s0, 24)) and (best is None or avg < best[1] - 1e-6):
            best = (k, avg)
    return "nosell" if best is None else {"k": best[0], "power": power, "target": target}


def test_planner_matches_independent_implementation_on_random_days():
    rng = random.Random(7)
    compared = 0
    for _ in range(80):
        buy = [round(rng.uniform(0.2, 3.2), 2) for _ in range(24)]
        sell = [round(b * rng.uniform(0.6, 0.9), 2) for b in buy]
        for h in rng.sample(range(10, 24), rng.randint(1, 4)):
            sell[h] = round(sell[h] + rng.uniform(0.5, 2.5), 2)
        soc, pv = rng.choice([20, 40, 65, 80, 90]), rng.choice([0, 3, 8, 12, 25])
        energy = round(32.154 * soc / 100, 1)
        got = run_planner(inverter(soc, energy, pv), prices(buy, sell), {}, NOW)
        want = reference(buy, sell, energy, pv)
        if want is None:
            assert got["ok"] is False and got["powod"].startswith("Brak okazji")
        elif isinstance(want, str):
            assert got["ok"] is False
        else:
            compared += 1
            assert got["ok"] and got["moc_w"] == want["power"] and int(got["start"][11:13]) == want["k"]
            assert abs(got["energia_kwh"] - want["target"]) < 0.051
    assert compared > 25


# ---------------------------------------------------------------- patched calendar script
def calendar_vars(helpers, **fields):
    doc = load("kalendarz_dodaj_ladowanie.yaml")
    env = make_env(helpers, {}, NOW)
    ctx = render_variables(doc["sequence"][0], env, dict(fields))
    return {k: ctx[k] for k in ("start_dt", "end_dt", "dzien_koniec", "moc_w")}


def helpers(start, end, power="3500"):
    return {"input_datetime.magazyn_start_ladowania": start, "input_datetime.magazyn_koniec_ladowania": end,
            "input_number.magazyn_moc_ladowania": power}


def test_calendar_script_without_parameters_behaves_as_before():
    r = calendar_vars(helpers("2026-11-04 02:00:00", "2026-11-04 04:00:00"))
    assert (r["end_dt"], r["moc_w"]) == ("2026-11-04 04:00:00", 3500)
    # old end date left in the helper: end time is taken over to the start day, as before
    r = calendar_vars(helpers("2026-11-05 02:00:00", "2026-11-04 04:00:00", "-4000"))
    assert (r["end_dt"], r["moc_w"]) == ("2026-11-05 04:00:00", 4000)


def test_calendar_script_window_over_midnight_and_parameters():
    r = calendar_vars(helpers("2026-11-04 22:00:00", "2026-11-05 03:00:00"))
    assert r["end_dt"] == "2026-11-05 03:00:00" and r["dzien_koniec"] == "2026-11-05"
    r = calendar_vars(helpers("2026-11-01 00:00:00", "2026-11-01 01:00:00"),
                      start="2026-11-04 23:00:00", koniec="2026-11-05 02:30:00", moc=3500)
    assert (r["start_dt"], r["end_dt"], r["moc_w"]) == ("2026-11-04 23:00:00", "2026-11-05 02:30:00", 3500)
    r = calendar_vars(helpers("2026-11-04 02:00:00", "2026-11-04 04:00:00"), start="", koniec="", moc="")
    assert (r["start_dt"], r["end_dt"], r["moc_w"]) == ("2026-11-04 02:00:00", "2026-11-04 04:00:00", 3500)


# ---------------------------------------------------------------- executor
def executor(zapis, now, kal=None, after=None, preview=False):
    doc = load("pstryk_arbitraz_zaplanuj.yaml")
    env = make_env({"input_text.pstryk_sell_arbitraz_plan": zapis}, {}, now)
    seq = doc["sequence"]
    ctx = render_variables(seq[0], env, {"podglad": preview})
    cond = lambda step: native(env.from_string(step["if"][0]["condition"] == "template" and step["if"][0]["value_template"]).render(**ctx))
    out = {"missing": cond(seq[1]), "already": cond(seq[2]), "expired": cond(seq[3]), "start_eff": ctx["start_eff"]}
    if not (out["missing"] or out["already"] or out["expired"]):
        ctx["kal"] = kal or {}
        render_variables(seq[5], env, ctx)
        out["conflicts"] = ctx["konflikty"]
        if after is not None:
            ctx["po"] = after
            render_variables(seq[10], env, ctx)
            out["created"] = ctx["jest"]
    return out


ZAPIS = "2026-11-04 00:00:00;2026-11-04 04:45:00;1500;7.1;0.4;2.5;13.1;n;17:00-18:00"


def test_executor_states_and_window_shift():
    assert executor("unknown", NOW)["missing"] and executor("brak;2026-11-04;x", NOW)["missing"]
    assert executor(ZAPIS.replace(";n;", ";z;"), NOW)["already"]
    assert executor(ZAPIS, dt.datetime(2026, 11, 4, 4, 50, tzinfo=TZ))["expired"]
    # fewer than 10 minutes left is treated as expired, 15 minutes left still gets planned
    assert executor(ZAPIS, dt.datetime(2026, 11, 4, 4, 38, tzinfo=TZ))["expired"]
    assert not executor(ZAPIS, dt.datetime(2026, 11, 4, 4, 30, tzinfo=TZ))["expired"]
    assert executor(ZAPIS, NOW)["start_eff"] == "2026-11-04 00:00:00"
    assert executor(ZAPIS, dt.datetime(2026, 11, 4, 1, 10, tzinfo=TZ))["start_eff"] == "2026-11-04 01:11:00"


def test_executor_conflicts_and_verification():
    feed_in = {"calendar.feed_in_magazynu": {"events": [
        {"summary": "Feed-in", "start": "2026-11-04T03:00:00+01:00", "end": "2026-11-04T04:00:00+01:00"}]}}
    assert executor(ZAPIS, NOW, feed_in)["conflicts"] == "Feed-in 04.11 03:00-04:00"
    assert executor(ZAPIS, NOW, {})["conflicts"] == ""
    event = {"summary": "Ładowanie", "start": "2026-11-04 00:00:00", "end": "2026-11-04 04:45:00", "description": "MOC:-1500"}
    assert executor(ZAPIS, NOW, {}, {"calendar.ladowanie_magazynu": {"events": [event]}})["created"] is True
    assert executor(ZAPIS, NOW, {}, {"calendar.ladowanie_magazynu": {"events": []}})["created"] is False
    wrong_power = dict(event, description="MOC:-3000")
    assert executor(ZAPIS, NOW, {}, {"calendar.ladowanie_magazynu": {"events": [wrong_power]}})["created"] is False


# ---------------------------------------------------------------- coordinator and dashboard
class _State:
    def __init__(self, attributes):
        self.attributes = attributes


def coordinator_guard(trigger, now):
    default = load("pstryk_arbitraz_koordynator.yaml")["actions"][0]["default"]
    env = make_env({}, {}, now)
    ctx = {"trigger": trigger}
    render_variables(default[0], env, ctx)
    return ctx["reczne"], native(env.from_string(default[1]["value_template"]).render(**ctx))


def test_coordinator_ignores_stale_event_but_not_manual_run():
    event = {"platform": "state", "id": "opublikowano", "to_state": _State({
        "event_type": "published", "published_at": "2026-11-03T12:05:00.621389+01:00", "prices_for": "2026-11-04"})}
    assert coordinator_guard(event, dt.datetime(2026, 11, 3, 12, 6, tzinfo=TZ)) == (False, True)
    assert coordinator_guard(event, dt.datetime(2026, 11, 3, 18, 0, tzinfo=TZ)) == (False, False)
    assert coordinator_guard({"platform": None}, dt.datetime(2026, 11, 3, 18, 0, tzinfo=TZ)) == (True, True)


def test_notification_buttons_are_dropped_on_collision():
    default = load("pstryk_arbitraz_koordynator.yaml")["actions"][0]["default"]
    template = default[4]["then"][0]["data"]["data"]["actions"]
    env = make_env({}, {}, NOW)
    assert len(native(env.from_string(template).render(plan={"kolizja": ""}))) == 2
    assert native(env.from_string(template).render(plan={"kolizja": "Feed-in 03:00-04:00"})) == []


def test_dashboard_card_renders_each_state_with_short_dates():
    card = load("dashboard_karta.yaml")["cards"][0]["content"]

    def render(value):
        return make_env({"input_text.pstryk_sell_arbitraz_plan": value}, {}, NOW).from_string(card).render()
    text = render(ZAPIS)
    assert "04.11.2026 00:00" in text and "czeka na zatwierdzenie" in text and "0,40 zł/kWh" in text
    assert "zaplanowano w kalendarzu" in render(ZAPIS.replace(";n;", ";z;"))
    assert "Brak planu na 04.11.2026: Brak okazji" in render("brak;2026-11-04;Brak okazji")
    assert "Przelicz plan" in render("unknown")
