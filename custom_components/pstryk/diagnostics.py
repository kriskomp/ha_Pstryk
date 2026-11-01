"""Diagnostics download (Settings > Devices & services > Pstryk Energy > Download diagnostics).

Answers the questions that come up when sensors stay empty: what the API budget
looks like (3 requests an hour), which data each cost period holds and when it
was fetched, what the last cost run did, whether a catch-up is booked, and which
of this integration's entities have no value. The API key is never included.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .api_client import REQUEST_LOG_KEY
from .const import (
    DOMAIN,
    CONF_MQTT_ENABLED,
    CONF_MQTT_48H_MODE,
    CONF_MQTT_TOPIC_BUY,
    CONF_MQTT_TOPIC_SELL,
    CONF_RETRY_ATTEMPTS,
    CONF_RETRY_DELAY,
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_RETRY_DELAY,
    retry_attempts_setting,
)
from .price_policy import next_cost_run, next_tomorrow_check, tomorrow_fetch_due

_LOGGER = logging.getLogger(__name__)

# What a cost period holds (see energy_cost_coordinator.py). Shown as None when a
# field is missing, which is how data saved by an older version looks.
PERIOD_FIELDS = (
    "total_cost", "total_sold", "total_balance", "fae_usage", "rae_usage",
    "energy_balance", "fae_billed", "rae_billed",
)
COST_PERIODS = ("daily", "monthly", "yearly")
# Entity states that mean "no value".
NO_VALUE = ("unknown", "unavailable")


def _local(value) -> str | None:
    """A datetime or ISO string as local "YYYY-MM-DD HH:MM:SS"; None if there is none."""
    if isinstance(value, str):
        value = dt_util.parse_datetime(value)
    if not isinstance(value, datetime):
        return None
    return dt_util.as_local(value).strftime("%Y-%m-%d %H:%M:%S")


def _enum(value):
    return getattr(value, "value", value)


def _api_budget(hass: HomeAssistant) -> dict[str, Any]:
    """The shared hourly request budget: prices and costs spend the same 3 requests."""
    request_log = hass.data.get(DOMAIN, {}).get(REQUEST_LOG_KEY)
    if request_log is None:
        return {"known": False}
    result: dict[str, Any] = {"known": True}
    for endpoint, info in request_log.describe().items():
        result[endpoint] = {
            "limit_per_hour": info["limit"],
            "used_in_last_hour": info["used"],
            "room_for_one_more_now": info["room_now"],
            "next_slot_free_at": _local(info["free_at"]),
            "blocked_by_429_until": _local(info["blocked_until"]),
            "requests_sent_at": [_local(t) for t in info["sent"]],
        }
    return result


def _prices(hass: HomeAssistant, entry: ConfigEntry, now: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {}
    store = hass.data.get(DOMAIN, {})
    for price_type in ("buy", "sell"):
        coordinator = store.get(f"{entry.entry_id}_{price_type}")
        if coordinator is None:
            continue
        data = coordinator.data or {}
        retry_at = coordinator._budget_retry_at if coordinator._unsub_budget_retry else None
        result[price_type] = {
            "last_update_success": coordinator.last_update_success,
            "has_data": coordinator.data is not None,
            "prices_fetched_at": _local(data.get("last_updated")),
            "from_cache": data.get("is_cached", False),
            "prices_today": len(data.get("prices_today", [])),
            "prices_total": len(data.get("prices", [])),
            "has_tomorrow": coordinator._has_tomorrow,
            "fetch_waiting_for_api_slot_until": _local(retry_at),
            "mqtt_48h_mode": getattr(coordinator, "mqtt_48h_mode", False),
        }
    has_tomorrow = bool(result) and all(info["has_tomorrow"] for info in result.values())
    result["tomorrow_check"] = {
        "prices_missing": tomorrow_fetch_due(has_tomorrow, now),
        "next_check_at": _local(next_tomorrow_check(now)),
    }
    return result


def _cost(hass: HomeAssistant, entry: ConfigEntry, now: datetime) -> dict[str, Any]:
    coordinator = hass.data.get(DOMAIN, {}).get(f"{entry.entry_id}_cost")
    if coordinator is None:
        return {"present": False}
    data = coordinator.data or {}
    saved = coordinator._saved or {}

    def fetched(period):
        return _local((saved.get(period) or {}).get("fetched"))

    periods = {}
    for period in COST_PERIODS:
        values = data.get(period)
        periods[period] = {
            "has_data": bool(values),
            "fetched_at": fetched(period),
            "current": coordinator._period_current(period, now),
            "values": {field: (values or {}).get(field) for field in PERIOD_FIELDS},
        }
    history = data.get("history") or {}
    last_run = coordinator.last_run
    return {
        "present": True,
        "last_update_success": coordinator.last_update_success,
        "periods": periods,
        "history": {
            "has_data": bool(history),
            "fetched_at": fetched("history"),
            "current": coordinator._period_current("history", now),
            "years": history.get("years", {}),
        },
        # Parts (day, month) whose periods have no data fetched today/this month/year.
        "missing_parts": coordinator.missing_parts(now),
        "last_run": None if last_run is None else {
            "at": _local(last_run["at"]),
            "reason": last_run["reason"],
            "outcome": last_run["outcome"],
            "parts": last_run["parts"],
            "waiting_for_api_slot_until": {
                part: _local(free_at) for part, free_at in last_run["waiting"].items()
            },
        },
        "catch_up_booked_for": _local(coordinator.catch_up_time()),
        "next_regular_run": _local(next_cost_run(now)),
    }


def _entities(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """This integration's entities and which of them have no value."""
    registry = er.async_get(hass)
    states: dict[str, str] = {}
    no_value: dict[str, str] = {}
    disabled: dict[str, Any] = {}
    hidden: dict[str, Any] = {}
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.disabled_by:
            disabled[entity.entity_id] = _enum(entity.disabled_by)
            continue
        state = hass.states.get(entity.entity_id)
        value = state.state if state is not None else "not_created"
        states[entity.entity_id] = value
        if value in NO_VALUE or value == "not_created":
            no_value[entity.entity_id] = value
        if entity.hidden_by:
            hidden[entity.entity_id] = _enum(entity.hidden_by)
    return {
        "enabled": len(states),
        "without_value": no_value,
        "disabled": disabled,
        "hidden": hidden,
        "states": states,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    now = dt_util.now()
    stored_attempts = entry.options.get(CONF_RETRY_ATTEMPTS, DEFAULT_RETRY_ATTEMPTS)
    diagnostics_data: dict[str, Any] = {
        "generated_at": _local(now),
        "entry": {
            "title": entry.title,
            "entry_id": entry.entry_id,
            "version": entry.version,
            "options": {
                "buy_top": entry.options.get("buy_top", entry.data.get("buy_top", 5)),
                "sell_top": entry.options.get("sell_top", entry.data.get("sell_top", 5)),
                "buy_worst": entry.options.get("buy_worst", entry.data.get("buy_worst", 5)),
                "sell_worst": entry.options.get("sell_worst", entry.data.get("sell_worst", 5)),
                "mqtt_enabled": entry.options.get(CONF_MQTT_ENABLED, False),
                "mqtt_48h_mode": entry.options.get(CONF_MQTT_48H_MODE, False),
                "mqtt_topic_buy": entry.options.get(CONF_MQTT_TOPIC_BUY, "Not set"),
                "mqtt_topic_sell": entry.options.get(CONF_MQTT_TOPIC_SELL, "Not set"),
                "retry_attempts_stored": stored_attempts,
                "retry_attempts_used": retry_attempts_setting(stored_attempts),
                "retry_delay": entry.options.get(CONF_RETRY_DELAY, DEFAULT_RETRY_DELAY),
            },
        },
        "api_budget": _api_budget(hass),
        "prices": _prices(hass, entry, now),
        "cost": _cost(hass, entry, now),
        "entities": _entities(hass, entry),
        "mqtt": {"integration_available": hass.services.has_service("mqtt", "publish")},
    }

    mqtt_publisher = hass.data.get(DOMAIN, {}).get(f"{entry.entry_id}_mqtt")
    if mqtt_publisher:
        diagnostics_data["mqtt"].update({
            "publisher_initialized": mqtt_publisher._initialized,
            "last_published": _local(mqtt_publisher.last_published),
            "topic_buy": mqtt_publisher.mqtt_topic_buy,
            "topic_sell": mqtt_publisher.mqtt_topic_sell,
        })
    else:
        diagnostics_data["mqtt"]["enabled"] = False

    prosumer = hass.data.get(DOMAIN, {}).get(f"{entry.entry_id}_prosumer")
    if prosumer is not None:
        diagnostics_data["prosumer_entities"] = prosumer.describe()

    return diagnostics_data
