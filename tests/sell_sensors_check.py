"""Checks for the sell revenue / energy sold / average sell price sensors.

Run by tests/test_sell_sensors.py in a separate process, so its Home Assistant
stand-ins never mix with the ones the other test modules install.

Home Assistant is not installed here: the HA names the integration imports are
replaced by small stubs. The real cost coordinator and sensor classes run
against a fake API that returns the monthly sell values from a real
unified-metrics response (Magnuszew, fetched 2026-10-16).
"""
import asyncio
import enum
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Europe/Warsaw")
NOW = [datetime(2026, 10, 16, 23, 40, tzinfo=TZ)]


def mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


def parse_datetime(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


dt = mod(
    "homeassistant.util.dt",
    now=lambda: NOW[0],
    utcnow=lambda: NOW[0].astimezone(timezone.utc),
    as_utc=lambda d: (d if d.tzinfo else d.replace(tzinfo=TZ)).astimezone(timezone.utc),  # naive = default zone, as in HA
    as_local=lambda d: d.astimezone(TZ),
    parse_datetime=parse_datetime,
)
mod("homeassistant.util", dt=dt)


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator:
    def __init__(self, hass, logger, name=None, **kw):
        self.hass = hass
        self.data = None
        self.last_update_success = True

    def async_update_listeners(self):
        pass


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.hass = None


class Store:
    def __init__(self, *a, **k):
        self.saved = None

    async def async_load(self):
        return self.saved

    async def async_save(self, data):
        self.saved = data


class SensorStateClass(str, enum.Enum):
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"


class SensorDeviceClass(str, enum.Enum):
    MONETARY = "monetary"
    ENERGY = "energy"
    TIMESTAMP = "timestamp"


mod("homeassistant")
mod("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
mod("homeassistant.config_entries", ConfigEntry=object)
mod("homeassistant.exceptions", HomeAssistantError=Exception)
mod("homeassistant.components")
mod("homeassistant.components.persistent_notification")
mod("homeassistant.components.button", ButtonEntity=type("ButtonEntity", (), {}))
mod("homeassistant.components.sensor", SensorEntity=type("SensorEntity", (), {}),
    SensorStateClass=SensorStateClass, SensorDeviceClass=SensorDeviceClass)
mod("homeassistant.helpers")
mod("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=DataUpdateCoordinator,
    UpdateFailed=UpdateFailed, CoordinatorEntity=CoordinatorEntity)
mod("homeassistant.helpers.event", async_track_point_in_time=lambda *a, **k: (lambda: None))
mod("homeassistant.helpers.restore_state", RestoreEntity=type("RestoreEntity", (), {}))
mod("homeassistant.helpers.storage", Store=Store)
mod("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda h: None)
mod("homeassistant.helpers.translation", async_get_translations=None)
mod("homeassistant.helpers.entity_registry",
    RegistryEntryHider=type("RegistryEntryHider", (), {"USER": "user", "INTEGRATION": "integration"}),
    RegistryEntryDisabler=type("RegistryEntryDisabler", (), {"USER": "user", "INTEGRATION": "integration"}))
mod("homeassistant.loader", async_get_integration=None)
mod("aiohttp", ClientError=Exception, ClientSession=object, ClientResponse=object,
    ClientTimeout=object)

pkg = mod("pstryk")
pkg.__path__ = [str(ROOT / "custom_components" / "pstryk")]
from pstryk import sensor as S  # noqa: E402
from pstryk.energy_cost_coordinator import PstrykCostDataUpdateCoordinator  # noqa: E402

# Monthly energy_sold_value from the real response (frame starts are UTC).
REAL_MONTHS = [
    ("2024-09-30T22:00:00Z", 0.0), ("2024-10-31T23:00:00Z", 0.0), ("2024-11-30T23:00:00Z", 0.0),
    ("2024-12-31T23:00:00Z", 0.0), ("2025-01-31T23:00:00Z", 0.0), ("2025-05-31T22:00:00Z", 0.0),
    ("2025-12-31T23:00:00Z", 0.0), ("2026-07-31T22:00:00Z", 0.0266515908),
    ("2026-08-31T22:00:00Z", 115.8504632427), ("2026-09-30T22:00:00Z", 322.3579084797002),
]
KWH_PER_PLN = 1 / 1.5  # the check response had no kWh; any fixed ratio tests the maths


BOUGHT_KWH, BUY_COST = 100.0, 80.0  # per month frame, for the buy totals


def month_frame(start, sold):
    return {"start": start, "end": None, "is_live": False,
            "metrics": {"meter_values": {"energy_active_export_register": sold * KWH_PER_PLN,
                                         "energy_active_import_register": BOUGHT_KWH,
                                         "energy_balance": BOUGHT_KWH - sold * KWH_PER_PLN},
                        "cost": {"energy_sold_value": sold, "energy_import_cost": BUY_COST}}}


class FakeAPI:
    def __init__(self, months):
        self.urls = []
        self.months = months

    async def fetch(self, url, **kw):
        self.urls.append(url)
        if "resolution=day" in url:
            return {"frames": [{"start": "2026-10-15T22:00:00Z", "is_live": True,
                                "metrics": {"meter_values": {"energy_active_import_register": 14.86,
                                                             "energy_active_export_register": 3.2,
                                                             "energy_balance": 11.66},
                                            "cost": {"energy_sold_value": 2.71}}}]}
        return {"frames": [month_frame(s, v) for s, v in self.months]}

    def budget_room_soon(self, **kw):
        return True


results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


async def main():
    api = FakeAPI(REAL_MONTHS)
    c = PstrykCostDataUpdateCoordinator(None, api, 1, 1, entry_id="e")
    c.data = await c._async_update_data()

    check("cost update: still exactly 2 requests (day + month)", len(api.urls) == 2, f"{len(api.urls)}")
    month_url = next(u for u in api.urls if "resolution=month" in u)
    check("month request starts 01.10.2024 local", "window_start=2024-09-30T22:00:00Z" in month_url, month_url)
    check("month request ends 01.01.2027 local", "window_end=2026-12-31T23:00:00Z" in month_url, month_url)

    years = c.data["history"]["years"]
    check("history: 2026 real revenue 438.24, frames grouped by local year",
          years.get("2026", {}).get("sell_revenue") == 438.24 and "2024" in years and "2025" in years, str(years))
    check("yearly = current year only (not the whole history)",
          round(c.data["yearly"]["total_sold"], 2) == 438.24, str(c.data["yearly"]["total_sold"]))
    check("monthly = October 2026", round(c.data["monthly"]["total_sold"], 2) == 322.36,
          str(c.data["monthly"]["total_sold"]))

    flow = {f"{p}_{m}": S.PstrykFlowSensor(c, m, p, "e") for m, p in S.FLOW_SENSORS}
    tot_rev = S.PstrykTotalSellSensor(c, "sell_revenue", "e")
    tot_kwh = S.PstrykTotalSellSensor(c, "energy_sold", "e")
    tot_bought = S.PstrykTotalSellSensor(c, "energy_bought", "e")
    tot_cost = S.PstrykTotalSellSensor(c, "buy_cost", "e")
    avg = {p: S.PstrykAverageSellPriceSensor(c, p, "e") for p in ("monthly", "yearly", "total")}
    avg_buy_total = S.PstrykAverageSellPriceSensor(c, "total", "e", "buy")
    tot_balance = S.PstrykTotalBalanceSensor(c, "e")
    energy_balance = {p: S.PstrykEnergyBalanceSensor(c, p, "e") for p in S.BALANCE_PERIODS}
    every = [*flow.values(), tot_rev, tot_kwh, tot_bought, tot_cost, *avg.values(),
             avg_buy_total, tot_balance, *energy_balance.values()]

    check("entity ids", sorted(s.entity_id for s in every) == sorted([
        "sensor.pstryk_daily_energy_bought", "sensor.pstryk_daily_energy_sold",
        "sensor.pstryk_daily_buy_cost", "sensor.pstryk_daily_sell_revenue",
        "sensor.pstryk_monthly_sell_revenue", "sensor.pstryk_yearly_sell_revenue",
        "sensor.pstryk_monthly_energy_sold", "sensor.pstryk_yearly_energy_sold",
        "sensor.pstryk_total_sell_revenue", "sensor.pstryk_total_energy_sold",
        "sensor.pstryk_total_energy_bought", "sensor.pstryk_total_buy_cost",
        "sensor.pstryk_sell_monthly_average", "sensor.pstryk_sell_yearly_average",
        "sensor.pstryk_sell_total_average",
        "sensor.pstryk_monthly_buy_cost", "sensor.pstryk_yearly_buy_cost",
        "sensor.pstryk_monthly_energy_bought", "sensor.pstryk_yearly_energy_bought",
        "sensor.pstryk_buy_total_average", "sensor.pstryk_total_financial_balance",
        "sensor.pstryk_daily_energy_balance", "sensor.pstryk_monthly_energy_balance",
        "sensor.pstryk_yearly_energy_balance"]))
    ids = [s.unique_id for s in every]
    check("24 distinct unique ids", len(set(ids)) == 24, str(ids))
    check("total average: ids like the original averages",
          (avg["total"].name, avg["total"].unique_id) == ("Pstryk Total Sell Price Average", "pstryk_sell_total_average"))
    check("total bought/cost: names, units, never reset",
          (tot_bought.name, tot_bought._attr_native_unit_of_measurement, tot_bought._attr_state_class,
           tot_cost.name, tot_cost._attr_native_unit_of_measurement, tot_cost._attr_state_class)
          == ("Pstryk Total Buy Volume", "kWh", S.SensorStateClass.TOTAL_INCREASING,
              "Pstryk Total Buy Cost", "PLN", S.SensorStateClass.TOTAL)
          and not hasattr(tot_cost, "last_reset"))
    # 10 month frames since 01.10.2024: 3 in 2024, 3 in 2025, 4 in 2026 (local months)
    check("total energy bought = all 10 months (1000 kWh)", tot_bought.native_value == 1000.0,
          str(tot_bought.native_value))
    check("total buy cost = all 10 months (800 PLN)", tot_cost.native_value == 800.0, str(tot_cost.native_value))
    check("history per year: bought/cost", (years["2024"]["energy_bought"], years["2025"]["buy_cost"],
                                            years["2026"]["energy_bought"]) == (300.0, 240.0, 400.0), str(years))
    check("current year live from yearly", c.data["yearly"]["fae_usage"] == 400.0 and
          round(c.data["yearly"]["total_cost"], 2) == 320.0)

    check("daily energy bought / sold / sell revenue",
          (flow["daily_energy_bought"].native_value, flow["daily_energy_sold"].native_value,
           flow["daily_sell_revenue"].native_value) == (14.86, 3.2, 2.71))
    check("total revenue 438.24", tot_rev.native_value == 438.24, str(tot_rev.native_value))
    check("total kWh = sum of real frames", abs(tot_kwh.native_value - 292.157) < 0.002, str(tot_kwh.native_value))
    check("average = revenue / kWh (1.5 PLN/kWh)",
          all(abs(a.native_value - 1.5) < 0.0005 for a in avg.values()),
          str({p: a.native_value for p, a in avg.items()}))

    # purchase side (2.3.0): the counterparts of the sell sensors
    m, y = c.data["monthly"], c.data["yearly"]
    check("monthly/yearly buy cost and volume = the period data",
          (flow["monthly_buy_cost"].native_value, flow["yearly_buy_cost"].native_value,
           flow["monthly_energy_bought"].native_value, flow["yearly_energy_bought"].native_value)
          == (round(m["total_cost"], 4), 320.0, round(m["fae_usage"], 4), 400.0)
          and flow["yearly_buy_cost"].native_value > 0,
          str((m["total_cost"], m["fae_usage"])))
    check("buy cost is money (total, resets per period), buy volume is energy (total_increasing)",
          (flow["monthly_buy_cost"].last_reset == datetime(2026, 10, 1, tzinfo=TZ),
           flow["yearly_buy_cost"].last_reset == datetime(2026, 1, 1, tzinfo=TZ),
           flow["monthly_energy_bought"].last_reset, flow["yearly_energy_bought"]._attr_state_class)
          == (True, True, None, S.SensorStateClass.TOTAL_INCREASING))
    check("total buy average = total cost / total kWh = 0.8 PLN/kWh",
          (avg_buy_total.name, avg_buy_total.unique_id, avg_buy_total.native_value)
          == ("Pstryk Total Buy Price Average", "pstryk_buy_total_average", 0.8),
          str(avg_buy_total.native_value))
    check("total buy average attributes: cost, kWh, per-year averages",
          (avg_buy_total.extra_state_attributes["Buy cost"], avg_buy_total.extra_state_attributes["Energy bought"],
           avg_buy_total.extra_state_attributes["2026"]) == (800.0, 1000.0, 0.8),
          str(avg_buy_total.extra_state_attributes))
    check("total financial balance = total buy cost - total sell revenue (positive = net cost)",
          (tot_balance.name, tot_balance.unique_id, tot_balance.native_value)
          == ("Pstryk Total Financial Balance", "pstryk_financial_balance_total", round(800.0 - 438.24, 2)),
          str(tot_balance.native_value))
    check("energy balance = the API's energy_balance of the period (day, month, sum of the year)",
          (energy_balance["daily"].native_value, energy_balance["monthly"].native_value,
           energy_balance["yearly"].native_value)
          == (11.66, round(m["energy_balance"], 3), round(y["energy_balance"], 3)),
          str({p: e.native_value for p, e in energy_balance.items()}))
    check("energy balance of the year = sum of the 4 monthly frames of 2026 (400 - 292.16 kWh)",
          abs(y["energy_balance"] - (4 * BOUGHT_KWH - 438.24 * KWH_PER_PLN)) < 0.01, str(y["energy_balance"]))
    check("energy balance: names, ids, unit, negative allowed (total, not total_increasing)",
          (energy_balance["daily"].name, energy_balance["daily"].unique_id,
           energy_balance["daily"]._attr_native_unit_of_measurement,
           energy_balance["daily"]._attr_state_class,
           energy_balance["daily"].last_reset == datetime(2026, 10, 16, tzinfo=TZ))
          == ("Pstryk Daily Energy Balance", "pstryk_energy_balance_daily", "kWh",
              S.SensorStateClass.TOTAL, True))
    # taken as given: a balance that differs from bought - sold is shown as the API reports it
    odd = c._process_monthly_data_simple({"frames": [{
        "start": "2026-09-30T22:00:00Z", "metrics": {"meter_values": {
            "energy_active_import_register": 10.0, "energy_active_export_register": 4.0,
            "energy_balance": 7.5}, "cost": {}}}]})
    saved = c.data["monthly"]
    c.data["monthly"] = odd
    check("energy balance is the API value, not recomputed (7.5, not 10 - 4)",
          energy_balance["monthly"].native_value == 7.5, str(energy_balance["monthly"].native_value))
    odd["energy_balance"] = -5.0
    check("energy balance is negative when more was sold than bought",
          energy_balance["monthly"].native_value == -5.0, str(energy_balance["monthly"].native_value))
    del odd["energy_balance"]  # period data saved by 2.2.x
    check("period data saved before 2.3.0 (no energy_balance): unknown, not a computed stand-in",
          energy_balance["monthly"].native_value is None)
    c.data["monthly"] = saved
    flow_missing = S.PstrykEnergyBalanceSensor(PstrykCostDataUpdateCoordinator(None, FakeAPI([]), 1, 1, entry_id="e"),
                                               "daily", "e")
    check("energy balance without data: unknown, not 0", flow_missing.native_value is None)

    cost_before = c.data["monthly"]["total_cost"]
    c.data["monthly"]["total_cost"] = -cost_before  # a cost reported as a negative number
    check("buy totals use the cost as a positive number", S._flow_totals(c, "monthly", "buy")[0] == cost_before)
    c.data["monthly"]["total_cost"] = cost_before


    # months before the contract: meter readings but no cost and no revenue
    pre = [(f"2025-12-31T23:00:00Z", 0.0), ("2026-01-31T23:00:00Z", 0.0), ("2026-02-28T23:00:00Z", 0.0)]
    def raw_frame(start, bought, cost, sold_kwh, sold_value):
        return {"start": start, "end": None, "is_live": False,
                "metrics": {"meter_values": {"energy_active_import_register": bought,
                                             "energy_active_export_register": sold_kwh,
                                             "energy_balance": bought - sold_kwh},
                            "cost": {"energy_import_cost": cost, "energy_sold_value": sold_value}}}

    class ContractAPI(FakeAPI):
        async def fetch(self, url, **kw):
            self.urls.append(url)
            if "resolution=day" in url:
                return {"frames": [raw_frame("2026-10-15T22:00:00Z", 28.8, 20.0, 0.0, 0.0) | {"is_live": True}]}
            return {"frames": [raw_frame(s_, 40.0, 0.0, 5.0, 0.0) for s_, _ in pre]
                    + [raw_frame("2026-09-30T22:00:00Z", 100.0, 80.0, 10.0, 15.0)]}

    cc = PstrykCostDataUpdateCoordinator(None, ContractAPI([]), 1, 1, entry_id="e")
    cc.data = await cc._async_update_data()
    cy = cc.data["yearly"]
    check("yearly volumes stay as the API reports them (3 x 40 + 100 kWh bought, 3 x 5 + 10 sold)",
          (cy["fae_usage"], cy["rae_usage"]) == (220.0, 25.0), str((cy["fae_usage"], cy["rae_usage"])))
    check("yearly billed energy = only the month with cost / revenue",
          (cy["fae_billed"], cy["rae_billed"]) == (100.0, 10.0), str((cy["fae_billed"], cy["rae_billed"])))
    avg_c = {(d, p): S.PstrykAverageSellPriceSensor(cc, p, "e", d)
             for d in ("buy", "sell") for p in ("monthly", "yearly", "total")}
    check("buy average over the billed month only: 80 / 100 = 0.8 (not 80 / 220)",
          [avg_c[("buy", p)].native_value for p in ("monthly", "yearly", "total")] == [0.8, 0.8, 0.8],
          str([avg_c[("buy", p)].native_value for p in ("monthly", "yearly", "total")]))
    check("sell average over the month with revenue only: 15 / 10 = 1.5 (not 15 / 25)",
          [avg_c[("sell", p)].native_value for p in ("monthly", "yearly", "total")] == [1.5, 1.5, 1.5],
          str([avg_c[("sell", p)].native_value for p in ("monthly", "yearly", "total")]))
    check("total volumes stay literal: bought 220, sold 25",
          (S.PstrykTotalSellSensor(cc, "energy_bought", "e").native_value,
           S.PstrykTotalSellSensor(cc, "energy_sold", "e").native_value) == (220.0, 25.0))
    check("the average's attributes show the billed energy it used",
          (avg_c[("buy", "yearly")].extra_state_attributes["Energy bought"],
           avg_c[("buy", "total")].extra_state_attributes["Energy bought"],
           avg_c[("buy", "total")].extra_state_attributes["2026"]) == (100.0, 100.0, 0.8))
    daily_cost0 = S.PstrykAverageSellPriceSensor(cc, "daily", "e", "sell")
    check("daily sell average with no revenue yet: unknown (no kWh with a price), not 0",
          daily_cost0.native_value is None, str(daily_cost0.native_value))
    check("daily buy average = cost / billed kWh (20 / 28.8)",
          S.PstrykAverageSellPriceSensor(cc, "daily", "e", "buy").native_value == round(20.0 / 28.8, 4))

    # period data saved before 2.3.0 has no billed energy: no new value can be computed. A
    # sensor that never had one is unknown (not a guessed number); one that has keeps its value.
    saved_old = {k: v for k, v in cc.data["yearly"].items() if k not in ("fae_billed", "rae_billed")}
    cc.data["yearly"] = saved_old
    never = S.PstrykAverageSellPriceSensor(cc, "yearly", "e", "buy")
    check("yearly average from data saved before 2.3.0, never computed: unknown",
          never.native_value is None and never.extra_state_attributes == {}, str(never.native_value))
    check("yearly average from data saved before 2.3.0: the last value stays, with its date",
          avg_c[("buy", "yearly")].native_value == 0.8
          and "Value from" in avg_c[("buy", "yearly")].extra_state_attributes,
          f"{avg_c[('buy', 'yearly')].native_value}")
    check("a monthly average is not affected by the old yearly data", avg_c[("buy", "monthly")].native_value == 0.8)

    # nothing sold -> no average (no fake 0.00, no division by zero)
    c.data["monthly"]["rae_billed"] = 0
    fresh_avg = S.PstrykAverageSellPriceSensor(c, "monthly", "e")
    check("average None when nothing sold", fresh_avg.native_value is None)

    # monetary sensors reset per period, energy sensors use total_increasing
    check("daily sell revenue last_reset = 16.10.2026 00:00",
          flow["daily_sell_revenue"].last_reset == datetime(2026, 10, 16, tzinfo=TZ))
    check("energy sensors have no last_reset", flow["daily_energy_sold"].last_reset is None)

    # restart: history comes back from the store without a request
    c2 = PstrykCostDataUpdateCoordinator(None, FakeAPI([]), 1, 1, entry_id="e")
    await c._async_save(c.data)
    c2._store = c._store
    await c2.async_restore()
    tot2 = S.PstrykTotalSellSensor(c2, "sell_revenue", "e")
    check("restart: total restored, no request", tot2.native_value == 438.24 and not c2.api_client.urls,
          str(tot2.native_value))

    # saved history from before buy totals existed: unknown until the next cost run
    c_old = PstrykCostDataUpdateCoordinator(None, FakeAPI([]), 1, 1, entry_id="e")
    c_old.data = {"yearly": dict(c.data["yearly"]), "history": {"years": {
        "2025": {"sell_revenue": 0.0, "energy_sold": 0.0}}, "fetched_at": NOW[0].isoformat()}}
    old_cost = S.PstrykTotalSellSensor(c_old, "buy_cost", "e")
    old_rev = S.PstrykTotalSellSensor(c_old, "sell_revenue", "e")
    check("old saved history: buy total unknown (no fake low value), sell total still works",
          old_cost.native_value is None and old_rev.native_value == 438.24,
          f"{old_cost.native_value}, {old_rev.native_value}")

    old_avg = S.PstrykAverageSellPriceSensor(c_old, "total", "e", "buy")
    old_bal = S.PstrykTotalBalanceSensor(c_old, "e")
    check("old saved history: total buy average and total balance unknown, not a wrong number",
          old_avg.native_value is None and old_bal.native_value is None,
          f"{old_avg.native_value}, {old_bal.native_value}")

    # next year: closed 2026 from history, 2027 live
    NOW[0] = datetime(2027, 2, 10, 12, 0, tzinfo=TZ)
    months = REAL_MONTHS + [("2026-12-31T23:00:00Z", 30.0), ("2027-01-31T23:00:00Z", 20.0)]
    c3 = PstrykCostDataUpdateCoordinator(None, FakeAPI(months), 1, 1, entry_id="e")
    c3.data = await c3._async_update_data()
    t3 = S.PstrykTotalSellSensor(c3, "sell_revenue", "e")
    y3 = S.PstrykFlowSensor(c3, "sell_revenue", "yearly", "e")
    a3 = S.PstrykAverageSellPriceSensor(c3, "total", "e")
    check("2027: yearly = 50.00, total = 488.24", (y3.native_value, t3.native_value) == (50.0, 488.24),
          f"{y3.native_value}, {t3.native_value}")
    attrs = t3.extra_state_attributes
    check("total attributes: per year + dd.mm.yyyy", attrs.get("2026") == 438.24 and attrs.get("2027") == 50.0
          and attrs["History fetched"].startswith("10.02.2027"), str(attrs))
    tb3 = S.PstrykTotalSellSensor(c3, "energy_bought", "e")
    check("2027: total bought = 12 months (1200 kWh), attrs per year",
          tb3.native_value == 1200.0 and tb3.extra_state_attributes.get("2027") == 200.0,
          f"{tb3.native_value}, {tb3.extra_state_attributes}")
    check("total average attributes: per-year averages",
          abs(a3.extra_state_attributes["2026"] - 1.5) < 0.0005, str(a3.extra_state_attributes))

    print(f"\n{sum(results)}/{len(results)} passed")
    return all(results)


sys.exit(0 if asyncio.run(main()) else 1)
