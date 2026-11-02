from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode
from .const import (
    DOMAIN,
    AIO_ACTION_DISABLE,
    AIO_ACTION_REMOVE,
    CONF_AIO_ACTION,
    CONF_MIGRATE_FROM,
    DEFAULT_MQTT_TOPIC_BUY,
    DEFAULT_MQTT_TOPIC_SELL,
    CONF_MQTT_ENABLED,
    CONF_MQTT_TOPIC_BUY,
    CONF_MQTT_TOPIC_SELL,
    CONF_MQTT_48H_MODE,
    CONF_JSON_SENSOR,
    CONF_RETRY_ATTEMPTS,
    CONF_RETRY_DELAY,
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_RETRY_DELAY,
    MIN_RETRY_ATTEMPTS,
    MAX_RETRY_ATTEMPTS,
    MIN_RETRY_DELAY,
    MAX_RETRY_DELAY,
    retry_attempts_setting,
    prosumer_setting,
    CONF_PROSUMER_ENTITIES,
    PROSUMER_AUTO,
    PROSUMER_SHOW,
    PROSUMER_DISABLE,
)

from .api_client import async_validate_api_key
from .migrate import aio_api_key, aio_candidates, async_migrate_from_aio, plan
from .unify_ids import (
    MODE_CHANGE,
    MODE_CHANGE_ALL,
    MODE_KEEP,
    STATUS_OK,
    async_apply,
    async_items,
    has_work,
)

CONF_AIO_MODE = "mode"
CONF_AIO_ENTRY = "aio_entry"
CONF_TAKE_OVER_AIO = "take_over_aio"
CONF_UNIFY_IDS = "unify_entity_ids"
CONF_UNIFY_MODE = "unify_mode"
CONF_ENGLISH_NAMES = "english_names"
# What the user chose for Pstryk AiO: take over its entities and then disable
# or remove it, or set this integration up on its own. No default is preset.
MODE_FRESH = "fresh"
MODE_DISABLE = AIO_ACTION_DISABLE
MODE_REMOVE = AIO_ACTION_REMOVE


def _aio_schema(entries, with_fresh):
    """The choice form: which AiO entry (only when there are several) and what to do."""
    modes = [MODE_DISABLE, MODE_REMOVE] + ([MODE_FRESH] if with_fresh else [])
    schema = {}
    if len(entries) > 1:
        schema[vol.Required(CONF_AIO_ENTRY)] = SelectSelector(SelectSelectorConfig(
            options=[{"value": e.entry_id, "label": e.title} for e in entries],
            mode=SelectSelectorMode.DROPDOWN,
        ))
    schema[vol.Required(CONF_AIO_MODE)] = SelectSelector(SelectSelectorConfig(
        options=modes, mode=SelectSelectorMode.LIST, translation_key="aio_mode",
    ))
    return vol.Schema(schema)


def _aio_placeholders(hass, entries):
    """Preview for the form: what is taken over, removed and left alone."""
    taken, removed, other = [], [], []
    for entry in entries:
        found = plan(hass, entry)
        taken += found["take"]
        removed += found["remove"]
        other += found["other"]
    return {
        "taken_count": str(len(taken)),
        "taken": ", ".join(taken) or "-",
        "removed": ", ".join(removed) or "-",
        "other": ", ".join(other) or "-",
    }


async def _aio_key_usable(hass, aio, key):
    """Whether AiO's API key can be taken over: True, False, or None (no API slot).

    A loaded AiO entry has just used this key (its set-up fails on a refused
    key), so it is taken without a request of its own: the 3 requests an hour
    are then left for prices and costs, and the first cost data comes at once
    instead of an hour later. An AiO entry that is not loaded (disabled, or
    failing to start) proves nothing, so its key is checked like a typed one.
    """
    if not key:
        return False
    if aio.state is ConfigEntryState.LOADED:
        return True
    return await async_validate_api_key(hass, key)


class MQTTNotConfiguredError(HomeAssistantError):
    pass

class PstrykConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 3

    def __init__(self):
        self._data = {}
        self._options = {}
        self._aio_offered = False

    async def async_step_user(self, user_input=None):
        errors = {}
        # Pstryk AiO is installed and this integration is not yet: offer to
        # take over its entities and API key (once, before the key is asked for).
        if (user_input is None and not self._aio_offered
                and aio_candidates(self.hass) and not self._async_current_entries()):
            self._aio_offered = True
            return await self.async_step_migrate()
        if user_input is not None:
            api_key = user_input["api_key"]
            valid = await async_validate_api_key(self.hass, api_key)

            if valid:
                self._data["api_key"] = api_key
                return await self.async_step_price_settings()
            elif valid is None:
                errors["base"] = "api_budget_full"
            else:
                errors["api_key"] = "invalid_api_key"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("api_key"): str,
            }),
            errors=errors
        )

    async def async_step_migrate(self, user_input=None):
        entries = aio_candidates(self.hass)
        errors = {}
        if user_input is not None:
            mode = user_input[CONF_AIO_MODE]
            if mode == MODE_FRESH:
                return await self.async_step_user()
            aio = next((e for e in entries if e.entry_id == user_input.get(CONF_AIO_ENTRY, entries[0].entry_id)), None)
            key = aio_api_key(aio) if aio else None
            valid = await _aio_key_usable(self.hass, aio, key)
            if valid:
                self._data.update({"api_key": key, CONF_MIGRATE_FROM: aio.entry_id, CONF_AIO_ACTION: mode})
                return await self.async_step_price_settings()
            errors["base"] = "api_budget_full" if valid is None else "aio_key_invalid"

        return self.async_show_form(
            step_id="migrate",
            data_schema=_aio_schema(entries, with_fresh=True),
            description_placeholders=_aio_placeholders(self.hass, entries),
            errors=errors,
        )

    async def async_step_price_settings(self, user_input=None):
        if user_input is not None:
            self._data.update({
                "buy_top": user_input["buy_top"],
                "sell_top": user_input["sell_top"],
                "buy_worst": user_input["buy_worst"],
                "sell_worst": user_input["sell_worst"],
            })
            self._options[CONF_JSON_SENSOR] = user_input.get(CONF_JSON_SENSOR, False)
            
            mqtt_available = await self._check_mqtt_configuration()
            if mqtt_available:
                return await self.async_step_mqtt_settings()
            else:
                return await self.async_step_api_retry()

        return self.async_show_form(
            step_id="price_settings",
            data_schema=vol.Schema({
                vol.Required("buy_top", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                vol.Required("sell_top", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                vol.Required("buy_worst", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                vol.Required("sell_worst", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                vol.Required(CONF_JSON_SENSOR, default=False): bool,
            })
        )

    async def async_step_mqtt_settings(self, user_input=None):
        errors = {}
        
        if user_input is not None:
            mqtt_enabled = user_input.get(CONF_MQTT_ENABLED, False)
            if mqtt_enabled:
                mqtt_configured = await self._check_mqtt_configuration()
                if not mqtt_configured:
                    errors["base"] = "mqtt_not_configured"
            
            if not errors:
                self._options.update({
                    CONF_MQTT_ENABLED: user_input.get(CONF_MQTT_ENABLED, False),
                    CONF_MQTT_TOPIC_BUY: user_input.get(CONF_MQTT_TOPIC_BUY, DEFAULT_MQTT_TOPIC_BUY),
                    CONF_MQTT_TOPIC_SELL: user_input.get(CONF_MQTT_TOPIC_SELL, DEFAULT_MQTT_TOPIC_SELL),
                    CONF_MQTT_48H_MODE: user_input.get(CONF_MQTT_48H_MODE, False),
                })
                return await self.async_step_api_retry()

        return self.async_show_form(
            step_id="mqtt_settings",
            data_schema=vol.Schema({
                vol.Required(CONF_MQTT_ENABLED, default=False): bool,
                vol.Optional(CONF_MQTT_TOPIC_BUY, default=DEFAULT_MQTT_TOPIC_BUY): str,
                vol.Optional(CONF_MQTT_TOPIC_SELL, default=DEFAULT_MQTT_TOPIC_SELL): str,
                vol.Optional(CONF_MQTT_48H_MODE, default=False): bool,
            }),
            errors=errors
        )

    async def async_step_api_retry(self, user_input=None):
        if user_input is not None:
            self._options.update({
                CONF_RETRY_ATTEMPTS: user_input.get(CONF_RETRY_ATTEMPTS, DEFAULT_RETRY_ATTEMPTS),
                CONF_RETRY_DELAY: user_input.get(CONF_RETRY_DELAY, DEFAULT_RETRY_DELAY),
            })
            
            return self.async_create_entry(
                title="Pstryk Energy", 
                data=self._data,
                options=self._options
            )

        return self.async_show_form(
            step_id="api_retry",
            data_schema=vol.Schema({
                vol.Optional(CONF_RETRY_ATTEMPTS, default=DEFAULT_RETRY_ATTEMPTS): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_RETRY_ATTEMPTS, max=MAX_RETRY_ATTEMPTS)
                ),
                vol.Optional(CONF_RETRY_DELAY, default=DEFAULT_RETRY_DELAY): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_RETRY_DELAY, max=MAX_RETRY_DELAY)
                ),
            })
        )
    
    async def _check_mqtt_configuration(self):
        try:
            return self.hass.services.has_service("mqtt", "publish")
        except Exception:
            return False
    
    @staticmethod
    def async_get_options_flow(config_entry):
        return PstrykOptionsFlowHandler()


class PstrykOptionsFlowHandler(config_entries.OptionsFlow):

    def __init__(self):
        self._new_options = None
        self._unify_after = False

    async def async_step_init(self, user_input=None):
        errors = {}
        
        if user_input is not None:
            user_input = dict(user_input)
            take_over = user_input.pop(CONF_TAKE_OVER_AIO, False)
            unify = user_input.pop(CONF_UNIFY_IDS, False)
            mqtt_enabled = user_input.get(CONF_MQTT_ENABLED, False)
            if mqtt_enabled:
                mqtt_configured = await self._check_mqtt_configuration()
                if not mqtt_configured:
                    errors["base"] = "mqtt_not_configured"
            
            if not errors:
                self._new_options = user_input
                self._unify_after = unify
                if take_over and aio_candidates(self.hass):
                    return await self.async_step_migrate_aio()
                if unify:
                    return await self.async_step_unify_ids()
                return self.async_create_entry(title="", data=user_input)

        mqtt_enabled = False
        try:
            mqtt_enabled = self.hass.services.has_service("mqtt", "publish")
        except Exception:
            mqtt_enabled = False
        
        schema = {
            vol.Required("buy_top", default=self.config_entry.options.get(
                "buy_top", self.config_entry.data.get("buy_top", 5))): 
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
            vol.Required("sell_top", default=self.config_entry.options.get(
                "sell_top", self.config_entry.data.get("sell_top", 5))): 
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
            vol.Required("buy_worst", default=self.config_entry.options.get(
                "buy_worst", self.config_entry.data.get("buy_worst", 5))): 
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
            vol.Required("sell_worst", default=self.config_entry.options.get(
                "sell_worst", self.config_entry.data.get("sell_worst", 5))): 
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
            vol.Required(CONF_JSON_SENSOR, default=self.config_entry.options.get(
                CONF_JSON_SENSOR, False)): bool,
            vol.Required(CONF_PROSUMER_ENTITIES, default=prosumer_setting(
                self.config_entry.options.get(CONF_PROSUMER_ENTITIES))): SelectSelector(
                SelectSelectorConfig(
                    options=[PROSUMER_AUTO, PROSUMER_SHOW, PROSUMER_DISABLE],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="prosumer_entities",
                )),
        }

        if mqtt_enabled:
            schema.update({
                vol.Required(CONF_MQTT_ENABLED, default=self.config_entry.options.get(
                    CONF_MQTT_ENABLED, False)): bool,
                vol.Optional(CONF_MQTT_TOPIC_BUY, default=self.config_entry.options.get(
                    CONF_MQTT_TOPIC_BUY, DEFAULT_MQTT_TOPIC_BUY)): str,
                vol.Optional(CONF_MQTT_TOPIC_SELL, default=self.config_entry.options.get(
                    CONF_MQTT_TOPIC_SELL, DEFAULT_MQTT_TOPIC_SELL)): str,
                vol.Optional(CONF_MQTT_48H_MODE, default=self.config_entry.options.get(
                    CONF_MQTT_48H_MODE, False)): bool,
            })
        
        schema.update({
            vol.Optional(CONF_RETRY_ATTEMPTS, default=retry_attempts_setting(self.config_entry.options.get(
                CONF_RETRY_ATTEMPTS, DEFAULT_RETRY_ATTEMPTS))): 
                    vol.All(vol.Coerce(int), vol.Range(min=MIN_RETRY_ATTEMPTS, max=MAX_RETRY_ATTEMPTS)),
            vol.Optional(CONF_RETRY_DELAY, default=self.config_entry.options.get(
                CONF_RETRY_DELAY, DEFAULT_RETRY_DELAY)): 
                    vol.All(vol.Coerce(int), vol.Range(min=MIN_RETRY_DELAY, max=MAX_RETRY_DELAY)),
        })

        if aio_candidates(self.hass):
            schema[vol.Optional(CONF_TAKE_OVER_AIO, default=False)] = bool
        if has_work(await async_items(self.hass, self.config_entry)):
            schema[vol.Optional(CONF_UNIFY_IDS, default=False)] = bool

        description_text = "Configure your energy price monitoring settings"
        if mqtt_enabled:
            description_text += "\n\n**Note:** Settings are grouped by: Price Monitoring, MQTT Bridge, and API Configuration"

        return self.async_show_form(
            step_id="init", 
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "description": description_text
            }
        )

    async def async_step_migrate_aio(self, user_input=None):
        """Take over Pstryk AiO's entities for an integration that is already set up."""
        entries = aio_candidates(self.hass)
        errors = {}
        if user_input is not None:
            aio = next((e for e in entries if e.entry_id == user_input.get(CONF_AIO_ENTRY, entries[0].entry_id)), None)
            if aio is None:
                errors["base"] = "aio_gone"
            elif aio_api_key(aio) != self.config_entry.data.get("api_key"):
                # Another Pstryk account: its entities describe another meter.
                errors["base"] = "different_api_key"
            else:
                await async_migrate_from_aio(self.hass, self.config_entry, aio, user_input[CONF_AIO_MODE])
                if self._new_options == dict(self.config_entry.options):
                    # Nothing changed, so no update listener reloads the entry:
                    # reload it for the moved entities to start.
                    self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
                if self._unify_after:
                    return await self.async_step_unify_ids()
                return self.async_create_entry(title="", data=self._new_options)

        return self.async_show_form(
            step_id="migrate_aio",
            data_schema=_aio_schema(entries, with_fresh=False),
            description_placeholders=_aio_placeholders(self.hass, entries),
            errors=errors,
        )

    async def async_step_unify_ids(self, user_input=None):
        """Optional: give taken-over entities this integration's own ids and names."""
        items = await async_items(self.hass, self.config_entry)
        if user_input is not None:
            mode = user_input[CONF_UNIFY_MODE]
            english = user_input.get(CONF_ENGLISH_NAMES, False)
            done = await async_apply(self.hass, self.config_entry, mode, english)
            if (done["renamed"] or done["names"]) and self._new_options == dict(self.config_entry.options):
                # No options change, so no update listener reloads the entry.
                self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data=self._new_options)

        lines = []
        for i in items:
            if i.status == STATUS_OK:
                continue
            mark = {"free": "✓", "collision": "⚠", "blocked": "✖"}[i.status]
            lines.append(f"{mark} {i.entity_id} → {i.target} ({i.references})")
        schema = vol.Schema({
            vol.Required(CONF_UNIFY_MODE): SelectSelector(SelectSelectorConfig(
                options=[MODE_KEEP, MODE_CHANGE, MODE_CHANGE_ALL],
                mode=SelectSelectorMode.LIST, translation_key="unify_mode",
            )),
            vol.Required(CONF_ENGLISH_NAMES, default=False): bool,
        })
        return self.async_show_form(
            step_id="unify_ids",
            data_schema=schema,
            description_placeholders={
                "preview": "\n".join(f"- {line}" for line in lines) or "-",
                "named": str(sum(1 for i in items if i.name_set)),
            },
        )

    async def _check_mqtt_configuration(self):
        try:
            mqtt_config_entry = None
            for entry in self.hass.config_entries.async_entries("mqtt"):
                if entry.state == config_entries.ConfigEntryState.LOADED:
                    mqtt_config_entry = entry
                    break
            
            if not mqtt_config_entry:
                return False
            
            return self.hass.services.has_service("mqtt", "publish")
        except Exception:
            return False
