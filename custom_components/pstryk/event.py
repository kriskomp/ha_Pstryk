"""Event entity: the prices for the next day have been published (once per day)."""
from __future__ import annotations

from homeassistant.components.event import EventEntity

from .const import DOMAIN
from .publication import EVENT_PUBLISHED
from .sensor import _pstryk_device_info


async def async_setup_entry(hass, entry, async_add_entities):
    tracker = hass.data[DOMAIN].get(f"{entry.entry_id}_publication")
    if tracker is not None:
        async_add_entities([PstrykNextDayPricesEvent(tracker)])


class PstrykNextDayPricesEvent(EventEntity):
    """Fires `published` when the integration first finds a complete next day.

    Automations trigger on the state change of this entity. A publication found
    while Home Assistant was down is announced after its start; a restart or
    reload never repeats a day.
    """

    _attr_icon = "mdi:calendar-check"
    _attr_event_types = [EVENT_PUBLISHED]
    _attr_should_poll = False

    def __init__(self, tracker):
        self._tracker = tracker
        self.entity_id = f"event.{DOMAIN}_next_day_prices"

    @property
    def name(self) -> str:
        return "Pstryk Next Day Prices"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_next_day_prices"

    @property
    def device_info(self):
        return _pstryk_device_info(self.hass)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._tracker.set_sink(self._published))

    def _published(self, attributes: dict) -> None:
        self._trigger_event(EVENT_PUBLISHED, attributes)
        self.async_write_ha_state()
