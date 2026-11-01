"""The averages keep their last value (restored at start-up) until a new one can be computed.

Reuses the stand-ins of tests/test_refresh.py. After `_cost_runs_then_restart` the
clock stands at the restart time, 2 October 2026 15:00 (Warsaw).
"""
import types
from datetime import datetime, timedelta

import pytest

import test_refresh as tr
from test_refresh import env, mods  # noqa: F401  (pytest fixtures)

RESTART = (2026, 10, 2, 15, 0)
TODAY_STAMP = "02.10.2026 14:50:00"  # a "Value from" of the running day, month and year
OLD_BILLED_KEYS = ("fae_billed", "rae_billed")


def _state(value="1.5", attributes=None, last_updated=None):
    return types.SimpleNamespace(state=value, attributes=dict(attributes or {}), last_updated=last_updated)


def _kept(stamp=TODAY_STAMP, **extra):
    attributes = {"Value from": stamp, "Energy bought": 10.0, "Total cost": 15.0, **extra}
    return _state("1.5", attributes)


def _restarted(mods, env, billed=False):
    """The cost coordinator after a restart; its period data lacks the billed energy unless `billed`."""
    _, _, cost, coords = tr._run(tr._cost_runs_then_restart(mods, env, RESTART))
    if not billed:
        for period in ("daily", "monthly", "yearly"):
            for key in OLD_BILLED_KEYS:
                cost.data[period].pop(key, None)
        for entry in (cost.data.get("history") or {}).get("years", {}).values():
            entry.pop("energy_bought_billed", None)
            entry.pop("energy_sold_billed", None)
    return cost, coords


def _period_sensor(mods, cost, coords, period, last_state=None, price_type="buy"):
    return tr._average(mods, cost, coords, period, last_state) if price_type == "buy" else _sell(mods, cost, coords, period, last_state)


def _sell(mods, cost, coords, period, last_state):
    sensor = mods.sensor.PstrykAveragePriceSensor(cost, coords["sell"], period, "e")
    sensor.hass = cost.hass
    sensor.last_state = last_state
    tr._run(sensor.async_added_to_hass())
    return sensor


def _total(mods, cost, last_state=None, direction="buy"):
    sensor = mods.sensor.PstrykAverageSellPriceSensor(cost, "total", "e", direction)
    sensor.coordinator = cost
    sensor.hass = cost.hass
    sensor.entry_id = "e"
    sensor.last_state = last_state
    tr._run(sensor.async_added_to_hass())
    return sensor


# ------------------------------------------------- the daily / monthly / yearly averages

@pytest.mark.parametrize("period", ["daily", "monthly", "yearly"])
def test_the_restored_value_stays_when_the_data_has_no_billed_energy(mods, env, period):
    """The case of a restart right after the update: saved data has no billed energy."""
    cost, coords = _restarted(mods, env)
    sensor = _period_sensor(mods, cost, coords, period, _kept())
    assert sensor.native_value == 1.5
    assert sensor.available is True
    attrs = sensor.extra_state_attributes
    assert attrs["Value from"] == TODAY_STAMP
    assert attrs["Energy bought"] == 10.0 and attrs["Total cost"] == 15.0  # restored too


def test_a_new_value_replaces_the_restored_one_and_is_dated_by_its_data(mods, env):
    cost, coords = _restarted(mods, env, billed=True)
    sensor = _period_sensor(mods, cost, coords, "monthly", _kept())
    assert sensor.native_value == 2.0 and sensor.native_value != 1.5
    fetched = cost.fetched_at("monthly")
    assert fetched is not None
    assert sensor.extra_state_attributes["Value from"] == fetched.strftime("%d.%m.%Y %H:%M:%S")
    assert sensor.extra_state_attributes["Value from"] != TODAY_STAMP


def test_the_value_is_replaced_when_billed_data_arrives_later(mods, env):
    cost, coords = _restarted(mods, env)
    sensor = _period_sensor(mods, cost, coords, "monthly", _kept())
    assert sensor.native_value == 1.5
    cost.data["monthly"].update({"total_cost": 10.0, "fae_billed": 20.0})
    sensor._handle_cost_update()
    assert sensor.native_value == 0.5
    assert sensor.extra_state_attributes["Energy bought"] == 20.0
    # a later period without billed energy (e.g. data lost) does not erase it again
    cost.data["monthly"].pop("fae_billed")
    sensor._handle_cost_update()
    assert sensor.native_value == 0.5


@pytest.mark.parametrize("period,stamp,survives", [
    ("daily", "02.10.2026 00:00:01", True),
    ("daily", "01.10.2026 23:59:59", False),     # yesterday's daily average is not today's
    ("monthly", "01.10.2026 00:00:00", True),
    ("monthly", "30.09.2026 23:59:59", False),   # last month
    ("yearly", "01.01.2026 00:00:00", True),
    ("yearly", "31.12.2025 23:59:59", False),    # last year
])
def test_a_kept_value_belongs_to_its_own_period_only(mods, env, period, stamp, survives):
    cost, coords = _restarted(mods, env)
    sensor = _period_sensor(mods, cost, coords, period, _kept(stamp))
    assert (sensor.native_value == 1.5) is survives
    if not survives:
        assert sensor.native_value is None
        assert "Value from" not in sensor.extra_state_attributes


def test_a_state_of_an_earlier_version_is_dated_by_the_time_it_was_written(mods, env):
    cost, coords = _restarted(mods, env)
    today = tr.TZ.localize(datetime(2026, 10, 2, 14, 0)) if hasattr(tr.TZ, "localize") else datetime(2026, 10, 2, 14, 0, tzinfo=tr.TZ)
    yesterday = today - timedelta(days=1)
    kept = _period_sensor(mods, cost, coords, "daily", _state("1.5", {}, today))
    assert kept.native_value == 1.5
    assert kept.extra_state_attributes["Value from"] == "02.10.2026 14:00:00"
    dropped = _period_sensor(mods, cost, coords, "daily", _state("1.5", {}, yesterday))
    assert dropped.native_value is None
    undated = _period_sensor(mods, cost, coords, "daily", _state("1.5", {}, None))
    assert undated.native_value is None  # no date, no trust


@pytest.mark.parametrize("state", ["unknown", "unavailable", None, "abc", ""])
def test_unusable_states_are_not_restored(mods, env, state):
    cost, coords = _restarted(mods, env)
    sensor = _period_sensor(mods, cost, coords, "monthly", _state(state, {"Value from": TODAY_STAMP}))
    assert sensor.native_value is None


def test_unusable_attributes_do_not_break_the_restore(mods, env):
    cost, coords = _restarted(mods, env)
    sensor = _period_sensor(mods, cost, coords, "monthly", _kept(**{"Energy bought": "x"}))
    assert sensor.native_value is None  # a half-restored value is not shown
    sensor = _period_sensor(mods, cost, coords, "monthly", _kept("not a date"))
    assert sensor.native_value is None


def test_a_kept_value_ends_with_its_period_while_running(mods, env):
    cost, coords = _restarted(mods, env)
    sensor = _period_sensor(mods, cost, coords, "daily", _kept())
    assert sensor.native_value == 1.5
    tr.CLOCK[0] = tr.CLOCK[0] + timedelta(days=1)  # midnight passes; no billed energy yet
    sensor._handle_cost_update()
    assert sensor.native_value is None
    assert sensor.extra_state_attributes.get("Value from") is None


def test_the_kept_value_is_shown_while_there_is_no_cost_data_at_all(mods, env):
    """Restart with nothing saved and the API limit used up: the old value, not "unavailable"."""
    cost, coords = _restarted(mods, env)
    cost.data = None
    cost.last_update_success = False
    sensor = _period_sensor(mods, cost, coords, "monthly", _kept())
    assert sensor.native_value == 1.5
    assert sensor.available is True
    stale = _period_sensor(mods, cost, coords, "daily", _kept("01.10.2026 10:00:00"))
    assert stale.available is False
    assert stale.native_value is None  # not restored at all
    # ... and a value kept in memory stops being shown when its day is over
    tr.CLOCK[0] = tr.CLOCK[0] + timedelta(days=1)
    daily = _period_sensor(mods, cost, coords, "daily", _kept("03.10.2026 10:00:00"))
    assert daily.available is True
    tr.CLOCK[0] = tr.CLOCK[0] + timedelta(days=1)
    assert daily.available is False


def test_sell_averages_keep_their_value_too(mods, env):
    cost, coords = _restarted(mods, env)
    sensor = _sell(mods, cost, coords, "monthly", _state("0.9", {
        "Value from": TODAY_STAMP, "Energy sold": 4.0, "Total revenue": 3.6}))
    assert sensor.native_value == 0.9
    assert sensor.extra_state_attributes["Energy sold"] == 4.0


def test_a_computed_value_of_zero_billed_energy_never_makes_up_a_number(mods, env):
    cost, coords = _restarted(mods, env)
    cost.data["monthly"].update({"total_cost": 0.0, "fae_usage": 100.0, "fae_billed": 0})
    sensor = _period_sensor(mods, cost, coords, "monthly")
    assert sensor.native_value is None


# ------------------------------------------------- the total averages

def _history(billed=True):
    entry = {"sell_revenue": 0.0, "energy_sold": 0.0, "buy_cost": 40.0, "energy_bought": 100.0}
    if billed:
        entry.update({"energy_bought_billed": 80.0, "energy_sold_billed": 0.0})
    return {"years": {"2025": dict(entry), "2026": dict(entry)}, "fetched_at": "2026-10-02T14:50:00+02:00"}


def _total_state(value="0.5", stamp="30.09.2026 10:00:00", **attrs):
    attributes = {"Period": "total", "Buy cost": 80.0, "Energy bought": 160.0, "2025": 0.5, "2026": 0.5,
                  "Value from": stamp, "Last updated": "x", "unit_of_measurement": "PLN/kWh",
                  "friendly_name": "x", **attrs}
    return _state(value, attributes)


def test_the_total_average_keeps_its_value_when_the_history_is_old(mods, env):
    cost, _ = _restarted(mods, env)
    cost.data["history"] = _history(billed=False)
    sensor = _total(mods, cost, _total_state())
    assert sensor.native_value == 0.5
    assert sensor.available is True
    attrs = sensor.extra_state_attributes
    assert attrs["Value from"] == "30.09.2026 10:00:00"
    assert attrs["Buy cost"] == 80.0 and attrs["Energy bought"] == 160.0
    assert attrs["2025"] == 0.5 and attrs["Period"] == "total"
    # Home Assistant's own attributes are not copied back
    assert "unit_of_measurement" not in attrs and "friendly_name" not in attrs


def test_the_total_average_has_no_period_end(mods, env):
    cost, _ = _restarted(mods, env)
    cost.data["history"] = _history(billed=False)
    sensor = _total(mods, cost, _total_state(stamp="01.01.2025 00:00:00"))
    assert sensor.native_value == 0.5


def test_a_new_total_replaces_the_kept_one(mods, env):
    cost, _ = _restarted(mods, env, billed=True)
    cost.data["history"] = _history(billed=True)
    sensor = _total(mods, cost, _total_state(value="9.9"))
    totals = mods.sensor._flow_totals(cost, "total", "buy", billed=True)
    assert totals is not None
    expected = mods.sensor._average_price(*totals)
    assert sensor.native_value == expected and expected != 9.9
    fetched = cost.fetched_at("history")
    stamp = sensor.extra_state_attributes["Value from"]
    assert stamp != "30.09.2026 10:00:00"
    assert fetched is None or stamp == fetched.strftime("%d.%m.%Y %H:%M:%S")
    cost.data["history"] = _history(billed=False)  # a later run without billed data
    assert sensor.native_value == expected
    assert sensor.extra_state_attributes["Value from"] == stamp


def test_the_total_average_without_any_value_is_unknown(mods, env):
    cost, _ = _restarted(mods, env)
    cost.data["history"] = _history(billed=False)
    sensor = _total(mods, cost)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_the_total_average_is_shown_while_there_is_no_cost_data(mods, env):
    cost, _ = _restarted(mods, env)
    cost.data = None
    cost.last_update_success = False
    sensor = _total(mods, cost, _total_state())
    assert sensor.native_value == 0.5 and sensor.available is True
    assert _total(mods, cost).available is False


@pytest.mark.parametrize("state", ["unknown", "unavailable", "abc"])
def test_unusable_total_states_are_not_restored(mods, env, state):
    cost, _ = _restarted(mods, env)
    cost.data["history"] = _history(billed=False)
    assert _total(mods, cost, _total_state(value=state)).native_value is None


def test_the_total_of_a_state_without_a_date_is_not_trusted(mods, env):
    cost, _ = _restarted(mods, env)
    cost.data["history"] = _history(billed=False)
    state = _total_state()
    del state.attributes["Value from"]
    assert _total(mods, cost, state).native_value is None
