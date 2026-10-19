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
    as_utc=lambda d: d.astimezone(timezone.utc),
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
                                         "energy_active_import_register": BOUGHT_KWH},
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
                                                             "energy_active_export_register": 3.2},
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
    every = [*flow.values(), tot_rev, tot_kwh, tot_bought, tot_cost, *avg.values()]

    check("entity ids", sorted(s.entity_id for s in every) == sorted([
        "sensor.pstryk_daily_energy_bought", "sensor.pstryk_daily_energy_sold",
        "sensor.pstryk_daily_buy_cost", "sensor.pstryk_daily_sell_revenue",
        "sensor.pstryk_monthly_sell_revenue", "sensor.pstryk_yearly_sell_revenue",
        "sensor.pstryk_monthly_energy_sold", "sensor.pstryk_yearly_energy_sold",
        "sensor.pstryk_total_sell_revenue", "sensor.pstryk_total_energy_sold",
        "sensor.pstryk_total_energy_bought", "sensor.pstryk_total_buy_cost",
        "sensor.pstryk_sell_monthly_average", "sensor.pstryk_sell_yearly_average",
        "sensor.pstryk_sell_total_average"]))
    ids = [s.unique_id for s in every]
    check("15 distinct unique ids", len(set(ids)) == 15, str(ids))
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

    # nothing sold -> no average (no fake 0.00, no division by zero)
    c.data["monthly"]["rae_usage"] = 0
    check("average None when nothing sold", avg["monthly"].native_value is None)

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
