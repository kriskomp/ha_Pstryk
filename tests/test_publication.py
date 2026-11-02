"""When Pstryk published the next day's prices: detection, record, sensor, event.

Reuses the stand-ins of tests/test_refresh.py (fake clock, fake HTTP session, the
real coordinators). The API answer is built here so that the day, the publication
and the clock-change days can be chosen: before publication Pstryk sends the next
day with price null.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

import test_refresh as tr
from test_refresh import START, TZ, env, mods  # noqa: F401  (pytest fixtures)


def _api(today, published):
    """The answer for today and tomorrow, both published or only today."""
    midnight = datetime(today.year, today.month, today.day, tzinfo=TZ).astimezone(timezone.utc)
    end = datetime(today.year, today.month, today.day, tzinfo=TZ) + timedelta(days=2)
    hours = int((end.astimezone(timezone.utc) - midnight).total_seconds() // 3600)
    next_midnight = datetime(today.year, today.month, today.day, tzinfo=TZ) + timedelta(days=1)
    today_hours = int((next_midnight.astimezone(timezone.utc) - midnight).total_seconds() // 3600)
    frames = []
    for i in range(hours):
        start = midnight + timedelta(hours=i)
        out = i >= today_hours and not published
        price = None if out else 1.0 + i
        frames.append({
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": (start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "price_gross": price,
            "price_prosumer_gross": 0.0 if out else price,
            "metrics": {"pricing": {"price_gross": price, "price_prosumer_gross": 0.0 if out else price,
                                    "tge_price": None if out else 0.5, "is_cheap": False, "is_expensive": False}},
        })
    return {"frames": frames}


async def _settle():
    for _ in range(3):
        await asyncio.sleep(0)


class _Rig:
    """One start of the integration: coordinators, tracker, event entity."""

    def __init__(self, mods, env):
        self.mods, self.env = mods, env

    async def start(self, restore=True):
        self.env.hass.data["pstryk"].clear()
        self.client, self.coords = await self.env.build()
        self.tracker = self.mods.publication.PublicationTracker(self.env.hass, "e")
        await self.tracker.async_load()
        self.coords["buy"].publication = self.tracker
        self.event = self.mods.event.PstrykNextDayPricesEvent(self.tracker)
        await self.event.async_added_to_hass()
        if restore:  # a cache start-up sends no request
            await self.coords["buy"].async_load_startup_cache()
            await self.tracker.async_observe(self.coords["buy"].data)
        await _settle()
        return self

    async def fetch(self, pricing):
        self.env.hass.session.pricing = pricing
        await self.coords["buy"].async_request_refresh()
        await _settle()


def _rig(mods, env):
    return _Rig(mods, env)


def _at(*args):
    tr._set_clock(*args)


def test_published_at_the_check_that_finds_it(mods, env):
    async def scenario():
        _at(2026, 11, 3, 11, 0)
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(date(2026, 11, 3), published=False))
        before = (rig.tracker.prices_for, list(rig.event.fired))
        _at(2026, 11, 3, 12, 25)
        await rig.fetch(_api(date(2026, 11, 3), published=True))
        return before, rig

    before, rig = tr._run(scenario())
    assert before == (date(2026, 11, 3), [])  # start-up record: silent
    assert rig.tracker.prices_for == date(2026, 11, 4)
    assert rig.tracker.published_at == datetime(2026, 11, 3, 12, 25, tzinfo=TZ)
    assert rig.tracker.late is False
    assert rig.event.fired == [("published", {
        "prices_for": "2026-11-04", "prices_for_display": "04.11.2026",
        "published_at": "2026-11-03T12:25:00+01:00", "late": False})]


def test_later_fetches_do_not_move_the_first_detection(mods, env):
    async def scenario():
        _at(2026, 11, 3, 11, 0)
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(date(2026, 11, 3), published=False))
        _at(2026, 11, 3, 12, 25)
        await rig.fetch(_api(date(2026, 11, 3), published=True))
        _at(2026, 11, 3, 15, 5)
        await rig.fetch(_api(date(2026, 11, 3), published=True))
        _at(2026, 11, 4, 0, 5)
        await rig.fetch(_api(date(2026, 11, 4), published=False))
        return rig

    rig = tr._run(scenario())
    assert rig.tracker.published_at == datetime(2026, 11, 3, 12, 25, tzinfo=TZ)
    assert rig.tracker.prices_for == date(2026, 11, 4)  # the state holds after midnight
    assert len(rig.event.fired) == 1


def test_restart_and_reload_keep_the_record_and_announce_nothing_again(mods, env):
    async def scenario():
        _at(2026, 11, 3, 11, 0)
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(date(2026, 11, 3), published=False))
        _at(2026, 11, 3, 12, 25)
        await rig.fetch(_api(date(2026, 11, 3), published=True))
        record = (rig.tracker.prices_for, rig.tracker.published_at)
        _at(2026, 11, 3, 16, 0)
        again = await _rig(mods, env).start()  # restart: price cache, store, no request
        return record, again

    record, again = tr._run(scenario())
    assert (again.tracker.prices_for, again.tracker.published_at) == record
    assert again.event.fired == []
    assert len(env.hass.session.sent) == 2  # 11:00 and 12:25; the restart sent nothing


def test_a_publication_found_while_home_assistant_starts_is_announced_after_the_start(mods, env):
    async def scenario():
        _at(2026, 11, 3, 11, 0)
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(date(2026, 11, 3), published=False))
        START.update(running=False, waiting=[])
        _at(2026, 11, 3, 14, 0)
        down = await _rig(mods, env).start(restore=False)  # HA is starting; the fetch finds the prices
        await down.fetch(_api(date(2026, 11, 3), published=True))
        waiting = (list(down.event.fired), len(START["waiting"]))
        START["running"] = True
        for callback in START["waiting"]:
            await callback(env.hass)
        after = list(down.event.fired)
        for callback in START["waiting"]:  # started twice: still once
            await callback(env.hass)
        return waiting, after, down

    waiting, after, down = tr._run(scenario())
    assert waiting[0] == [] and waiting[1] >= 1
    assert len(after) == 1 and after[0][1]["prices_for"] == "2026-11-04"
    assert len(down.event.fired) == 1
    assert down.tracker.published_at == datetime(2026, 11, 3, 14, 0, tzinfo=TZ)


def test_prices_published_after_midnight_count_for_their_day_and_are_late(mods, env):
    async def scenario():
        _at(2026, 11, 3, 11, 0)
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(date(2026, 11, 3), published=False))
        _at(2026, 11, 3, 23, 45)
        await rig.fetch(_api(date(2026, 11, 3), published=False))
        _at(2026, 11, 4, 0, 5)
        await rig.fetch(_api(date(2026, 11, 4), published=False))  # day 4 itself: published
        return rig

    rig = tr._run(scenario())
    # Nov 4's prices are in the answer of Nov 3 only as null rows; on Nov 4 they are today's.
    assert rig.tracker.prices_for == date(2026, 11, 4)
    assert rig.tracker.published_at == datetime(2026, 11, 4, 0, 5, tzinfo=TZ)
    assert rig.tracker.late is True
    assert len(rig.event.fired) == 1 and rig.event.fired[0][1]["late"] is True


def test_the_first_record_is_silent_and_has_no_lateness(mods, env):
    async def scenario():
        _at(2026, 11, 3, 15, 0)  # installed (or updated) after publication
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(date(2026, 11, 3), published=True))
        return rig

    rig = tr._run(scenario())
    assert rig.tracker.prices_for == date(2026, 11, 4)
    assert rig.tracker.late is None and rig.event.fired == []


def test_an_incomplete_or_unpublished_day_is_not_a_publication(mods, env):
    api = _api(date(2026, 11, 3), published=True)
    full = mods.publication.complete_days
    rows = lambda pricing: [  # noqa: E731
        {"start": __import__("datetime").datetime.fromisoformat(f["start"].replace("Z", "+00:00"))
         .astimezone(TZ).isoformat(), "price": f["price_gross"], "tge_price": f["metrics"]["pricing"]["tge_price"]}
        for f in pricing["frames"]]
    all_rows = rows(api)
    tr._set_clock(2026, 11, 3, 13, 0)
    assert full(all_rows) == [date(2026, 11, 3), date(2026, 11, 4)]
    assert full(all_rows[:-1]) == [date(2026, 11, 3)]  # 23 of 24 hours
    nulls = [dict(r, price=None) if i == 30 else r for i, r in enumerate(all_rows)]
    assert full(nulls) == [date(2026, 11, 3)]
    no_tge = [dict(r, tge_price=None) if i == 30 else r for i, r in enumerate(all_rows)]
    assert full(no_tge) == [date(2026, 11, 3)]
    old = [{k: v for k, v in r.items() if k != "tge_price"} for r in all_rows]  # cache of an older version
    assert full(old) == [date(2026, 11, 3), date(2026, 11, 4)]


@pytest.mark.parametrize("today, tomorrow_hours", [
    (date(2026, 10, 24), 25),  # clocks go back on the 25th
    (date(2027, 3, 27), 23),   # and forward on the 28th
])
def test_a_clock_change_day_is_complete_with_its_own_number_of_hours(mods, env, today, tomorrow_hours):
    async def scenario():
        tr._set_clock(today.year, today.month, today.day, 11, 0)
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(today, published=False))
        tr._set_clock(today.year, today.month, today.day, 12, 25)
        await rig.fetch(_api(today, published=True))
        return rig

    rig = tr._run(scenario())
    assert rig.tracker.prices_for == today + timedelta(days=1)
    assert mods.publication.day_length_hours(today + timedelta(days=1)) == tomorrow_hours


def test_a_missing_hour_on_a_25_hour_day_is_not_complete(mods, env):
    async def scenario():
        tr._set_clock(2026, 10, 24, 11, 0)
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(date(2026, 10, 24), published=False))
        api = _api(date(2026, 10, 24), published=True)
        del api["frames"][-1]  # 24 of 25 hours
        tr._set_clock(2026, 10, 24, 12, 25)
        await rig.fetch(api)
        return rig

    rig = tr._run(scenario())
    assert rig.tracker.prices_for == date(2026, 10, 24)  # still the start-up day


def test_an_old_pending_day_is_not_announced(mods, env):
    async def scenario():
        _at(2026, 11, 3, 11, 0)
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(date(2026, 11, 3), published=False))
        START.update(running=False, waiting=[])
        _at(2026, 11, 3, 12, 25)
        down = await _rig(mods, env).start(restore=False)
        await down.fetch(_api(date(2026, 11, 3), published=True))  # found, HA still starting
        _at(2026, 11, 5, 9, 0)  # started two days later
        START["running"] = True
        for callback in START["waiting"]:
            await callback(env.hass)
        return down

    down = tr._run(scenario())
    assert down.event.fired == []


def test_a_record_of_another_entry_is_not_used(mods, env):
    async def scenario():
        _at(2026, 11, 3, 11, 0)
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(date(2026, 11, 3), published=False))
        _at(2026, 11, 3, 12, 25)
        await rig.fetch(_api(date(2026, 11, 3), published=True))
        other = mods.publication.PublicationTracker(env.hass, "another-entry")
        await other.async_load()
        return other

    other = tr._run(scenario())
    assert other.prices_for is None and other.published_at is None


def test_the_sensor_shows_the_record_and_stays_available(mods, env):
    async def scenario():
        _at(2026, 11, 3, 11, 0)
        rig = await _rig(mods, env).start()
        sensor = mods.sensor.PstrykNextDayPublishedSensor(rig.coords["buy"], rig.tracker, "e")
        empty = (sensor.native_value, sensor.extra_state_attributes)
        await rig.fetch(_api(date(2026, 11, 3), published=False))
        _at(2026, 11, 3, 12, 25)
        await rig.fetch(_api(date(2026, 11, 3), published=True))
        rig.coords["buy"].last_update_success = False  # an API outage does not hide the record
        noon = (sensor.native_value, sensor.extra_state_attributes, sensor.available)
        _at(2026, 11, 4, 0, 5)
        midnight = sensor.extra_state_attributes
        return sensor, empty, noon, midnight

    sensor, empty, noon, midnight = tr._run(scenario())
    assert empty[0] is None and empty[1]["next_day_available"] is False
    assert noon[0] == datetime(2026, 11, 3, 12, 25, tzinfo=TZ)
    assert noon[1] == {"prices_for": "2026-11-04", "prices_for_display": "04.11.2026",
                       "late": False, "next_day_available": True}
    assert noon[2] is True
    assert midnight["next_day_available"] is False and midnight["prices_for"] == "2026-11-04"
    assert (sensor.entity_id, sensor.unique_id) == (
        "sensor.pstryk_next_day_prices_published", "pstryk_next_day_prices_published")
    assert sensor._attr_device_class == "timestamp"


def test_the_event_entity_ids(mods, env):
    event = mods.event.PstrykNextDayPricesEvent(mods.publication.PublicationTracker(env.hass, "e"))
    assert (event.entity_id, event.unique_id, event.name) == (
        "event.pstryk_next_day_prices", "pstryk_next_day_prices", "Pstryk Next Day Prices")
    assert event._attr_event_types == ["published"]


def test_garbage_data_never_breaks_a_fetch(mods, env):
    async def scenario():
        _at(2026, 11, 3, 11, 0)
        rig = await _rig(mods, env).start()
        for bad in (None, {}, {"prices": None}, {"prices": [{"start": "x"}, {"price": 1}, 5]},
                    {"prices": [{"start": "2026-11-03T10:00:00+01:00", "price": "a"}]}):
            await rig.tracker.async_observe(bad)
        return rig

    assert tr._run(scenario()).tracker.prices_for is None


def test_setup_looks_at_the_start_up_data_and_hands_the_tracker_to_buy(mods, env):
    """sensor.async_setup_entry cannot run here; pin the lines that wire the tracker."""
    import inspect
    src = inspect.getsource(mods.sensor.async_setup_entry)
    assert 'coordinator.publication = hass.data[DOMAIN].get(f"{entry.entry_id}_publication")' in src
    assert "await tracker.async_observe(" in src
    assert "PstrykNextDayPublishedSensor(coordinator, tracker, entry.entry_id)" in src


def test_diagnostics_describe_the_record(mods, env):
    async def scenario():
        _at(2026, 11, 3, 11, 0)
        rig = await _rig(mods, env).start()
        await rig.fetch(_api(date(2026, 11, 3), published=False))
        _at(2026, 11, 3, 12, 25)
        await rig.fetch(_api(date(2026, 11, 3), published=True))
        return rig.tracker.describe()

    assert tr._run(scenario()) == {
        "prices_for": "2026-11-04", "found_at": "2026-11-03 12:25:00", "late": False,
        "announced": "2026-11-04", "event_entity_listening": True}
