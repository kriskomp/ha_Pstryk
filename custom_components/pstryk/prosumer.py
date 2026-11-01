"""Switch off the sell-side entities of a customer who does not sell energy.

Twelve entities only describe selling: revenue, energy sold and the average sell
price for the day, month, year and all time. Without a solar installation they
stay at 0 or unknown for good, so they are disabled. (Hiding is not enough: Home
Assistant still lists a hidden entity on the device page.) Nothing is lost: their
values come from the API's own totals, so once enabled they are right from the
first fetch. Home Assistant reloads the integration by itself after an entity is
enabled, which adds them.

Setting "prosumer_entities":
  auto     disable while no sale has been seen anywhere in the data, enable on
           the first sale and tell the user once (default)
  show     never disable
  disable  always disable

A sale is seen when the history from October 2024 (every year, the current month
included) or the day, month or year in progress holds any energy sold or revenue.
Meter readings from before the contract count too. Until the history has been
fetched nothing is decided and nothing is disabled.

The user stays in charge: only entities disabled by this integration are ever
enabled again, an entity the user disabled or enabled by hand is not touched a
second time, and nothing is disabled twice. What was done is kept in .storage so a restart
does not repeat it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN, PROSUMER_AUTO, PROSUMER_DISABLE, PROSUMER_SHOW, prosumer_setting

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
NOTIFICATION_ID = f"{DOMAIN}_sale_detected"
# Period data that already shows a sale (the history decides "no sale").
PERIODS = ("daily", "monthly", "yearly")

DISABLED = "disabled"
SHOWN = "shown"

def sale_seen(data: dict | None) -> bool | None:
    """True if the cost data shows any sale, False if it shows none, None if it cannot tell yet.

    "None" while the history of years is missing or empty: an empty answer of
    the API must not make someone who sells look like someone who does not.
    """
    if not data:
        return None
    years = (data.get("history") or {}).get("years") or {}
    for year in years.values():
        if (year.get("energy_sold") or 0) > 0 or (year.get("sell_revenue") or 0) > 0:
            return True
    for period in PERIODS:
        values = data.get(period) or {}
        if (values.get("rae_usage") or 0) > 0 or (values.get("total_sold") or 0) > 0:
            return True
    return False if years else None


class ProsumerVisibility:

    def __init__(self, hass: HomeAssistant, entry_id: str, mode: str, unique_ids, coordinator):
        self.hass = hass
        self.entry_id = entry_id
        self.mode = prosumer_setting(mode)
        self.unique_ids = tuple(unique_ids)
        self.coordinator = coordinator
        self.sale = None
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}_prosumer")
        self._saved: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        try:
            saved = await self._store.async_load() or {}
        except Exception as err:
            _LOGGER.warning("Failed to load the prosumer visibility state: %s", err)
            saved = {}
        # Like the other stores: it outlives its entry, and a later entry may be another account.
        # A state of an earlier test version ("hidden") is not valid any more: decide afresh.
        if (saved.get("owner") == self.entry_id and saved.get("mode") == self.mode
                and saved.get("state") in (None, DISABLED, SHOWN)):
            self._saved = {"state": saved.get("state"), "handled": list(saved.get("handled", []))}
        else:
            self._saved = {"state": None, "handled": []}

    def describe(self) -> dict[str, Any]:
        """For the diagnostics download."""
        registry = er.async_get(self.hass)
        disabled = {}
        for unique_id in self.unique_ids:
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
            entry = registry.async_get(entity_id) if entity_id else None
            if entry is not None and entry.disabled_by:
                disabled[entity_id] = getattr(entry.disabled_by, "value", entry.disabled_by)
        return {
            "setting": self.mode,
            "sale_seen": self.sale,
            "decision": self._saved.get("state"),
            "entities": len(self.unique_ids),
            "disabled": disabled,
        }

    async def async_evaluate(self) -> None:
        """Decide from the current data and apply it. Safe to call as often as wanted."""
        async with self._lock:
            self.sale = sale_seen(self.coordinator.data)
            state = self._saved.get("state")
            handled = self._saved["handled"]
            before = (state, tuple(handled))

            if self.mode == PROSUMER_SHOW:
                if state != SHOWN:
                    self._reveal()
                    state = SHOWN
            elif self.mode == PROSUMER_DISABLE:
                state = DISABLED
            elif state is None and self.sale is not None:
                state = SHOWN if self.sale else DISABLED
                if state == SHOWN:
                    self._reveal()  # left disabled by this integration under another setting

            notify = False
            if state == DISABLED and self.mode == PROSUMER_AUTO and self.sale:
                self._reveal()
                state, handled, notify = SHOWN, [], True
            elif state == DISABLED:
                self._disable_new(handled)

            self._saved = {"state": state, "handled": handled}
            if (state, tuple(handled)) != before:
                await self._async_save()
            if notify:
                await self._async_notify()

    def _entries(self):
        registry = er.async_get(self.hass)
        for unique_id in self.unique_ids:
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
            entry = registry.async_get(entity_id) if entity_id else None
            if entry is not None:
                yield registry, unique_id, entry

    def _disable_new(self, handled: list[str]) -> None:
        """Disable each entity once. One the user already disabled, hid or enabled is only marked as handled.

        An entity this integration hid in an earlier test version is disabled
        instead and no longer hidden.
        """
        for registry, unique_id, entry in self._entries():
            if unique_id in handled:
                continue
            ours = er.RegistryEntryHider.INTEGRATION
            if entry.disabled_by is None and entry.hidden_by in (None, ours):
                registry.async_update_entity(
                    entry.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION, hidden_by=None)
            handled.append(unique_id)

    def _reveal(self) -> None:
        """Enable again what this integration disabled (and unhide what it hid); the user's own choices stay."""
        for registry, _unique_id, entry in self._entries():
            changes = {}
            if entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                changes["disabled_by"] = None
            if entry.hidden_by == er.RegistryEntryHider.INTEGRATION:
                changes["hidden_by"] = None
            if changes:
                registry.async_update_entity(entry.entity_id, **changes)

    async def _async_save(self) -> None:
        try:
            await self._store.async_save({"owner": self.entry_id, "mode": self.mode, **self._saved})
        except Exception as err:
            _LOGGER.warning("Failed to save the prosumer visibility state: %s", err)

    async def _async_notify(self) -> None:
        _LOGGER.info("Energy sold was seen for the first time: the sell entities are enabled")
        try:
            texts = await async_get_translations(self.hass, self.hass.config.language, "issues", [DOMAIN])
        except Exception as err:
            _LOGGER.warning("Failed to load translations for the sale notification: %s", err)
            texts = {}
        key = f"component.{DOMAIN}.issues.sale_detected"
        persistent_notification.async_create(
            self.hass,
            texts.get(f"{key}.description",
                      "Energy sold to the grid was seen for the first time, so the sell entities "
                      "(revenue, energy sold, average sell price) are enabled again. Home Assistant "
                      "adds them in about 30 seconds."),
            title=texts.get(f"{key}.title", "Pstryk Energy: sale detected"),
            notification_id=NOTIFICATION_ID,
        )
