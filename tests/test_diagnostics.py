"""The diagnostics download, run against the real coordinators and API client.

It reuses the stand-ins of tests/test_refresh.py (fake clock, fake HTTP session,
fixtures `mods` and `env`), so every number below comes from a real run of the
integration's own code.
"""
import json
import types
from datetime import datetime, timedelta, timezone

import pytest

import test_refresh as tr
from test_refresh import env, mods  # noqa: F401  (pytest fixtures)

SECRET = "SECRET-API-KEY-0123456789"


class _States:
    def __init__(self, states):
        self.states = states

    def get(self, entity_id):
        value = self.states.get(entity_id)
        return None if value is None else types.SimpleNamespace(state=value)


def _entity(entity_id, entry_id="e", disabled_by=None, hidden_by=None):
    return types.SimpleNamespace(entity_id=entity_id, config_entry_id=entry_id,
                                 disabled_by=disabled_by, hidden_by=hidden_by)


def _entry(options=None):
    return types.SimpleNamespace(title="Pstryk Energy", entry_id="e", version=3,
                                 options=dict(options or {}), data={"api_key": SECRET})


def _prepare(env, entities=(), states=None, mqtt=False):
    hass = env.hass
    hass.registry = types.SimpleNamespace(entities=list(entities))
    hass.states = _States(states or {})
    hass.services = types.SimpleNamespace(has_service=lambda domain, service: mqtt)
    return hass


async def _installed(mods, env, day=2, hour=16, minute=11):
    """A first install as in the Oct 2 tests; the cost coordinator is registered like sensor.py does."""
    client, coords, cost, result, sent = await tr._first_start(mods, env, day, hour, minute)
    env.hass.data["pstryk"]["e_cost"] = cost
    return client, coords, cost


def _diagnostics(mods, env, options=None):
    return tr._run(mods.diagnostics.async_get_config_entry_diagnostics(env.hass, _entry(options)))


def _local(moment):
    return moment.astimezone(tr.TZ).strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------- budget

def test_api_budget_names_the_requests_and_when_a_slot_frees(mods, env):
    tr._run(_installed(mods, env))
    _prepare(env)
    result = _diagnostics(mods, env)
    sent = env.hass.session.sent
    budget = result["api_budget"]["unified-metrics"]
    assert len(sent) == 3  # prices, day, month
    assert budget["limit_per_hour"] == 3 and budget["used_in_last_hour"] == 3
    assert budget["room_for_one_more_now"] is False
    assert budget["requests_sent_at"] == [_local(t) for t in sent]
    # A slot frees an hour (plus the 2 s margin) after the oldest request was sent.
    assert budget["next_slot_free_at"] == _local(sent[0] + timedelta(hours=1, seconds=2))
    assert budget["blocked_by_429_until"] is None


def test_budget_unknown_before_the_first_client_exists(mods, env):
    _prepare(env)
    result = _diagnostics(mods, env)
    assert result["api_budget"] == {"known": False}
    assert result["cost"] == {"present": False}
    assert result["prices"]["tomorrow_check"]["next_check_at"]


def test_diagnostics_do_not_spend_or_claim_anything(mods, env):
    tr._run(_installed(mods, env))
    _prepare(env)
    before = list(env.hass.session.sent)
    first = _diagnostics(mods, env)
    second = _diagnostics(mods, env)
    assert first == second
    assert env.hass.session.sent == before
    log = env.hass.data["pstryk"]["request_log"]
    assert log.describe()["unified-metrics"]["used"] == 3


def test_a_429_block_is_shown(mods, env):
    async def scenario():
        client, coords, cost = await _installed(mods, env)
        until = tr.CLOCK[0].astimezone(timezone.utc) + timedelta(minutes=40)
        client._budget("unified-metrics").block_until(until)
        return until

    until = tr._run(scenario())
    _prepare(env)
    budget = _diagnostics(mods, env)["api_budget"]["unified-metrics"]
    assert budget["blocked_by_429_until"] == _local(until)


# ------------------------------------------------------------------- cost

def test_cost_periods_show_their_values_and_fetch_times(mods, env):
    tr._run(_installed(mods, env))
    _prepare(env)
    cost = _diagnostics(mods, env)["cost"]
    assert cost["present"] and cost["last_update_success"] is True
    assert cost["missing_parts"] == []
    daily, monthly, yearly = (cost["periods"][p] for p in ("daily", "monthly", "yearly"))
    # The fake API numbers each response by request: day is the 2nd, month the 3rd.
    assert daily["has_data"] and daily["current"] and daily["fetched_at"] == "2026-10-02 16:11:00"
    assert daily["values"]["total_cost"] == 4 and daily["values"]["fae_usage"] == 2
    assert monthly["values"]["total_cost"] == 6 and monthly["values"]["fae_usage"] == 3
    assert yearly["has_data"] and yearly["values"]["fae_usage"] == 3 and yearly["values"]["energy_balance"] == 0
    assert set(daily["values"]) == set(mods.diagnostics.PERIOD_FIELDS)
    assert cost["history"]["has_data"] and cost["history"]["current"]
    assert "2026" in cost["history"]["years"]


def test_cost_run_outcome_and_the_next_regular_run(mods, env):
    tr._run(_installed(mods, env))
    _prepare(env)
    cost = _diagnostics(mods, env)["cost"]
    assert cost["last_run"]["reason"] == "start-up" and cost["last_run"]["outcome"] == "fetched"
    assert cost["last_run"]["parts"] == ["day", "month"]
    assert cost["last_run"]["waiting_for_api_slot_until"] == {}
    assert cost["last_run"]["at"] == "2026-10-02 16:11:00"
    assert cost["catch_up_booked_for"] is None
    assert cost["next_regular_run"] == "2026-10-02 17:05:30"


def test_a_part_the_limit_refused_is_shown_with_its_catch_up(mods, env):
    """The Warsaw case: price fetch, another call and a restart leave one slot."""
    env.hass.session.cost_frames = True

    async def scenario():
        tr._at(2, 16, 9, 38)
        client, coords = await env.build()
        await tr.asyncio.gather(*(c.async_request_refresh() for c in coords.values()))
        tr._at(2, 16, 20)
        await client.fetch(
            "https://api.pstryk.pl/integrations/meter-data/unified-metrics/?metrics=cost", max_retries=1)
        tr._at(2, 16, 38)
        cost = tr._new_cost(mods, env, client, coords)
        await cost.async_restore()
        await cost.async_startup_refresh()
        env.hass.data["pstryk"]["e_cost"] = cost

    tr._run(scenario())
    _prepare(env)
    cost = _diagnostics(mods, env)["cost"]
    assert cost["last_run"]["outcome"] == "partial"
    # The day request went first and got the slot; the month waits for 16:09:38 + 1 h + 2 s.
    assert cost["periods"]["daily"]["has_data"] is True
    assert cost["periods"]["monthly"]["has_data"] is False
    assert cost["periods"]["monthly"]["values"]["total_cost"] is None
    assert cost["missing_parts"] == ["month"]
    assert cost["last_run"]["waiting_for_api_slot_until"] == {"month": "2026-10-02 17:09:40"}
    assert cost["catch_up_booked_for"] == "2026-10-02 17:09:50"


def test_a_catch_up_that_has_run_is_no_longer_shown_as_booked(mods, env):
    env.hass.session.cost_frames = True

    async def scenario():
        tr._at(2, 16, 9, 38)
        client, coords = await env.build()
        await tr.asyncio.gather(*(c.async_request_refresh() for c in coords.values()))
        tr._at(2, 16, 20)
        await client.fetch(
            "https://api.pstryk.pl/integrations/meter-data/unified-metrics/?metrics=cost", max_retries=1)
        tr._at(2, 16, 38)
        cost = tr._new_cost(mods, env, client, coords)
        await cost.async_restore()
        await cost.async_startup_refresh()
        env.hass.data["pstryk"]["e_cost"] = cost
        assert cost.catch_up_time() is not None
        tr._at(2, 17, 9, 50)
        await cost._handle_catch_up(None)

    tr._run(scenario())
    _prepare(env)
    cost = _diagnostics(mods, env)["cost"]
    assert cost["catch_up_booked_for"] is None and cost["missing_parts"] == []
    assert cost["last_run"]["reason"] == "catch-up" and cost["last_run"]["outcome"] == "fetched"
    assert cost["periods"]["monthly"]["has_data"] is True


def test_start_up_that_finds_no_room_is_recorded(mods, env):
    async def scenario():
        client, coords = await env.build()
        await tr.asyncio.gather(*(c.async_request_refresh() for c in coords.values()))  # 12:05, 1 request
        await tr._two_more_calls(client)  # the budget is full
        cost = tr._new_cost(mods, env, client, coords)
        await cost.async_restore()
        tr._set_clock(2026, 10, 2, 12, 20)
        outcome = await cost.async_startup_refresh()
        env.hass.data["pstryk"]["e_cost"] = cost
        return outcome

    assert tr._run(scenario()) == "budget"
    _prepare(env)
    cost = _diagnostics(mods, env)["cost"]
    assert cost["last_run"]["reason"] == "start-up" and cost["last_run"]["outcome"] == "budget"
    assert set(cost["last_run"]["waiting_for_api_slot_until"]) == {"day", "month"}
    assert cost["missing_parts"] == ["day", "month"]
    assert cost["catch_up_booked_for"]


def test_data_saved_by_an_older_version_shows_missing_fields_as_null(mods, env):
    tr._run(_installed(mods, env))
    cost = env.hass.data["pstryk"]["e_cost"]
    cost.data["daily"] = {"total_cost": 1.5, "fae_usage": 2.0}  # 2.2.x had no billed/balance fields
    _prepare(env)
    values = _diagnostics(mods, env)["cost"]["periods"]["daily"]["values"]
    assert values["total_cost"] == 1.5 and values["fae_usage"] == 2.0
    assert values["fae_billed"] is None and values["energy_balance"] is None and values["rae_billed"] is None


def test_an_hourly_run_that_waits_for_the_limit_is_recorded(mods, env):
    async def scenario():
        client, coords, cost = await _installed(mods, env)
        tr._set_clock(2026, 10, 2, 17, 5, 30)
        await cost._handle_hourly_update(None)  # budget: the 16:11 requests are still counted

    tr._run(scenario())
    _prepare(env)
    last = _diagnostics(mods, env)["cost"]["last_run"]
    # The three requests of 16:11 are counted until 17:11:02: cost waits, nothing is sent.
    assert last["reason"] == "hourly" and last["outcome"] == "waits"
    assert last["at"] == "2026-10-02 17:05:30"
    assert last["parts"] == ["day", "month"]
    assert set(last["waiting_for_api_slot_until"]) == {"day", "month"}
    assert len(env.hass.session.sent) == 3


def test_a_restart_with_current_data_is_recorded_as_restored(mods, env):
    _, _, restarted, coords = tr._run(tr._cost_runs_then_restart(mods, env, (2026, 10, 2, 15, 0)))
    env.hass.data["pstryk"]["e_cost"] = restarted
    assert tr._run(restarted.async_startup_refresh()) == "restored"
    _prepare(env)
    last = _diagnostics(mods, env)["cost"]["last_run"]
    assert (last["reason"], last["outcome"], last["parts"]) == ("start-up", "restored", [])
    assert last["at"] == "2026-10-02 15:00:00"


def test_a_start_just_before_the_regular_run_is_recorded(mods, env):
    async def scenario():
        tr._set_clock(2026, 10, 2, 16, 58)
        client, coords = await env.build()
        cost = tr._new_cost(mods, env, client, coords)
        await cost.async_restore()
        env.hass.data["pstryk"]["e_cost"] = cost
        return await cost.async_startup_refresh()

    assert tr._run(scenario()) == "next_run_soon"  # 17:05:30 is closer than 10 minutes
    _prepare(env)
    cost = _diagnostics(mods, env)["cost"]
    assert (cost["last_run"]["outcome"], cost["last_run"]["parts"]) == ("next_run_soon", ["day", "month"])
    assert cost["missing_parts"] == ["day", "month"] and cost["next_regular_run"] == "2026-10-02 17:05:30"


def test_a_run_skipped_for_the_prices_is_recorded(mods, env):
    async def scenario():
        client, coords, cost = await _installed(mods, env, hour=11, minute=0)
        for coord in coords.values():
            coord._has_tomorrow = False  # after 12:00 cost waits for tomorrow's prices
        tr._set_clock(2026, 10, 2, 13, 5, 30)
        await cost._handle_hourly_update(None)

    tr._run(scenario())
    _prepare(env)
    last = _diagnostics(mods, env)["cost"]["last_run"]
    assert (last["reason"], last["outcome"]) == ("hourly", "skipped") and last["at"] == "2026-10-02 13:05:30"


def test_a_failed_cost_run_is_recorded(mods, env):
    async def scenario():
        client, coords, cost = await _installed(mods, env)
        tr._set_clock(2026, 10, 2, 18, 5, 30)
        env.hass.session.statuses = [404, 404]  # not retried: the part fails
        await cost._handle_hourly_update(None)

    tr._run(scenario())
    _prepare(env)
    last = _diagnostics(mods, env)["cost"]["last_run"]
    assert last["reason"] == "hourly" and last["outcome"] == "failed"


# ----------------------------------------------------------------- prices

def test_prices_show_when_they_were_fetched_and_whether_tomorrow_is_in(mods, env):
    tr._run(_installed(mods, env))
    _prepare(env)
    prices = _diagnostics(mods, env)["prices"]
    assert prices["buy"]["has_data"] and prices["buy"]["has_tomorrow"] is True
    assert prices["buy"]["prices_today"] == 24 and prices["buy"]["prices_total"] == 48
    assert prices["buy"]["prices_fetched_at"] == "2026-10-02 16:11:00"
    assert prices["buy"]["fetch_waiting_for_api_slot_until"] is None
    assert prices["tomorrow_check"]["prices_missing"] is False
    assert prices["tomorrow_check"]["next_check_at"] == "2026-10-02 16:25:00"


def test_a_price_fetch_waiting_for_a_slot_is_shown(mods, env):
    async def scenario():
        client, coords = await env.build()
        free_at = tr.CLOCK[0].astimezone(timezone.utc) + timedelta(minutes=25)
        coords["buy"]._arm_budget_retry(free_at)
        return free_at

    free_at = tr._run(scenario())
    _prepare(env)
    prices = _diagnostics(mods, env)["prices"]
    assert prices["buy"]["fetch_waiting_for_api_slot_until"] == _local(free_at + timedelta(seconds=5))
    assert prices["sell"]["fetch_waiting_for_api_slot_until"] is None


def test_a_price_retry_that_already_ran_is_no_longer_shown(mods, env):
    async def scenario():
        client, coords = await env.build()
        coords["buy"]._arm_budget_retry(tr.CLOCK[0].astimezone(timezone.utc) + timedelta(minutes=25))
        coords["buy"]._unsub_budget_retry = None  # what the retry callback does when it runs

    tr._run(scenario())
    _prepare(env)
    assert _diagnostics(mods, env)["prices"]["buy"]["fetch_waiting_for_api_slot_until"] is None


@pytest.mark.parametrize("hour, minute, has_tomorrow, missing", [
    (14, 0, False, True),    # published from about 12:05, still not in
    (14, 0, True, False),
    (11, 30, False, False),  # not expected yet
    (12, 4, False, False),
    (12, 5, False, True),
])
def test_tomorrows_prices_count_as_missing_only_after_they_are_expected(mods, env, hour, minute, has_tomorrow, missing):
    async def scenario():
        client, coords = await env.build()
        for coord in coords.values():
            coord._has_tomorrow = has_tomorrow
        tr._set_clock(2026, 10, 2, hour, minute)

    tr._run(scenario())
    _prepare(env)
    assert _diagnostics(mods, env)["prices"]["tomorrow_check"]["prices_missing"] is missing


def test_a_period_fetched_on_an_earlier_day_is_not_current(mods, env):
    tr._run(_installed(mods, env))
    tr._set_clock(2026, 10, 3, 0, 20)  # the day changed; nothing was fetched yet
    _prepare(env)
    cost = _diagnostics(mods, env)["cost"]
    assert cost["periods"]["daily"]["current"] is False and cost["periods"]["daily"]["fetched_at"]
    assert cost["periods"]["monthly"]["current"] is True and cost["history"]["current"] is True
    assert cost["missing_parts"] == ["day"]


# --------------------------------------------------------------- entities

def test_entities_without_a_value_are_listed_with_their_reason(mods, env):
    tr._run(_installed(mods, env))
    _prepare(env, entities=[
        _entity("sensor.pstryk_daily_buy_cost"),
        _entity("sensor.pstryk_sell_total_average"),
        _entity("sensor.pstryk_daily_sell_revenue", hidden_by="integration"),
        _entity("sensor.pstryk_buy_daily_average", disabled_by="user"),
        _entity("sensor.pstryk_not_yet_created"),
        _entity("sensor.other_integration", entry_id="other"),
    ], states={
        "sensor.pstryk_daily_buy_cost": "21.45",
        "sensor.pstryk_sell_total_average": "unknown",
        "sensor.pstryk_daily_sell_revenue": "unavailable",
        "sensor.pstryk_buy_daily_average": "0.7",
        "sensor.other_integration": "1",
    })
    entities = _diagnostics(mods, env)["entities"]
    assert entities["enabled"] == 4  # the disabled one is not counted
    assert entities["without_value"] == {
        "sensor.pstryk_sell_total_average": "unknown",
        "sensor.pstryk_daily_sell_revenue": "unavailable",
        "sensor.pstryk_not_yet_created": "not_created",
    }
    assert entities["disabled"] == {"sensor.pstryk_buy_daily_average": "user"}
    assert entities["hidden"] == {"sensor.pstryk_daily_sell_revenue": "integration"}
    assert entities["states"]["sensor.pstryk_daily_buy_cost"] == "21.45"
    assert "sensor.other_integration" not in entities["states"]
    assert "sensor.pstryk_buy_daily_average" not in entities["states"]  # disabled: no state to show


def test_enum_values_of_the_registry_are_shown_as_text(mods, env):
    class By:  # like RegistryEntryDisabler / RegistryEntryHider members
        value = "integration"

    tr._run(_installed(mods, env))
    _prepare(env, entities=[_entity("sensor.a", disabled_by=By()), _entity("sensor.b", hidden_by=By())],
             states={"sensor.b": "1"})
    entities = _diagnostics(mods, env)["entities"]
    assert entities["disabled"] == {"sensor.a": "integration"}
    assert entities["hidden"] == {"sensor.b": "integration"}
    json.dumps(entities)


# ---------------------------------------------------------- options, secrets

@pytest.mark.parametrize("options, stored, used", [
    ({}, 2, 2),
    ({"retry_attempts": 5}, 5, 3),
    ({"retry_attempts": 1}, 1, 1),
])
def test_retry_settings_show_stored_and_used_values(mods, env, options, stored, used):
    _prepare(env)
    shown = _diagnostics(mods, env, options)["entry"]["options"]
    assert (shown["retry_attempts_stored"], shown["retry_attempts_used"]) == (stored, used)
    assert shown["retry_delay"] == 30


def test_the_api_key_never_appears_and_everything_is_json(mods, env):
    tr._run(_installed(mods, env))
    env.hass.data["pstryk"]["e"] = {"api_key": SECRET}
    _prepare(env, mqtt=True, entities=[_entity("sensor.pstryk_daily_buy_cost")],
             states={"sensor.pstryk_daily_buy_cost": "1"})
    result = _diagnostics(mods, env, {"mqtt_enabled": True})
    dumped = json.dumps(result)  # HA serialises the dictionary; datetimes would fail here
    assert SECRET not in dumped and "api_key" not in dumped
    assert result["entry"]["entry_id"] == "e" and result["mqtt"]["integration_available"] is True


def test_mqtt_publisher_state_is_shown_when_it_runs(mods, env):
    tr._run(_installed(mods, env))
    env.hass.data["pstryk"]["e_mqtt"] = types.SimpleNamespace(
        _initialized=True, last_published=datetime(2026, 10, 2, 16, 0, tzinfo=tr.TZ),
        mqtt_topic_buy="energy/forecast/buy", mqtt_topic_sell="energy/forecast/sell")
    _prepare(env, mqtt=True)
    mqtt = _diagnostics(mods, env)["mqtt"]
    assert mqtt["publisher_initialized"] is True and mqtt["last_published"] == "2026-10-02 16:00:00"
    assert mqtt["topic_buy"] == "energy/forecast/buy"
    assert "enabled" not in mqtt


def test_without_a_publisher_mqtt_is_reported_off(mods, env):
    _prepare(env)
    assert _diagnostics(mods, env)["mqtt"] == {"integration_available": False, "enabled": False}
