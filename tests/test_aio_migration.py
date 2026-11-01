"""Take-over of Pstryk AiO: registry move, config flow, options flow.

Home Assistant is not installed here, so its registries, config entries and
selectors are replaced by small stand-ins that follow the behaviour the code
relies on (a clash of platform + unique_id raises ValueError, disabling a config
entry disables its entities with CONFIG_ENTRY, removing an entry removes them).
The real migrate.py, config_flow.py and the take-over in __init__.py run on them.

AiO side: unique_id = sensor key, as in szkocot/Pstryk-all-in-one 0.1.6
(const.py SENSOR_*), with the Polish names it shows.
"""
import asyncio
import enum
import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "pstryk"

sys.path.insert(0, str(Path(__file__).parent))
from test_refresh import IDS_ADDED_IN_2_3_0, RELEASED_IDS  # noqa: E402

# (unique_id, entity_id, name) of the 16 sensors AiO creates (Warsaw instance).
AIO_ENTITIES = [
    ("today_purchase_price", "sensor.pstryk_obecna_cena_zakupu_pradu", "Obecna cena zakupu prądu"),
    ("tomorrow_purchase_price", "sensor.pstryk_cena_zakupu_pradu_jutro", "Cena zakupu prądu (jutro)"),
    ("today_sale_price", "sensor.pstryk_obecna_cena_sprzedazy_pradu", "Obecna cena sprzedaży prądu"),
    ("tomorrow_sale_price", "sensor.pstryk_cena_sprzedazy_pradu_jutro", "Cena sprzedaży prądu (jutro)"),
    ("daily_consumption_cost", "sensor.pstryk_dzienne_koszty_zuzycia_energii", "Dzienne koszty zużycia energii"),
    ("daily_production_yield", "sensor.pstryk_dzienna_wartosc_produkcji_energii", "Dzienna wartość produkcji energii"),
    ("billing_balance_monthly_pln", "sensor.pstryk_saldo_rozliczeniowe_miesieczne_pln", "Saldo rozliczeniowe miesięczne (PLN)"),
    ("energy_balance_monthly_kwh", "sensor.pstryk_saldo_energetyczne_miesieczne_kwh", "Saldo energetyczne miesięczne (kWh)"),
    ("billing_balance_daily_pln", "sensor.pstryk_saldo_rozliczeniowe_dzienne_pln", "Saldo rozliczeniowe dzienne (PLN)"),
    ("energy_balance_daily_kwh", "sensor.pstryk_saldo_energetyczne_dzienne_kwh", "Saldo energetyczne dzienne (kWh)"),
    ("consumption_daily_kwh", "sensor.pstryk_dzienne_zuzycie_energii_kwh", "Dzienne zużycie energii (kWh)"),
    ("production_daily_kwh", "sensor.pstryk_dzienna_produkcja_energii_kwh", "Dzienna produkcja energii (kWh)"),
    ("consumption_monthly_kwh", "sensor.pstryk_miesieczne_zuzycie_energii_kwh", "Miesięczne zużycie energii (kWh)"),
    ("production_monthly_kwh", "sensor.pstryk_miesieczna_produkcja_energii_kwh", "Miesięczna produkcja energii (kWh)"),
    ("consumption_monthly_cost_pln", "sensor.pstryk_miesieczne_koszty_zuzycia_energii_pln", "Miesięczne koszty zużycia energii (PLN)"),
    ("production_monthly_yield_pln", "sensor.pstryk_miesieczna_wartosc_produkcji_energii_pln", "Miesięczna wartość produkcji energii (PLN)"),
]
OBSOLETE = {"tomorrow_purchase_price", "tomorrow_sale_price"}


# ---------------------------------------------------------------- stand-ins

class Disabler(enum.Enum):
    USER = "user"
    CONFIG_ENTRY = "config_entry"
    INTEGRATION = "integration"


@dataclass
class Ent:
    entity_id: str
    unique_id: str
    platform: str
    config_entry_id: str
    device_id: str | None = None
    name: str | None = None
    original_name: str | None = None
    disabled_by: Disabler | None = None


class Registry:
    def __init__(self):
        self.entities: dict[str, Ent] = {}

    def add(self, entity_id, unique_id, platform, config_entry_id, **kw):
        self.entities[entity_id] = Ent(entity_id, unique_id, platform, config_entry_id, **kw)
        return self.entities[entity_id]

    def async_get(self, entity_id):
        return self.entities.get(entity_id)

    def async_get_entity_id(self, domain, platform, unique_id):
        for e in self.entities.values():
            if e.platform == platform and e.unique_id == unique_id and e.entity_id.startswith(domain + "."):
                return e.entity_id
        return None

    def async_remove(self, entity_id):
        del self.entities[entity_id]

    def async_update_entity(self, entity_id, **kw):
        for key, value in kw.items():
            setattr(self.entities[entity_id], key, value)

    def async_update_entity_platform(self, entity_id, new_platform, *, new_config_entry_id,
                                     new_unique_id=None, new_device_id=None):
        entity = self.entities[entity_id]
        unique_id = entity.unique_id if new_unique_id is None else new_unique_id
        if self.async_get_entity_id("sensor", new_platform, unique_id) not in (None, entity_id):
            raise ValueError(f"Unique id '{unique_id}' is already in use")
        entity.platform, entity.unique_id = new_platform, unique_id
        entity.config_entry_id, entity.device_id = new_config_entry_id, new_device_id

    def for_entry(self, entry_id):
        return [e for e in self.entities.values() if e.config_entry_id == entry_id]


class Entry:
    def __init__(self, entry_id, domain, data=None, options=None, title=None):
        self.entry_id, self.domain, self.title = entry_id, domain, title or domain
        self.data, self.options = dict(data or {}), dict(options or {})
        self.disabled_by = None
        self.state = "not_loaded"
        self.update_listeners = []


class Manager:
    def __init__(self, registry):
        self.registry, self.entries, self.log = registry, {}, []

    def add(self, entry):
        self.entries[entry.entry_id] = entry
        return entry

    def async_entries(self, domain=None):
        return [e for e in self.entries.values() if domain is None or e.domain == domain]

    def async_get_entry(self, entry_id):
        return self.entries.get(entry_id)

    async def async_set_disabled_by(self, entry_id, disabler):
        self.entries[entry_id].disabled_by = disabler
        self.log.append(("disable", entry_id))
        for e in self.registry.for_entry(entry_id):
            if e.disabled_by is None:
                e.disabled_by = Disabler.CONFIG_ENTRY

    async def async_remove(self, entry_id):
        self.log.append(("remove", entry_id))
        for e in self.registry.for_entry(entry_id):
            self.registry.async_remove(e.entity_id)
        del self.entries[entry_id]

    def async_update_entry(self, entry, *, data=None, options=None):
        changed = False
        if data is not None and data != entry.data:
            entry.data, changed = dict(data), True
        if options is not None and options != entry.options:
            entry.options, changed = dict(options), True
        if changed:
            self.log.append(("update", entry.entry_id))
        return changed

    def async_schedule_reload(self, entry_id):
        self.log.append(("reload", entry_id))


class Issues:
    created = []


@dataclass
class Device:
    id: str


class Devices:
    def __init__(self):
        self.made = {}

    def async_get_or_create(self, *, config_entry_id, identifiers, **kw):
        key = frozenset(identifiers)
        self.made.setdefault(key, Device(f"device-{len(self.made) + 1}"))
        return self.made[key]


class Hass:
    def __init__(self):
        self.registry = Registry()
        self.devices = Devices()
        self.config_entries = Manager(self.registry)
        self.data = {"pstryk": {}}


def _mod(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


class _Key:
    def __init__(self, schema, default="<none>"):
        self.schema, self.default = schema, default

    def __hash__(self):
        return hash(self.schema)

    def __eq__(self, other):
        return isinstance(other, _Key) and other.schema == self.schema


class _Flow:
    """What ConfigFlow and OptionsFlow offer the code under test."""
    current_entries = []

    def async_show_form(self, **kw):
        return {"type": "form", **kw}

    def async_create_entry(self, **kw):
        return {"type": "create_entry", **kw}

    def _async_current_entries(self):
        return list(self.current_entries)


def _stubs(hass_holder):
    registry_mod = _mod(
        "homeassistant.helpers.entity_registry",
        RegistryEntryDisabler=Disabler,
        async_get=lambda hass: hass.registry,
        async_entries_for_config_entry=lambda registry, entry_id: registry.for_entry(entry_id),
    )
    device_mod = _mod("homeassistant.helpers.device_registry", async_get=lambda hass: hass.devices)
    issue_mod = _mod(
        "homeassistant.helpers.issue_registry",
        IssueSeverity=types.SimpleNamespace(WARNING="warning"),
        async_create_issue=lambda hass, domain, issue_id, **kw: Issues.created.append((domain, issue_id, kw)),
    )
    selector = _mod(
        "homeassistant.helpers.selector",
        SelectSelector=lambda config: ("select", config),
        SelectSelectorConfig=lambda **kw: kw,
        SelectSelectorMode=types.SimpleNamespace(LIST="list", DROPDOWN="dropdown"),
    )
    helpers = _mod("homeassistant.helpers", entity_registry=registry_mod, device_registry=device_mod,
                   issue_registry=issue_mod, selector=selector)

    class ConfigFlow(_Flow):
        def __init_subclass__(cls, domain=None, **kw):
            super().__init_subclass__()

    class OptionsFlow(_Flow):
        pass

    config_entries = _mod(
        "homeassistant.config_entries",
        ConfigEntry=Entry, ConfigEntryDisabler=types.SimpleNamespace(USER="user"),
        ConfigFlow=ConfigFlow, OptionsFlow=OptionsFlow,
        ConfigEntryState=types.SimpleNamespace(LOADED="loaded"),
    )
    vol = _mod(
        "voluptuous",
        Schema=lambda schema: schema,
        Required=lambda key, default="<none>": _Key(key, default),
        Optional=lambda key, default="<none>": _Key(key, default),
        All=lambda *a: a, Coerce=lambda t: t, Range=lambda **kw: kw,
    )
    notify = _mod("homeassistant.components.persistent_notification",
                  async_create=lambda *a, **k: None)
    return {
        "homeassistant": _mod("homeassistant"),
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.entity_registry": registry_mod,
        "homeassistant.helpers.device_registry": device_mod,
        "homeassistant.helpers.issue_registry": issue_mod,
        "homeassistant.helpers.selector": selector,
        "homeassistant.helpers.translation": _mod("homeassistant.helpers.translation",
                                                  async_get_translations=None),
        "homeassistant.config_entries": config_entries,
        "homeassistant.core": _mod("homeassistant.core", HomeAssistant=Hass, callback=lambda f: f),
        "homeassistant.exceptions": _mod("homeassistant.exceptions", HomeAssistantError=type("E", (Exception,), {})),
        "homeassistant.components": _mod("homeassistant.components", persistent_notification=notify),
        "homeassistant.components.persistent_notification": notify,
        "voluptuous": vol,
        "pstryk.api_client": _mod("pstryk.api_client", async_validate_api_key=None),
        "pstryk.mqtt_publisher": _mod("pstryk.mqtt_publisher", PstrykMqttPublisher=object),
        "pstryk.mqtt_common": _mod("pstryk.mqtt_common", setup_periodic_mqtt_publish=None),
    }


@pytest.fixture(scope="module")
def mods():
    stubs = _stubs(None)
    saved = {name: sys.modules.get(name) for name in stubs}
    saved_pkg = {n: m for n, m in sys.modules.items() if n == "pstryk" or n.startswith("pstryk.")}
    for name in saved_pkg:
        del sys.modules[name]
    sys.modules.update(stubs)
    spec = importlib.util.spec_from_file_location(
        "pstryk", PKG / "__init__.py", submodule_search_locations=[str(PKG)])
    package = importlib.util.module_from_spec(spec)
    sys.modules["pstryk"] = package
    spec.loader.exec_module(package)
    try:
        yield types.SimpleNamespace(
            init=package,
            migrate=importlib.import_module("pstryk.migrate"),
            flow=importlib.import_module("pstryk.config_flow"),
            const=importlib.import_module("pstryk.const"),
        )
    finally:
        for name in [n for n in sys.modules if n == "pstryk" or n.startswith("pstryk.")]:
            del sys.modules[name]
        sys.modules.update(saved_pkg)
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _run(coro):
    return asyncio.run(coro)


AIO_KEY = "aio-key-123"


def _setup(mods, *, action="disable", with_marker=True, aio_disabled=False, fork_twins=False):
    """Warsaw: AiO with its 16 sensors and a new fork entry waiting for the take-over."""
    Issues.created.clear()
    hass = Hass()
    aio = hass.config_entries.add(Entry("aio1", "pstryk_aio", {"api_key": AIO_KEY}, title="Pstryk AiO"))
    for unique_id, entity_id, name in AIO_ENTITIES:
        hass.registry.add(entity_id, unique_id, "pstryk_aio", "aio1", original_name=name, device_id="aio-dev")
    data = {"api_key": AIO_KEY}
    if with_marker:
        data.update({mods.const.CONF_MIGRATE_FROM: "aio1", mods.const.CONF_AIO_ACTION: action})
    fork = hass.config_entries.add(Entry("fork1", "pstryk", data))
    if aio_disabled:
        aio.disabled_by = "user"
        for e in hass.registry.for_entry("aio1"):
            e.disabled_by = Disabler.CONFIG_ENTRY
    if fork_twins:  # the fork was added next to AiO earlier: English sensors exist
        for aio_uid, fork_uid in mods.migrate.AIO_TO_FORK.items():
            hass.registry.add(f"sensor.{fork_uid}_english", fork_uid, "pstryk", "fork1")
    return hass, aio, fork


def _take_over(mods, hass, fork):
    _run(mods.init._async_take_over_aio(hass, fork))


# ------------------------------------------------------------------ mapping

def test_every_take_over_target_is_a_real_sensor_of_the_integration(mods):
    real = set(RELEASED_IDS.values()) | set(IDS_ADDED_IN_2_3_0.values())
    targets = set(mods.migrate.AIO_TO_FORK.values())
    assert targets <= real
    assert len(targets) == len(mods.migrate.AIO_TO_FORK) == 14  # one AiO sensor per target


def test_the_mapping_covers_all_16_aio_sensors_and_nothing_else(mods):
    aio_ids = {uid for uid, _, _ in AIO_ENTITIES}
    assert set(mods.migrate.AIO_TO_FORK) | set(mods.migrate.AIO_OBSOLETE) == aio_ids
    assert set(mods.migrate.AIO_OBSOLETE) == OBSOLETE
    assert not set(mods.migrate.AIO_TO_FORK) & set(mods.migrate.AIO_OBSOLETE)


def test_same_quantity_same_unit_pairs(mods):
    """Each AiO sensor is paired with the sensor of the same quantity and period."""
    pairs = {
        "daily_consumption_cost": "buy_cost_daily", "consumption_daily_kwh": "energy_bought_daily",
        "production_daily_kwh": "energy_sold_daily", "daily_production_yield": "sell_revenue_daily",
        "consumption_monthly_cost_pln": "buy_cost_monthly", "consumption_monthly_kwh": "energy_bought_monthly",
        "production_monthly_kwh": "energy_sold_monthly", "production_monthly_yield_pln": "sell_revenue_monthly",
        "billing_balance_daily_pln": "financial_balance_daily", "billing_balance_monthly_pln": "financial_balance_monthly",
        "energy_balance_daily_kwh": "energy_balance_daily", "energy_balance_monthly_kwh": "energy_balance_monthly",
        "today_purchase_price": "buy_price", "today_sale_price": "sell_price",
    }
    assert mods.migrate.AIO_TO_FORK == {k: f"pstryk_{v}" for k, v in pairs.items()}


# -------------------------------------------------------------- the take-over

def test_take_over_moves_14_entities_with_id_name_and_device(mods):
    hass, aio, fork = _setup(mods)
    _take_over(mods, hass, fork)
    taken = [e for e in hass.registry.for_entry("fork1")]
    assert len(taken) == 14
    by_old_unique = {uid: (eid, name) for uid, eid, name in AIO_ENTITIES}
    for entity in taken:
        assert entity.platform == "pstryk" and entity.device_id == "device-1"
    for aio_uid, fork_uid in mods.migrate.AIO_TO_FORK.items():
        entity_id, name = by_old_unique[aio_uid]
        entity = hass.registry.async_get(entity_id)
        assert entity is not None, entity_id  # the old entity_id survives
        assert entity.unique_id == fork_uid
        assert entity.name == name  # the Polish label, not the English name of the integration


def test_take_over_removes_only_the_two_tomorrow_prices(mods):
    hass, aio, fork = _setup(mods)
    _take_over(mods, hass, fork)
    left = {e.entity_id for e in hass.registry.entities.values()}
    assert "sensor.pstryk_cena_zakupu_pradu_jutro" not in left
    assert "sensor.pstryk_cena_sprzedazy_pradu_jutro" not in left
    assert len(left) == 14  # nothing else disappeared


def test_disable_keeps_the_aio_entry_and_clears_the_marker(mods):
    hass, aio, fork = _setup(mods, action="disable")
    _take_over(mods, hass, fork)
    assert "aio1" in hass.config_entries.entries and aio.disabled_by == "user"
    assert ("remove", "aio1") not in hass.config_entries.log
    assert mods.const.CONF_MIGRATE_FROM not in fork.data and mods.const.CONF_AIO_ACTION not in fork.data
    assert fork.data == {"api_key": AIO_KEY}


def test_remove_deletes_the_aio_entry(mods):
    hass, aio, fork = _setup(mods, action="remove")
    _take_over(mods, hass, fork)
    assert "aio1" not in hass.config_entries.entries
    assert hass.registry.for_entry("aio1") == []
    assert len(hass.registry.for_entry("fork1")) == 14  # the moved ones survive the removal


def test_aio_is_stopped_before_anything_is_moved(mods):
    hass, aio, fork = _setup(mods)
    order = []
    original = hass.registry.async_update_entity_platform
    hass.registry.async_update_entity_platform = lambda *a, **k: (order.append(list(hass.config_entries.log)),
                                                                  original(*a, **k))[1]
    _take_over(mods, hass, fork)
    assert all(("disable", "aio1") in seen for seen in order) and len(order) == 14


def test_unknown_aio_entities_are_left_alone_when_the_entry_is_disabled(mods):
    hass, aio, fork = _setup(mods, action="disable")
    hass.registry.add("sensor.pstryk_przyszla_encja", "future_sensor", "pstryk_aio", "aio1")
    _take_over(mods, hass, fork)
    future = hass.registry.async_get("sensor.pstryk_przyszla_encja")
    assert future is not None and future.platform == "pstryk_aio" and future.config_entry_id == "aio1"


def test_entities_disabled_only_by_the_aio_switch_off_come_back_on(mods):
    hass, aio, fork = _setup(mods, aio_disabled=True)
    _take_over(mods, hass, fork)
    assert all(e.disabled_by is None for e in hass.registry.for_entry("fork1"))


def test_an_entity_the_user_disabled_stays_disabled(mods):
    hass, aio, fork = _setup(mods)
    hass.registry.entities["sensor.pstryk_dzienne_koszty_zuzycia_energii"].disabled_by = Disabler.USER
    _take_over(mods, hass, fork)
    assert hass.registry.async_get("sensor.pstryk_dzienne_koszty_zuzycia_energii").disabled_by is Disabler.USER
    assert hass.registry.async_get("sensor.pstryk_obecna_cena_zakupu_pradu").disabled_by is None


def test_a_label_the_user_set_is_kept(mods):
    hass, aio, fork = _setup(mods)
    hass.registry.entities["sensor.pstryk_dzienne_koszty_zuzycia_energii"].name = "Koszt dziś"
    _take_over(mods, hass, fork)
    assert hass.registry.async_get("sensor.pstryk_dzienne_koszty_zuzycia_energii").name == "Koszt dziś"


def test_a_sensor_added_next_to_aio_earlier_is_replaced_by_the_older_one(mods):
    hass, aio, fork = _setup(mods, fork_twins=True)
    _take_over(mods, hass, fork)
    ids = {e.entity_id for e in hass.registry.entities.values()}
    assert not [i for i in ids if i.endswith("_english")]  # no duplicates, nothing parked
    assert len(hass.registry.for_entry("fork1")) == 14
    assert {e.unique_id for e in hass.registry.for_entry("fork1")} == set(mods.migrate.AIO_TO_FORK.values())


def test_a_twin_of_another_quantity_is_not_touched(mods):
    hass, aio, fork = _setup(mods, fork_twins=True)
    hass.registry.add("sensor.pstryk_total_buy_cost", "pstryk_buy_cost_total", "pstryk", "fork1")
    _take_over(mods, hass, fork)
    assert hass.registry.async_get("sensor.pstryk_total_buy_cost") is not None


def test_repeating_the_take_over_changes_nothing(mods):
    hass, aio, fork = _setup(mods)
    _take_over(mods, hass, fork)
    snapshot = {k: (v.platform, v.unique_id, v.name, v.config_entry_id) for k, v in hass.registry.entities.items()}
    fork.data = {"api_key": AIO_KEY, mods.const.CONF_MIGRATE_FROM: "aio1", mods.const.CONF_AIO_ACTION: "disable"}
    _take_over(mods, hass, fork)
    assert {k: (v.platform, v.unique_id, v.name, v.config_entry_id) for k, v in hass.registry.entities.items()} == snapshot


def test_a_clash_leaves_that_entity_with_aio_instead_of_failing(mods, caplog):
    hass, aio, fork = _setup(mods)
    hass.registry.async_update_entity_platform = lambda *a, **k: (_ for _ in ()).throw(ValueError("clash"))
    _take_over(mods, hass, fork)
    assert len(hass.registry.for_entry("fork1")) == 0
    assert mods.const.CONF_MIGRATE_FROM not in fork.data  # finished, not retried at every start


def test_no_marker_does_nothing(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    _take_over(mods, hass, fork)
    assert hass.config_entries.log == [] and len(hass.registry.for_entry("aio1")) == 16


def test_a_marker_without_an_action_does_nothing_but_is_cleared(mods):
    hass, aio, fork = _setup(mods)
    fork.data.pop(mods.const.CONF_AIO_ACTION)
    _take_over(mods, hass, fork)
    assert len(hass.registry.for_entry("aio1")) == 16 and ("disable", "aio1") not in hass.config_entries.log
    assert mods.const.CONF_MIGRATE_FROM not in fork.data


def test_the_marker_is_gone_when_aio_was_removed_meanwhile(mods):
    hass, aio, fork = _setup(mods)
    del hass.config_entries.entries["aio1"]
    _take_over(mods, hass, fork)
    assert mods.const.CONF_MIGRATE_FROM not in fork.data


def test_a_repair_notice_lists_what_happened(mods):
    hass, aio, fork = _setup(mods, action="disable")
    _take_over(mods, hass, fork)
    (domain, issue_id, kw), = Issues.created
    assert (domain, kw["translation_key"]) == ("pstryk", "migrated_from_aio_disabled")
    assert "sensor.pstryk_dzienne_koszty_zuzycia_energii" in kw["translation_placeholders"]["taken"]
    assert "sensor.pstryk_cena_zakupu_pradu_jutro" in kw["translation_placeholders"]["removed"]

    hass, aio, fork = _setup(mods, action="remove")
    Issues.created.clear()
    _take_over(mods, hass, fork)
    assert Issues.created[0][2]["translation_key"] == "migrated_from_aio_removed"


def test_the_notice_texts_exist_in_both_languages():
    import json
    for lang in ("en", "pl"):
        issues = json.loads((PKG / "translations" / f"{lang}.json").read_text())["issues"]
        for key in ("migrated_from_aio_disabled", "migrated_from_aio_removed"):
            assert issues[key]["title"] and "{taken}" in issues[key]["description"] and "{removed}" in issues[key]["description"]


# ------------------------------------------------------------- entry setup

def _setup_entry(mods, hass, fork):
    """async_setup_entry up to the platforms; records what happened before them."""
    seen = {}

    async def forward(entry, platforms):
        seen["aio_entities_at_forward"] = len(hass.registry.for_entry("aio1"))
        seen["fork_entities_at_forward"] = len(hass.registry.for_entry("fork1"))
        seen["disabled_at_forward"] = sorted(e.entity_id for e in hass.registry.for_entry("fork1")
                                             if e.disabled_by is not None)

    hass.config_entries.async_forward_entry_setups = forward
    fork.update_listeners = []
    fork.add_update_listener = lambda cb: None
    fork.async_on_unload = lambda cb: None
    hass.services = types.SimpleNamespace(has_service=lambda *a: False)
    assert _run(mods.init.async_setup_entry(hass, fork)) is True
    return seen


def test_setup_takes_over_before_any_sensor_is_added(mods):
    hass, aio, fork = _setup(mods)
    seen = _setup_entry(mods, hass, fork)
    assert seen["aio_entities_at_forward"] == 0 and seen["fork_entities_at_forward"] == 14


def test_setup_switches_on_what_2_2_disabled_before_the_sensors_are_added(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    hass.registry.add("sensor.a", "pstryk_buy_daily_average", "pstryk", "fork1", disabled_by=Disabler.INTEGRATION)
    hass.registry.add("sensor.b", "pstryk_sell_daily_average", "pstryk", "fork1", disabled_by=Disabler.USER)
    seen = _setup_entry(mods, hass, fork)
    assert seen["disabled_at_forward"] == ["sensor.b"]


# ------------------------------------------------------------------ preview

def test_the_preview_lists_what_will_happen(mods):
    hass, aio, fork = _setup(mods)
    hass.registry.add("sensor.pstryk_przyszla_encja", "future_sensor", "pstryk_aio", "aio1")
    found = mods.migrate.plan(hass, aio)
    assert len(found["take"]) == 14 and len(found["remove"]) == 2
    assert found["other"] == ["sensor.pstryk_przyszla_encja"]


# ------------------------------------------------------------- enable fixup

def test_entities_disabled_by_the_integration_are_enabled_but_not_the_users(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    hass.registry.add("sensor.a", "pstryk_buy_daily_average", "pstryk", "fork1", disabled_by=Disabler.INTEGRATION)
    hass.registry.add("sensor.b", "pstryk_sell_daily_average", "pstryk", "fork1", disabled_by=Disabler.USER)
    hass.registry.add("sensor.c", "pstryk_buy_yearly_average", "pstryk", "other", disabled_by=Disabler.INTEGRATION)
    enabled = _run(mods.migrate.async_enable_integration_disabled(hass, fork))
    assert enabled == ["sensor.a"]
    assert hass.registry.async_get("sensor.a").disabled_by is None
    assert hass.registry.async_get("sensor.b").disabled_by is Disabler.USER
    assert hass.registry.async_get("sensor.c").disabled_by is Disabler.INTEGRATION  # another entry


# --------------------------------------------------------------- config flow

def _config_flow(mods, hass, *, valid=True, current=()):
    async def validate(h, key):
        validate.keys.append(key)
        return valid
    validate.keys = []
    mods.flow.async_validate_api_key = validate
    flow = mods.flow.PstrykConfigFlow()
    flow.hass = hass
    flow.current_entries = list(current)
    return flow, validate


def test_flow_offers_the_take_over_before_asking_for_a_key(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    del hass.config_entries.entries["fork1"]
    flow, _ = _config_flow(mods, hass)
    form = _run(flow.async_step_user())
    assert form["step_id"] == "migrate"
    placeholders = form["description_placeholders"]
    assert placeholders["taken_count"] == "14"
    assert "sensor.pstryk_cena_zakupu_pradu_jutro" in placeholders["removed"]


def test_flow_does_not_preset_a_choice(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    flow, _ = _config_flow(mods, hass)
    form = _run(flow.async_step_migrate())
    keys = list(form["data_schema"])
    assert [k.schema for k in keys] == ["mode"]
    assert all(k.default == "<none>" for k in keys)  # the user has to pick, nothing is preselected
    _, config = form["data_schema"][keys[0]]
    assert config["options"] == ["disable", "remove", "fresh"]


def test_flow_without_aio_asks_for_the_key_as_before(mods):
    hass = Hass()
    flow, _ = _config_flow(mods, hass)
    assert _run(flow.async_step_user())["step_id"] == "user"


def test_an_aio_entry_already_emptied_is_not_offered_again(mods):
    hass, aio, fork = _setup(mods)
    _take_over(mods, hass, fork)  # AiO stays, disabled, with nothing left to take
    assert "aio1" in hass.config_entries.entries
    del hass.config_entries.entries["fork1"]
    flow, _ = _config_flow(mods, hass)
    assert _run(flow.async_step_user())["step_id"] == "user"

    hass.config_entries.add(fork)
    options = _options_flow(mods, hass, fork, BASE_OPTIONS)
    form = _run(options.async_step_init())
    assert not [k for k in form["data_schema"] if k.schema == "take_over_aio"]


def test_flow_with_an_existing_entry_does_not_offer_the_take_over(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    flow, _ = _config_flow(mods, hass, current=[fork])
    assert _run(flow.async_step_user())["step_id"] == "user"


@pytest.mark.parametrize("mode", ["disable", "remove"])
def test_flow_reuses_the_aio_key_and_records_the_choice(mods, mode):
    hass, aio, fork = _setup(mods, with_marker=False)
    flow, validate = _config_flow(mods, hass)
    _run(flow.async_step_user())
    result = _run(flow.async_step_migrate({"mode": mode}))
    assert validate.keys == [AIO_KEY]  # checked once, the user typed nothing
    assert result["step_id"] == "price_settings"
    assert flow._data == {"api_key": AIO_KEY, mods.const.CONF_MIGRATE_FROM: "aio1",
                          mods.const.CONF_AIO_ACTION: mode}


def test_flow_the_entry_carries_the_key_and_the_marker(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    flow, _ = _config_flow(mods, hass)
    _run(flow.async_step_migrate({"mode": "disable"}))
    flow._async_current_entries = lambda: []
    hass.services = types.SimpleNamespace(has_service=lambda *a: False)
    _run(flow.async_step_price_settings({"buy_top": 5, "sell_top": 5, "buy_worst": 5, "sell_worst": 5}))
    result = _run(flow.async_step_api_retry({}))
    assert result["type"] == "create_entry"
    assert result["data"]["api_key"] == AIO_KEY and result["data"][mods.const.CONF_MIGRATE_FROM] == "aio1"


def test_flow_fresh_setup_asks_for_a_key_and_takes_nothing_over(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    flow, validate = _config_flow(mods, hass)
    _run(flow.async_step_user())
    form = _run(flow.async_step_migrate({"mode": "fresh"}))
    assert form["step_id"] == "user" and validate.keys == []
    assert mods.const.CONF_MIGRATE_FROM not in flow._data
    _run(flow.async_step_user({"api_key": "typed"}))
    assert flow._data == {"api_key": "typed"}


def test_flow_an_invalid_aio_key_is_reported_not_used(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    flow, _ = _config_flow(mods, hass, valid=False)
    result = _run(flow.async_step_migrate({"mode": "disable"}))
    assert result["step_id"] == "migrate" and result["errors"] == {"base": "aio_key_invalid"}
    assert flow._data == {}


def test_flow_a_full_api_limit_is_reported_and_nothing_is_decided(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    flow, _ = _config_flow(mods, hass, valid=None)
    result = _run(flow.async_step_migrate({"mode": "disable"}))
    assert result["errors"] == {"base": "api_budget_full"} and flow._data == {}


def test_flow_a_running_aio_hands_over_its_key_without_a_request(mods):
    """AiO is loaded, so its key was just accepted by Pstryk: no slot of the
    3 requests an hour is spent on checking it again."""
    hass, aio, fork = _setup(mods, with_marker=False)
    aio.state = mods.flow.ConfigEntryState.LOADED
    flow, validate = _config_flow(mods, hass, valid=False)
    _run(flow.async_step_migrate({"mode": "disable"}))
    assert validate.keys == []
    assert flow._data == {"api_key": AIO_KEY, mods.const.CONF_MIGRATE_FROM: "aio1",
                          mods.const.CONF_AIO_ACTION: "disable"}


def test_flow_a_running_aio_without_a_key_is_reported(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    aio.state = mods.flow.ConfigEntryState.LOADED
    aio.data = {}
    flow, validate = _config_flow(mods, hass)
    result = _run(flow.async_step_migrate({"mode": "disable"}))
    assert result["errors"] == {"base": "aio_key_invalid"} and validate.keys == [] and flow._data == {}


def test_flow_an_aio_that_is_not_running_has_its_key_checked(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    aio.state = "setup_retry"  # e.g. its start failed: the key is not proven
    flow, validate = _config_flow(mods, hass)
    _run(flow.async_step_migrate({"mode": "disable"}))
    assert validate.keys == [AIO_KEY] and flow._data["api_key"] == AIO_KEY


def test_flow_several_aio_entries_ask_which_one(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    hass.config_entries.add(Entry("aio2", "pstryk_aio", {"api_key": "other-key"}, title="Pstryk AiO 2"))
    hass.registry.add("sensor.pstryk_obecna_cena_zakupu_pradu_2", "today_purchase_price", "pstryk_aio", "aio2")
    flow, validate = _config_flow(mods, hass)
    form = _run(flow.async_step_migrate())
    assert [k.schema for k in form["data_schema"]] == ["aio_entry", "mode"]
    _run(flow.async_step_migrate({"aio_entry": "aio2", "mode": "disable"}))
    assert validate.keys == ["other-key"] and flow._data[mods.const.CONF_MIGRATE_FROM] == "aio2"


# -------------------------------------------------------------- options flow

def _options_flow(mods, hass, fork, options):
    fork.options = dict(options)
    flow = mods.flow.PstrykOptionsFlowHandler()
    flow.hass, flow.config_entry = hass, fork
    return flow


BASE_OPTIONS = {"buy_top": 5, "sell_top": 5, "buy_worst": 5, "sell_worst": 5, "json_sensor_enabled": False}


def test_options_offer_the_take_over_only_when_aio_exists(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    form = _run(_options_flow(mods, hass, fork, BASE_OPTIONS).async_step_init())
    take = [k for k in form["data_schema"] if k.schema == "take_over_aio"]
    assert take and take[0].default is False  # off unless the user turns it on

    hass.config_entries.entries.pop("aio1")
    form = _run(_options_flow(mods, hass, fork, BASE_OPTIONS).async_step_init())
    assert not [k for k in form["data_schema"] if k.schema == "take_over_aio"]


def test_options_without_the_take_over_save_as_before(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    flow = _options_flow(mods, hass, fork, BASE_OPTIONS)
    result = _run(flow.async_step_init({**BASE_OPTIONS, "take_over_aio": False}))
    assert result["type"] == "create_entry" and "take_over_aio" not in result["data"]
    assert len(hass.registry.for_entry("aio1")) == 16  # AiO untouched


def test_options_take_over_runs_for_an_installed_integration(mods):
    hass, aio, fork = _setup(mods, with_marker=False, fork_twins=True)
    flow = _options_flow(mods, hass, fork, BASE_OPTIONS)
    form = _run(flow.async_step_init({**BASE_OPTIONS, "take_over_aio": True}))
    assert form["step_id"] == "migrate_aio"
    assert len(hass.registry.for_entry("aio1")) == 16  # nothing moved before the choice
    result = _run(flow.async_step_migrate_aio({"mode": "disable"}))
    assert result["type"] == "create_entry" and result["data"] == BASE_OPTIONS
    assert len(hass.registry.for_entry("fork1")) == 14
    assert ("reload", "fork1") in hass.config_entries.log  # unchanged options: no listener, so reload by hand


def test_options_take_over_with_changed_options_leaves_the_reload_to_the_listener(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    flow = _options_flow(mods, hass, fork, BASE_OPTIONS)
    _run(flow.async_step_init({**BASE_OPTIONS, "buy_top": 7, "take_over_aio": True}))
    result = _run(flow.async_step_migrate_aio({"mode": "remove"}))
    assert result["data"]["buy_top"] == 7
    assert ("reload", "fork1") not in hass.config_entries.log  # the options update reloads it once


def test_options_a_different_api_key_blocks_the_take_over(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    fork.data["api_key"] = "another-account"
    flow = _options_flow(mods, hass, fork, BASE_OPTIONS)
    _run(flow.async_step_init({**BASE_OPTIONS, "take_over_aio": True}))
    result = _run(flow.async_step_migrate_aio({"mode": "disable"}))
    assert result["step_id"] == "migrate_aio" and result["errors"] == {"base": "different_api_key"}
    assert len(hass.registry.for_entry("aio1")) == 16 and hass.config_entries.log == []


def test_options_choice_has_no_fresh_option_and_no_preset(mods):
    hass, aio, fork = _setup(mods, with_marker=False)
    flow = _options_flow(mods, hass, fork, BASE_OPTIONS)
    _run(flow.async_step_init({**BASE_OPTIONS, "take_over_aio": True}))
    form = _run(flow.async_step_migrate_aio())
    key, = list(form["data_schema"])
    assert key.default == "<none>" and form["data_schema"][key][1]["options"] == ["disable", "remove"]


# ------------------------------------------------------------- translations

def test_flow_texts_exist_in_both_languages():
    import json
    for lang in ("en", "pl"):
        t = json.loads((PKG / "translations" / f"{lang}.json").read_text())
        for step in (t["config"]["step"]["migrate"], t["options"]["step"]["migrate_aio"]):
            assert {"{taken_count}", "{taken}", "{removed}", "{other}"} <= {
                p for p in ("{taken_count}", "{taken}", "{removed}", "{other}") if p in step["description"]}
            assert step["data"]["mode"] and step["data"]["aio_entry"]
        assert t["config"]["error"]["aio_key_invalid"]
        assert t["options"]["error"]["different_api_key"] and t["options"]["error"]["aio_gone"]
        assert t["options"]["step"]["init"]["data"]["take_over_aio"]
        assert set(t["selector"]["aio_mode"]["options"]) == {"disable", "remove", "fresh"}
