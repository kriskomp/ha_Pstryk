"""Bring the entity_ids (and names) of taken-over Pstryk AiO entities in line
with this integration's own.

The take-over keeps AiO's entity_id and label on purpose, so nothing breaks at
once (e.g. ``sensor.pstryk_obecna_cena_zakupu_pradu``). This module is the
optional, later step: rename them to the ids this integration gives the same
sensors (``sensor.pstryk_current_buy_price``). Home Assistant moves long-term
statistics with the entity_id, but it does not rewrite automations, scripts,
scenes, dashboards or Energy preferences, so the preview counts references
and the user decides.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .migrate import AIO_TO_FORK

_LOGGER = logging.getLogger(__name__)

# Unique_ids that can have come from AiO; their standard entity_id is derived.
UNIFY_UNIQUE_IDS = tuple(AIO_TO_FORK.values())

STATUS_OK = "ok"              # already the standard id
STATUS_FREE = "free"          # target id is free
STATUS_COLLISION = "collision"  # only leftover data (statistics) uses the target id
STATUS_BLOCKED = "blocked"    # another entity holds the target id

MODE_KEEP = "keep"
MODE_CHANGE = "change"
MODE_CHANGE_ALL = "change_all"


def standard_entity_id(unique_id: str) -> str | None:
    """The entity_id this integration gives the sensor with ``unique_id``."""
    if unique_id not in UNIFY_UNIQUE_IDS:
        return None
    key = unique_id[len(DOMAIN) + 1:]  # e.g. "energy_bought_daily", "buy_price"
    if key in ("buy_price", "sell_price"):
        return f"sensor.{DOMAIN}_current_{key}"
    metric, _, period = key.rpartition("_")
    return f"sensor.{DOMAIN}_{period}_{metric}"


@dataclass
class Item:
    unique_id: str
    entity_id: str
    target: str
    status: str
    references: int
    name_set: bool
    disabled: bool


def _references(hass: HomeAssistant, entity_id: str) -> int:
    """Automations, scripts and scenes that mention the entity (best effort:
    template references are not found)."""
    total = 0
    for module, func in (("automation", "automations_with_entity"),
                         ("script", "scripts_with_entity"),
                         ("scene", "scenes_with_entity")):
        try:
            mod = __import__(f"homeassistant.components.{module}", fromlist=[func])
            total += len(getattr(mod, func)(hass, entity_id))
        except Exception:  # helper missing or failing: count what we can
            continue
    return total


async def _statistic_ids(hass: HomeAssistant, ids: list[str]) -> set[str]:
    """Which of ``ids`` have long-term statistics (leftovers of an old sensor)."""
    if not ids:
        return set()
    try:
        from homeassistant.components.recorder.statistics import async_list_statistic_ids

        found = await async_list_statistic_ids(hass, statistic_ids=set(ids))
        return {row["statistic_id"] for row in found}
    except Exception as err:
        _LOGGER.debug("Could not look for statistics of %s: %s", ids, err)
        return set()


async def async_items(hass: HomeAssistant, entry: ConfigEntry) -> list[Item]:
    """This entry's entities that have a standard id, with the state of the move."""
    registry = er.async_get(hass)
    mine = [e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if e.unique_id in UNIFY_UNIQUE_IDS]
    targets = [standard_entity_id(e.unique_id) for e in mine if standard_entity_id(e.unique_id) != e.entity_id]
    with_statistics = await _statistic_ids(hass, targets)
    items = []
    for e in sorted(mine, key=lambda x: x.entity_id):
        target = standard_entity_id(e.unique_id)
        if target == e.entity_id:
            status = STATUS_OK
        elif registry.async_get(target) is not None:
            status = STATUS_BLOCKED
        elif target in with_statistics or hass.states.get(target) is not None:
            status = STATUS_COLLISION
        else:
            status = STATUS_FREE
        items.append(Item(
            e.unique_id, e.entity_id, target, status,
            _references(hass, e.entity_id) if status != STATUS_OK else 0,
            e.name is not None, e.disabled_by is not None,
        ))
    return items


def has_work(items: list[Item]) -> bool:
    """Something to offer: an id to change or a registry name to drop."""
    return any(i.status != STATUS_OK or i.name_set for i in items)


async def _clear_leftovers(hass: HomeAssistant, entity_id: str) -> None:
    """Delete states and statistics of an entity_id that no entity uses."""
    try:
        await hass.services.async_call(
            "recorder", "purge_entities", {"entity_id": [entity_id]}, blocking=True)
    except Exception as err:
        _LOGGER.warning("Could not purge old states of %s: %s", entity_id, err)
    try:
        from homeassistant.components.recorder import get_instance

        get_instance(hass).async_clear_statistics([entity_id])
    except Exception as err:
        _LOGGER.warning("Could not clear old statistics of %s: %s", entity_id, err)


async def async_apply(hass: HomeAssistant, entry: ConfigEntry, mode: str,
                      english_names: bool) -> dict[str, list[str]]:
    """Do what the user chose; returns what was changed, for the log.

    ``mode`` keep: ids stay. change: only ids whose target is free.
    change_all: also ids whose target has leftover data (only that data is
    deleted). A target held by another entity is never touched.
    """
    registry = er.async_get(hass)
    done: dict[str, list[str]] = {"renamed": [], "skipped": [], "cleared": [], "names": []}
    for item in await async_items(hass, entry):
        current = item.entity_id
        if mode != MODE_KEEP and item.status != STATUS_OK:
            if item.status == STATUS_BLOCKED or (
                    item.status == STATUS_COLLISION and mode != MODE_CHANGE_ALL):
                done["skipped"].append(current)
            else:
                if item.status == STATUS_COLLISION:
                    await _clear_leftovers(hass, item.target)
                    done["cleared"].append(item.target)
                try:
                    registry.async_update_entity(current, new_entity_id=item.target)
                    done["renamed"].append(f"{current} -> {item.target}")
                    current = item.target
                except ValueError as err:
                    _LOGGER.warning("Could not rename %s: %s", current, err)
                    done["skipped"].append(current)
        if english_names and item.name_set:
            registry.async_update_entity(current, name=None)
            done["names"].append(current)
    _LOGGER.info("Unified entity ids: %s", done)
    return done
