"""Minimal stand-in for Home Assistant's template engine, enough to run the YAML in docs/arbitraz.

Not Home Assistant: a Jinja2 sandbox with the handful of HA globals and filters those templates use
(states, state_attr, now, timedelta, as_datetime, as_local, bool) and HA's "render, then literal_eval"
result parsing. Good for catching template mistakes; the final check is still done on a real HA.
"""
import ast
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from jinja2.sandbox import ImmutableSandboxedEnvironment

TZ = ZoneInfo("Europe/Warsaw")
DOCS = Path(__file__).resolve().parent.parent / "docs" / "arbitraz"


def load(name):
    return yaml.safe_load((DOCS / name).read_text(encoding="utf-8"))


def make_env(state, attrs, now):
    env = ImmutableSandboxedEnvironment()

    def as_datetime(value, default=None):
        if isinstance(value, dt.datetime):
            return value
        return dt.datetime.fromisoformat(str(value).replace(" ", "T"))

    def as_local(value):
        return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)

    def to_bool(value, default=False):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "yes", "on", "1"):
            return True
        if text in ("false", "no", "off", "0"):
            return False
        return default

    env.globals.update(
        states=lambda entity: state.get(entity, "unknown"),
        state_attr=lambda entity, attr: attrs.get(entity, {}).get(attr),
        now=lambda: now,
        timedelta=dt.timedelta,
        as_datetime=as_datetime,
        as_local=as_local,
    )
    env.filters["as_local"] = as_local
    env.filters["bool"] = to_bool
    return env


def native(text):
    """HA turns a rendered template into a Python value when it is a literal, else keeps the string."""
    try:
        return ast.literal_eval(text.strip())
    except (ValueError, SyntaxError):
        return text


def render_variables(step, env, ctx):
    for key, value in step["variables"].items():
        ctx[key] = native(env.from_string(value).render(**ctx)) if isinstance(value, str) else value
    return ctx


def run_planner(state, attrs, kal, now, dzien=None, replace=None):
    """Runs script.pstryk_arbitraz_plan up to its response; `replace` patches the YAML text (parameters)."""
    text = (DOCS / "pstryk_arbitraz_plan.yaml").read_text(encoding="utf-8")
    for old, new in (replace or {}).items():
        assert old in text, old
        text = text.replace(old, new)
    doc = yaml.safe_load(text)
    env = make_env(state, attrs, now)
    ctx = {} if dzien is None else {"dzien": dzien}
    for step in doc["sequence"]:
        if "variables" in step:
            render_variables(step, env, ctx)
        elif step.get("action") == "calendar.get_events":
            ctx["kal"] = kal
    return ctx["wynik"]
