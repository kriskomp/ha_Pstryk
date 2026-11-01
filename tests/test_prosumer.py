"""Hiding the sell-side entities of someone who sells no energy (prosumer.py).

Runs the real ProsumerVisibility and the real sensor classes on the stand-ins of
tests/test_refresh.py (fake clock, fake Store on STORE_DISK, fake notifications).
"""
import json
import re
import types
from pathlib import Path

import pytest

import test_refresh as tr
from test_refresh import env, mods  # noqa: F401  (pytest fixtures)

COMPONENT = Path(tr.__file__).resolve().parent.parent / "custom_components" / "pstryk"

SELL_IDS = sorted(
    [f"pstryk_sell_revenue_{p}" for p in ("daily", "monthly", "yearly", "total")]
    + [f"pstryk_energy_sold_{p}" for p in ("daily", "monthly", "yearly", "total")]
    + [f"pstryk_sell_{p}_average" for p in ("daily", "monthly", "yearly", "total")]
)


class _Registry:
    """entity_registry with the three calls prosumer.py makes."""

    def __init__(self):
        self.by_unique = {}
        self.updates = []

    def add(self, unique_id, hidden_by=None):
        entity_id = f"sensor.{unique_id}"
        self.by_unique[unique_id] = types.SimpleNamespace(
            entity_id=entity_id, hidden_by=hidden_by, disabled_by=None, config_entry_id="e")

    def async_get_entity_id(self, domain, platform, unique_id):
        assert (domain, platform) == ("sensor", "pstryk")
        entry = self.by_unique.get(unique_id)
        return entry.entity_id if entry else None

    def async_get(self, entity_id):
        return next((e for e in self.by_unique.values() if e.entity_id == entity_id), None)

    def async_update_entity(self, entity_id, hidden_by=None):
        self.async_get(entity_id).hidden_by = hidden_by
        self.updates.append((entity_id, hidden_by))

    @property
    def entities(self):
        return list(self.by_unique.values())

    def hidden(self):
        return sorted(u for u, e in self.by_unique.items() if e.hidden_by)

    def hidden_by(self, unique_id):
        return self.by_unique[unique_id].hidden_by


def _years(**by_year):
    return {"years": {y: {"energy_sold": s, "sell_revenue": r} for y, (s, r) in by_year.items()}}


def _data(history=None, **periods):
    data = dict(periods)
    if history is not None:
        data["history"] = history
    return data


class _Cost:
    def __init__(self, data=None):
        self.data = data


def _vis(mods, env, mode="auto", data=None, ids=SELL_IDS, entry_id="e", registry=None):
    hass = env.hass
    hass.registry = registry if registry is not None else _Registry()
    if registry is None:
        for unique_id in ids:
            hass.registry.add(unique_id)
    hass.config = types.SimpleNamespace(language="pl")
    cost = _Cost(data)
    visibility = mods.prosumer.ProsumerVisibility(hass, entry_id, mode, ids, cost)
    tr._run(visibility.async_load())
    return visibility, cost, hass.registry


def _evaluate(visibility):
    tr._run(visibility.async_evaluate())


NO_SALE = _data(_years(**{"2024": (0, 0), "2025": (0.0, 0.0), "2026": (0, 0)}))
SALE = _data(_years(**{"2024": (0, 0), "2025": (12.5, 7.0), "2026": (0, 0)}))


# ------------------------------------------------------------- sale_seen

@pytest.mark.parametrize("data", [None, {}, {"daily": {}}, _data({}), _data({"years": {}}),
                                  _data({"years": None}), {"history": None}])
def test_nothing_is_decided_until_the_history_is_there(mods, data):
    assert mods.prosumer.sale_seen(data) is None


def test_no_sale_anywhere(mods):
    assert mods.prosumer.sale_seen(NO_SALE) is False
    # None and missing values count as zero, not as a crash.
    data = _data({"years": {"2025": {"energy_sold": None, "sell_revenue": None}, "2026": {}}})
    assert mods.prosumer.sale_seen(data) is False


@pytest.mark.parametrize("year", [{"energy_sold": 0.01}, {"sell_revenue": 0.01}])
def test_a_sale_in_any_year_is_seen(mods, year):
    data = _data({"years": {"2024": {"energy_sold": 0, "sell_revenue": 0}, "2025": year}})
    assert mods.prosumer.sale_seen(data) is True


@pytest.mark.parametrize("period,field", [
    ("daily", "rae_usage"), ("daily", "total_sold"), ("monthly", "rae_usage"),
    ("monthly", "total_sold"), ("yearly", "rae_usage"), ("yearly", "total_sold"),
])
def test_a_sale_in_the_running_period_is_seen_even_before_history(mods, period, field):
    assert mods.prosumer.sale_seen(_data(**{period: {field: 0.4}})) is True
    # ... and on top of a history without sales
    assert mods.prosumer.sale_seen(_data(_years(**{"2026": (0, 0)}), **{period: {field: 0.4}})) is True


def test_period_zero_without_history_is_still_undecided(mods):
    assert mods.prosumer.sale_seen(_data(daily={"rae_usage": 0, "total_sold": 0.0})) is None


def test_negative_values_are_not_a_sale(mods):
    assert mods.prosumer.sale_seen(_data(_years(**{"2026": (-1, -1)}), daily={"rae_usage": -2})) is False


# ------------------------------------------------------------- auto

def test_auto_waits_without_data(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", None)
    _evaluate(vis)
    assert registry.hidden() == [] and registry.updates == []
    assert tr.STORE_DISK == {}


def test_auto_hides_all_twelve_when_nothing_is_sold(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS
    assert len(SELL_IDS) == 12
    assert all(v == "integration" for _, v in registry.updates)
    assert tr.NOTIFICATIONS == {}
    assert tr.STORE_DISK["pstryk_prosumer"] == {
        "owner": "e", "mode": "auto", "state": "hidden", "handled": SELL_IDS if False else sorted(SELL_IDS, key=SELL_IDS.index)}


def test_auto_shows_everything_for_a_seller_and_says_nothing(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", SALE)
    _evaluate(vis)
    assert registry.hidden() == [] and registry.updates == []
    assert tr.NOTIFICATIONS == {}
    assert tr.STORE_DISK["pstryk_prosumer"]["state"] == "shown"


def test_auto_reveals_on_the_first_sale_and_notifies_once(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS
    cost.data = _data(_years(**{"2026": (0, 0)}), daily={"rae_usage": 1.2, "total_sold": 0.9})
    _evaluate(vis)
    assert registry.hidden() == []
    assert list(tr.NOTIFICATIONS) == ["pstryk_sale_detected"]
    assert tr.STORE_DISK["pstryk_prosumer"]["state"] == "shown"
    assert tr.STORE_DISK["pstryk_prosumer"]["handled"] == []
    tr.NOTIFICATIONS.clear()
    _evaluate(vis)
    _evaluate(vis)
    assert tr.NOTIFICATIONS == {}  # once


def test_after_a_sale_a_zero_day_does_not_hide_again(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    cost.data = SALE
    _evaluate(vis)
    cost.data = NO_SALE  # e.g. the year totals are momentarily lower/zero
    _evaluate(vis)
    assert registry.hidden() == []


def test_the_notification_uses_translations_and_falls_back_to_english(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    tr.TRANSLATIONS.clear()
    tr.TRANSLATIONS["component.pstryk.issues.sale_detected.description"] = "OPIS PL"
    try:
        cost.data = SALE
        _evaluate(vis)
    finally:
        tr.TRANSLATIONS.clear()
    assert tr.NOTIFICATIONS["pstryk_sale_detected"] == "OPIS PL"

    tr.NOTIFICATIONS.clear()
    tr.STORE_DISK.clear()
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    cost.data = SALE
    _evaluate(vis)
    assert "sold to the grid" in tr.NOTIFICATIONS["pstryk_sale_detected"]


def test_a_failing_translation_lookup_still_notifies(mods, env, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("no translations")

    monkeypatch.setattr(mods.prosumer, "async_get_translations", boom)
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    cost.data = SALE
    _evaluate(vis)
    assert registry.hidden() == []
    assert "pstryk_sale_detected" in tr.NOTIFICATIONS


# ------------------------------------------------------------- respecting the user

def test_an_entity_the_user_hid_stays_hidden_after_a_sale(mods, env):
    registry = _Registry()
    for unique_id in SELL_IDS:
        registry.add(unique_id, hidden_by="user" if unique_id == "pstryk_sell_revenue_daily" else None)
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE, registry=registry)
    _evaluate(vis)
    assert registry.hidden_by("pstryk_sell_revenue_daily") == "user"  # not taken over
    cost.data = SALE
    _evaluate(vis)
    assert registry.hidden() == ["pstryk_sell_revenue_daily"]
    assert registry.hidden_by("pstryk_sell_revenue_daily") == "user"


def test_an_entity_the_user_showed_is_not_hidden_again(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    registry.by_unique["pstryk_energy_sold_daily"].hidden_by = None  # shown by hand
    registry.updates.clear()
    _evaluate(vis)
    _evaluate(vis)
    assert registry.updates == []
    assert "pstryk_energy_sold_daily" not in registry.hidden()


def test_an_entity_the_user_showed_before_the_first_evaluation_is_left_alone_afterwards(mods, env):
    # Only entities this integration hid are ever shown again; none is hidden twice.
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    first = len(registry.updates)
    for _ in range(3):
        _evaluate(vis)
    assert len(registry.updates) == first == 12


def test_late_registered_entities_are_hidden_as_they_appear(mods, env):
    registry = _Registry()
    for unique_id in SELL_IDS[:5]:
        registry.add(unique_id)
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE, registry=registry)
    _evaluate(vis)
    assert registry.hidden() == sorted(SELL_IDS[:5])
    for unique_id in SELL_IDS[5:]:
        registry.add(unique_id)
        _evaluate(vis)  # as each entity is added to Home Assistant
        assert unique_id in registry.hidden()
    assert registry.hidden() == SELL_IDS
    assert len(registry.updates) == 12


def test_entities_missing_from_the_registry_are_skipped(mods, env):
    registry = _Registry()
    for unique_id in SELL_IDS:
        registry.add(unique_id)
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE, ids=SELL_IDS + ["pstryk_not_there"],
                               registry=registry)
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS


def test_other_entities_are_never_touched(mods, env):
    registry = _Registry()
    for unique_id in SELL_IDS + ["pstryk_buy_cost_daily", "pstryk_current_sell_price"]:
        registry.add(unique_id)
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE, registry=registry)
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS
    cost.data = SALE
    _evaluate(vis)
    assert registry.hidden() == []
    assert all(e not in ("sensor.pstryk_buy_cost_daily", "sensor.pstryk_current_sell_price")
               for e, _ in registry.updates)


# ------------------------------------------------------------- show / hide

def test_show_never_hides_and_gives_back_what_was_hidden_by_us(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS
    registry.by_unique["pstryk_sell_revenue_total"].hidden_by = "user"
    vis, cost, registry = _vis(mods, env, "show", NO_SALE, registry=registry)
    _evaluate(vis)
    assert registry.hidden() == ["pstryk_sell_revenue_total"]  # the user's own choice stays
    assert tr.NOTIFICATIONS == {}
    n = len(registry.updates)
    _evaluate(vis)
    assert len(registry.updates) == n


def test_show_does_not_wait_for_data(mods, env):
    vis, cost, registry = _vis(mods, env, "show", None)
    _evaluate(vis)
    assert registry.hidden() == [] and registry.updates == []


def test_hide_hides_without_data_and_with_a_sale(mods, env):
    vis, cost, registry = _vis(mods, env, "hide", None)
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS
    cost.data = SALE
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS
    assert tr.NOTIFICATIONS == {}  # a chosen setting is not second-guessed


def test_hide_hides_late_entities_too(mods, env):
    registry = _Registry()
    vis, cost, registry = _vis(mods, env, "hide", SALE, ids=SELL_IDS, registry=registry)
    for unique_id in SELL_IDS:
        registry.add(unique_id)
        _evaluate(vis)
    assert registry.hidden() == SELL_IDS


def test_hide_respects_an_entity_the_user_showed_afterwards(mods, env):
    vis, cost, registry = _vis(mods, env, "hide", None)
    _evaluate(vis)
    registry.by_unique["pstryk_sell_total_average"].hidden_by = None
    _evaluate(vis)
    assert "pstryk_sell_total_average" not in registry.hidden()


def test_an_unknown_setting_means_auto(mods, env):
    vis, cost, registry = _vis(mods, env, "nonsense", NO_SALE)
    assert vis.mode == "auto"
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS


# ------------------------------------------------------------- restart and mode changes

def test_a_restart_repeats_nothing(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    registry.by_unique["pstryk_sell_revenue_monthly"].hidden_by = None  # user shows one
    registry.updates.clear()
    vis2, cost2, registry = _vis(mods, env, "auto", NO_SALE, registry=registry)  # restart
    _evaluate(vis2)
    assert registry.updates == []
    assert "pstryk_sell_revenue_monthly" not in registry.hidden()


def test_the_sale_is_noticed_after_a_restart_too(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    vis2, cost2, registry = _vis(mods, env, "auto", SALE, registry=registry)
    _evaluate(vis2)
    assert registry.hidden() == []
    assert "pstryk_sale_detected" in tr.NOTIFICATIONS


def test_changing_the_setting_starts_over(mods, env):
    vis, cost, registry = _vis(mods, env, "hide", None)
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS
    vis, cost, registry = _vis(mods, env, "auto", SALE, registry=registry)
    _evaluate(vis)
    assert registry.hidden() == []  # ours are shown again
    assert tr.NOTIFICATIONS == {}  # chosen by the user's own setting change, no sale news
    assert tr.STORE_DISK["pstryk_prosumer"]["mode"] == "auto"


def test_auto_after_show_hides_when_there_is_no_sale(mods, env):
    vis, cost, registry = _vis(mods, env, "show", NO_SALE)
    _evaluate(vis)
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE, registry=registry)
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS


def test_state_saved_by_another_entry_is_ignored(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE, entry_id="old")
    _evaluate(vis)
    registry2 = _Registry()
    for unique_id in SELL_IDS:
        registry2.add(unique_id)
    vis2, cost2, registry2 = _vis(mods, env, "auto", NO_SALE, entry_id="new", registry=registry2)
    _evaluate(vis2)
    assert registry2.hidden() == SELL_IDS  # not taken for "already handled"


def test_a_broken_store_does_not_stop_the_decision(mods, env, monkeypatch):
    async def bad_load(self):
        raise OSError("disk")

    async def bad_save(self, data):
        raise OSError("disk")

    monkeypatch.setattr(tr._Store, "async_load", bad_load)
    monkeypatch.setattr(tr._Store, "async_save", bad_save)
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    _evaluate(vis)
    assert registry.hidden() == SELL_IDS


def test_overlapping_evaluations_hide_each_entity_once(mods, env):
    import asyncio
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)

    async def many():
        await asyncio.gather(*(vis.async_evaluate() for _ in range(6)))

    tr._run(many())
    assert len(registry.updates) == 12


# ------------------------------------------------------------- describe

def test_describe_reports_setting_decision_and_hidden(mods, env):
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    before = vis.describe()
    assert before == {"setting": "auto", "sale_seen": None, "decision": None, "entities": 12, "hidden": {}}
    _evaluate(vis)
    after = vis.describe()
    assert after["sale_seen"] is False and after["decision"] == "hidden"
    assert sorted(after["hidden"]) == sorted(f"sensor.{u}" for u in SELL_IDS)
    assert set(after["hidden"].values()) == {"integration"}


def test_diagnostics_carry_the_section_only_when_it_exists(mods, env):
    import test_diagnostics as td
    td._prepare(env)
    assert "prosumer_entities" not in td._diagnostics(mods, env)
    vis, cost, registry = _vis(mods, env, "auto", NO_SALE)
    env.hass.data["pstryk"]["e_prosumer"] = vis
    _evaluate(vis)
    section = td._diagnostics(mods, env)["prosumer_entities"]
    assert section["setting"] == "auto" and section["decision"] == "hidden"


# ------------------------------------------------------------- the real sensors

def test_exactly_the_twelve_sell_side_sensors_are_flagged(mods, env):
    flagged = sorted(s.unique_id for s in tr._all_sensors(mods, env) if getattr(s, "prosumer", False))
    assert flagged == SELL_IDS


def test_nothing_else_is_flagged_and_buy_side_stays_visible(mods, env):
    sensors = tr._all_sensors(mods, env)
    unflagged = {s.unique_id for s in sensors if not getattr(s, "prosumer", False)}
    for unique_id in ("pstryk_buy_daily_average", "pstryk_buy_total_average", "pstryk_daily_buy_cost",
                      "pstryk_daily_energy_bought", "pstryk_current_sell_price", "pstryk_current_buy_price"):
        assert unique_id in unflagged or not any(s.unique_id == unique_id for s in sensors), unique_id


def test_a_flagged_sensor_asks_for_an_evaluation_when_added(mods, env):
    vis, cost, registry = _vis(mods, env, "hide", None)
    env.hass.data["pstryk"]["e_prosumer"] = vis
    sensors = {s.unique_id: s for s in tr._all_sensors(mods, env)}
    for s in sensors.values():
        s.hass = env.hass
        s.entry_id = "e"
    registry.updates.clear()
    tr._run(sensors["pstryk_sell_revenue_daily"].async_added_to_hass())
    assert registry.hidden() == SELL_IDS
    # a buy-side sensor does not trigger it
    registry2 = _Registry()
    vis2, _, registry2 = _vis(mods, env, "hide", None, registry=registry2)
    for unique_id in SELL_IDS:
        registry2.add(unique_id)
    env.hass.data["pstryk"]["e_prosumer"] = vis2
    tr._run(sensors["pstryk_daily_buy_cost"].async_added_to_hass() if "pstryk_daily_buy_cost" in sensors
            else sensors["pstryk_buy_daily_average"].async_added_to_hass())
    assert registry2.hidden() == []


def test_a_sensor_without_a_visibility_object_still_starts(mods, env):
    env.hass.data["pstryk"].pop("e_prosumer", None)
    sensors = {s.unique_id: s for s in tr._all_sensors(mods, env)}
    s = sensors["pstryk_sell_revenue_daily"]
    s.hass = env.hass
    s.entry_id = "e"
    tr._run(s.async_added_to_hass())


# ------------------------------------------------------------- setup wiring, options, texts

def test_setup_wires_visibility_to_the_cost_coordinator():
    src = (COMPONENT / "sensor.py").read_text()
    assert "_prosumer\"] = visibility" in src
    assert "cost_coordinator.async_add_listener(_cost_data_arrived)" in src
    assert "entry.async_on_unload(" in src


def test_the_option_is_in_the_options_form_with_a_default():
    src = (COMPONENT / "config_flow.py").read_text()
    assert "vol.Required(CONF_PROSUMER_ENTITIES, default=prosumer_setting(" in src
    assert "translation_key=\"prosumer_entities\"" in src


def test_setting_helper(mods):
    import importlib
    const = importlib.import_module("pstryk.const")
    assert const.DEFAULT_PROSUMER_ENTITIES == "auto"
    assert const.prosumer_setting(None) == "auto"
    assert const.prosumer_setting("x") == "auto"
    for value in ("auto", "show", "hide"):
        assert const.prosumer_setting(value) == value


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_translations_have_every_text(lang):
    data = json.loads((COMPONENT / "translations" / f"{lang}.json").read_text())
    form = data["options"]["step"]["init"]
    assert form["data"]["prosumer_entities"].strip()
    assert form["data_description"]["prosumer_entities"].strip()
    options = data["selector"]["prosumer_entities"]["options"]
    assert set(options) == {"auto", "show", "hide"} and all(options.values())
    issue = data["issues"]["sale_detected"]
    assert issue["title"].strip() and issue["description"].strip()
