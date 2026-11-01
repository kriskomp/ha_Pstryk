"""Take over the entities of Pstryk AiO (szkocot/Pstryk-all-in-one).

AiO and this integration read the same Pstryk API (and share its 3 requests
per hour), so one of them has to go. This module moves AiO's registry entries
to this integration: entity_id, name (label), area, history and statistics stay
as they were (Home Assistant keys them on entity_id), so dashboards,
automations and the Energy dashboard carry on without a gap.

Every AiO entity is either taken over or, when it has no sensible counterpart
here, removed; nothing is left half-done. Unknown AiO entities are never
touched by the take-over itself.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir

from .const import (
    SELL_UNIQUE_IDS,
    AIO_ACTION_DISABLE,
    AIO_ACTION_REMOVE,
    AIO_DOMAIN,
    CONF_AIO_ACTION,
    CONF_MIGRATE_FROM,
    DOMAIN,
    ISSUE_MIGRATED,
)

_LOGGER = logging.getLogger(__name__)

# AiO unique_id (its sensor key) -> unique_id of the same quantity here.
AIO_TO_FORK = {
    "today_purchase_price": f"{DOMAIN}_buy_price",
    "today_sale_price": f"{DOMAIN}_sell_price",
    "consumption_daily_kwh": f"{DOMAIN}_energy_bought_daily",
    "production_daily_kwh": f"{DOMAIN}_energy_sold_daily",
    "daily_consumption_cost": f"{DOMAIN}_buy_cost_daily",
    "daily_production_yield": f"{DOMAIN}_sell_revenue_daily",
    "billing_balance_daily_pln": f"{DOMAIN}_financial_balance_daily",
    "energy_balance_daily_kwh": f"{DOMAIN}_energy_balance_daily",
    "consumption_monthly_kwh": f"{DOMAIN}_energy_bought_monthly",
    "production_monthly_kwh": f"{DOMAIN}_energy_sold_monthly",
    "consumption_monthly_cost_pln": f"{DOMAIN}_buy_cost_monthly",
    "production_monthly_yield_pln": f"{DOMAIN}_sell_revenue_monthly",
    "billing_balance_monthly_pln": f"{DOMAIN}_financial_balance_monthly",
    "energy_balance_monthly_kwh": f"{DOMAIN}_energy_balance_monthly",
}

# AiO entities with no use here: the price of the first hour of tomorrow only.
# This integration has every hour of tomorrow in the attributes of the price
# sensors and in the JSON sensors.
AIO_OBSOLETE = ("tomorrow_purchase_price", "tomorrow_sale_price")

DEVICE_IDENTIFIER = (DOMAIN, "pstryk_energy")

# Repair notice (translation key) by what happened to the AiO entry.
ISSUE_MIGRATED_KEY = {
    AIO_ACTION_DISABLE: ISSUE_MIGRATED + "_disabled",
    AIO_ACTION_REMOVE: ISSUE_MIGRATED + "_removed",
}


def aio_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Every Pstryk AiO entry, loaded or not."""
    return hass.config_entries.async_entries(AIO_DOMAIN)


def aio_candidates(hass: HomeAssistant) -> list[ConfigEntry]:
    """AiO entries that still have entities to take over (an entry emptied by an
    earlier take-over, left disabled, is not offered again)."""
    return [e for e in aio_entries(hass) if plan(hass, e)["take"]]


def aio_api_key(aio_entry: ConfigEntry) -> str | None:
    return aio_entry.data.get("api_key")


def plan(hass: HomeAssistant, aio_entry: ConfigEntry) -> dict[str, list[str]]:
    """What the take-over will do, as entity_ids, for the preview.

    take: moved here (kept id, name and history); remove: no use here;
    other: AiO entities this integration does not know (left alone; they go
    only if the whole AiO entry is removed).
    """
    registry = er.async_get(hass)
    result: dict[str, list[str]] = {"take": [], "remove": [], "other": []}
    for entity in er.async_entries_for_config_entry(registry, aio_entry.entry_id):
        if entity.unique_id in AIO_TO_FORK:
            result["take"].append(entity.entity_id)
        elif entity.unique_id in AIO_OBSOLETE:
            result["remove"].append(entity.entity_id)
        else:
            result["other"].append(entity.entity_id)
    return result


def _device_id(hass: HomeAssistant, entry: ConfigEntry) -> str:
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={DEVICE_IDENTIFIER},
        name="Pstryk Energy",
        manufacturer="Pstryk",
        model="Energy Price Monitor",
    )
    return device.id


async def async_migrate_from_aio(
    hass: HomeAssistant, entry: ConfigEntry, aio_entry: ConfigEntry, action: str
) -> list[str]:
    """Move AiO's entities to ``entry``; returns the taken-over entity_ids.

    Safe to repeat: an entity already moved is skipped. ``action`` is what
    happens to the (then emptied) AiO entry: disable it or remove it.
    """
    # AiO first, so it stops polling the shared API and its entities are not
    # live while the registry changes under them.
    if aio_entry.disabled_by is None:
        await hass.config_entries.async_set_disabled_by(aio_entry.entry_id, ConfigEntryDisabler.USER)

    registry = er.async_get(hass)
    device_id = _device_id(hass, entry)
    moved: list[str] = []
    replaced: list[str] = []

    for old in list(er.async_entries_for_config_entry(registry, aio_entry.entry_id)):
        target = AIO_TO_FORK.get(old.unique_id)
        if target is None:
            continue
        # A sensor of this integration for the same quantity (it was added next
        # to AiO earlier) is younger than AiO's: the old one, with its longer
        # history, takes its place.
        twin = registry.async_get_entity_id("sensor", DOMAIN, target)
        if twin is not None:
            registry.async_remove(twin)
            replaced.append(twin)
        try:
            registry.async_update_entity_platform(
                old.entity_id,
                DOMAIN,
                new_config_entry_id=entry.entry_id,
                new_unique_id=target,
                new_device_id=device_id,
            )
        except ValueError as err:
            _LOGGER.warning("Could not take over %s: %s", old.entity_id, err)
            continue
        # Keep the label AiO showed: the registry name overrides the name this
        # integration gives the sensor. A name the user set is kept as it is.
        updates: dict = {}
        if old.name is None and old.original_name:
            updates["name"] = old.original_name
        if old.disabled_by is er.RegistryEntryDisabler.CONFIG_ENTRY:
            # Disabled only because AiO was disabled just now: switch it back on.
            updates["disabled_by"] = None
        if updates:
            registry.async_update_entity(old.entity_id, **updates)
        moved.append(old.entity_id)

    removed = []
    for old in list(er.async_entries_for_config_entry(registry, aio_entry.entry_id)):
        if old.unique_id in AIO_OBSOLETE:
            registry.async_remove(old.entity_id)
            removed.append(old.entity_id)

    if action == AIO_ACTION_REMOVE:
        await hass.config_entries.async_remove(aio_entry.entry_id)

    hass.config_entries.async_update_entry(
        entry,
        data={k: v for k, v in entry.data.items() if k not in (CONF_MIGRATE_FROM, CONF_AIO_ACTION)},
    )
    _LOGGER.info(
        "Took over %d entities from Pstryk AiO (%s replaced, %s removed, AiO %s)",
        len(moved), replaced or "none", removed or "none",
        "removed" if action == AIO_ACTION_REMOVE else "disabled",
    )
    if moved or removed or replaced:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_MIGRATED}_{entry.entry_id}",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_MIGRATED_KEY[action],
            translation_placeholders={
                "taken": ", ".join(moved) or "-",
                "removed": ", ".join(removed + replaced) or "-",
            },
        )
    return moved



async def async_enable_integration_disabled(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Switch on entities that 2.2.x disabled by default (four average prices).

    Only those disabled by the integration itself; an entity the user disabled
    is left as the user wanted. Runs before the sensors are added. The sell-side
    entities are left alone: whether they are on is decided by prosumer.py.
    """
    registry = er.async_get(hass)
    enabled = []
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (entity.platform == DOMAIN and entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
                and entity.unique_id not in SELL_UNIQUE_IDS):
            registry.async_update_entity(entity.entity_id, disabled_by=None)
            enabled.append(entity.entity_id)
    return enabled
