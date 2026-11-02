"""When Pstryk published the prices for the next day, as the integration sees it.

The API gives no publication time, only hourly rows. Pstryk puts them in some
time after 12:00 (12:05, 12:20, 14:00 ...), and the integration finds them with
the checks of tomorrow_poll.py (every 20 minutes). The moment a fetch first holds
a complete day newer than the one recorded is the moment recorded here: one
record per calendar day, 365 or 366 a year, the first detection wins.

Complete means every hour of the day (23, 24 or 25 in UTC on clock-change days)
has a price, and a `tge_price` when the row carries one. Before publication Pstryk
sends rows with price null, so buy prices tell the two states apart exactly.

The record is kept in .storage with the entry that wrote it, so a restart or a
reload keeps it. The "published" event is sent once per day, and only after Home
Assistant has started: automations are not listening before that, so a
publication found while Home Assistant was down is announced after its start.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Callable

from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .update_coordinator import entry_start

_LOGGER = logging.getLogger(__name__)

PUBLICATION_STORE_VERSION = 1
EVENT_PUBLISHED = "published"


def day_length_hours(day: date) -> int:
    """Hours in the local `day`: 23, 24 or 25 (measured in UTC)."""
    seconds = (dt_util.as_utc(dt_util.start_of_local_day(day.fromordinal(day.toordinal() + 1)))
               - dt_util.as_utc(dt_util.start_of_local_day(day))).total_seconds()
    return int(seconds // 3600)


def complete_days(prices: list[dict]) -> list[date]:
    """Local dates for which every hour of the day has a published price."""
    hours: dict[date, set] = {}
    for row in prices:
        start = entry_start(row)
        if start is None or row.get("price") is None:
            continue
        if "tge_price" in row and row["tge_price"] is None:
            continue
        hours.setdefault(dt_util.as_local(start).date(), set()).add(start)
    return sorted(day for day, found in hours.items() if len(found) == day_length_hours(day))


def _day(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


class PublicationTracker:
    """Detects, stores and announces the publication of the next day's prices."""

    def __init__(self, hass, entry_id: str):
        self.hass = hass
        self.entry_id = entry_id
        self._store = Store(hass, PUBLICATION_STORE_VERSION, f"{DOMAIN}_next_day_published")
        self._rec: dict[str, Any] = {}
        self._listeners: list[Callable[[], None]] = []
        self._sink: Callable[[dict], None] | None = None

    # -- stored record ------------------------------------------------------

    async def async_load(self) -> None:
        try:
            saved = await self._store.async_load()
        except Exception as err:
            _LOGGER.warning("Failed to read the next-day publication record: %s", err)
            saved = None
        # The store outlives its entry; another entry may belong to another account.
        if saved and saved.get("owner") == self.entry_id and _day(saved.get("for")):
            self._rec = {k: saved.get(k) for k in ("for", "at", "announced", "late")}

    async def _async_save(self) -> None:
        try:
            await self._store.async_save({**self._rec, "owner": self.entry_id})
        except Exception as err:
            _LOGGER.warning("Failed to write the next-day publication record: %s", err)

    # -- what the sensor shows ---------------------------------------------

    @property
    def prices_for(self) -> date | None:
        return _day(self._rec.get("for"))

    @property
    def published_at(self) -> datetime | None:
        return dt_util.parse_datetime(self._rec["at"]) if self._rec.get("at") else None

    @property
    def late(self) -> bool | None:
        return self._rec.get("late")

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None

    def _notify(self) -> None:
        for callback in list(self._listeners):
            callback()

    def describe(self) -> dict[str, Any]:
        """For the diagnostics download."""
        at = self.published_at
        return {
            "prices_for": self._rec.get("for"),
            "found_at": dt_util.as_local(at).strftime("%Y-%m-%d %H:%M:%S") if at else None,
            "late": self.late,
            "announced": self._rec.get("announced"),
            "event_entity_listening": self._sink is not None,
        }

    # -- detection ----------------------------------------------------------

    async def async_observe(self, data: dict | None) -> None:
        """Look at buy-price data (a fetch, or the cache at start-up). Never raises."""
        try:
            await self._observe(data)
        except Exception:
            _LOGGER.exception("Checking for the next day's publication failed")

    async def _observe(self, data: dict | None) -> None:
        if not data:
            return
        today = dt_util.now().date()
        found = [day for day in complete_days(data.get("prices") or []) if day >= today]
        if not found:
            return
        newest = max(found)
        recorded = self.prices_for
        if recorded is not None and newest <= recorded:
            return  # the first detection of a day stays
        first = not self._rec
        at = dt_util.parse_datetime(data.get("last_updated") or "") or dt_util.now()
        self._rec = {
            "for": newest.isoformat(),
            "at": at.isoformat(),
            # Before the first record the real time is unknown: start-up data says
            # only when it was fetched. Nothing is announced for it.
            "announced": newest.isoformat() if first else self._rec.get("announced"),
            "late": None if first else dt_util.as_local(at).date() >= newest,
        }
        _LOGGER.info("Prices for %s are in (found at %s)", newest.isoformat(),
                     dt_util.as_local(at).strftime("%H:%M"))
        await self._async_save()
        self._notify()
        async_at_started(self.hass, self._on_started)

    # -- the event ----------------------------------------------------------

    def set_sink(self, sink: Callable[[dict], None]) -> Callable[[], None]:
        """The event entity; it is told once per day, after Home Assistant has started."""
        self._sink = sink
        async_at_started(self.hass, self._on_started)

        def _remove():
            if self._sink is sink:
                self._sink = None
        return _remove

    async def _on_started(self, _hass=None) -> None:
        sink, rec = self._sink, self._rec
        if sink is None or not rec.get("for") or rec.get("announced") == rec["for"]:
            return
        # Marked first: nothing below may announce the same day twice.
        rec["announced"] = rec["for"]
        if self.prices_for >= dt_util.now().date():  # an older day is not news
            sink({
                "prices_for": rec["for"],
                "prices_for_display": self.prices_for.strftime("%d.%m.%Y"),
                "published_at": rec["at"],
                "late": rec.get("late"),
            })
        await self._async_save()
