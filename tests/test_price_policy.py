"""Tests for price_policy.py, loaded by path so Home Assistant is not needed."""
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
WARSAW = ZoneInfo("Europe/Warsaw")
_spec = importlib.util.spec_from_file_location(
    "price_policy", ROOT / "custom_components" / "pstryk" / "price_policy.py"
)
price_policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(price_policy)


def _local(*args):
    return datetime(*args, tzinfo=WARSAW)


def _day(date, price=1.0, tge=0.5, hours=24, key=True):
    entries = []
    for h in range(hours):
        entry = {"start": f"{date}T{h:02d}:00:00", "price": price}
        if key:
            entry["tge_price"] = tge
        entries.append(entry)
    return entries


@pytest.mark.parametrize(
    "entries, now, expected",
    [
        (_day("2026-10-04"), _local(2026, 10, 4, 9, 0), True),
        (_day("2026-10-04", key=False), _local(2026, 10, 4, 9, 0), True),  # cached before tge_price was kept
        (_day("2026-10-04", price=0.0, tge=None), _local(2026, 10, 4, 9, 0), False),  # unpublished sell rows
        (_day("2026-10-04", price=None, tge=None), _local(2026, 10, 4, 9, 0), False),  # unpublished buy rows
        (_day("2026-10-03"), _local(2026, 10, 4, 9, 0), False),  # yesterday only
        (_day("2026-10-04", hours=12), _local(2026, 10, 4, 9, 0), False),  # partial day
        (_day("2026-10-04", hours=20), _local(2026, 10, 4, 21, 0), False),  # current hour missing
        (_day("2026-10-04", hours=20), _local(2026, 10, 4, 19, 0), True),
    ],
)
def test_today_published(entries, now, expected):
    assert price_policy.today_published(entries, now) is expected


@pytest.mark.parametrize(
    "has_tomorrow, now, expected",
    [
        (False, _local(2026, 10, 4, 11, 0), False),  # not due yet
        (False, _local(2026, 10, 4, 12, 4), False),
        (False, _local(2026, 10, 4, 12, 5), True),  # due and missing
        (True, _local(2026, 10, 4, 12, 30), False),
    ],
)
def test_tomorrow_fetch_due(has_tomorrow, now, expected):
    assert price_policy.tomorrow_fetch_due(has_tomorrow, now) is expected


# Fork kriskomp/ha_Pstryk: one hourly rhythm at :05 (prices :05:00, cost :05:30).
@pytest.mark.parametrize(
    "now, expected",
    [
        (_local(2026, 10, 4, 9, 0), _local(2026, 10, 4, 9, 5, 30)),
        (_local(2026, 10, 4, 9, 5, 29), _local(2026, 10, 4, 9, 5, 30)),
        (_local(2026, 10, 4, 9, 5, 30), _local(2026, 10, 4, 10, 5, 30)),
        (_local(2026, 10, 4, 23, 55), _local(2026, 10, 5, 0, 5, 30)),
    ],
)
def test_next_cost_run(now, expected):
    assert price_policy.next_cost_run(now) == expected


def test_cost_runs_every_hour_but_waits_for_tomorrows_prices():
    def skipped(has_tomorrow):
        return [h for h in range(24) if not price_policy.cost_run_allowed(_local(2026, 10, 4, h, 5, 30), has_tomorrow)]

    assert skipped(True) == []
    assert skipped(False) == list(range(12, 24))


def test_cost_keeps_a_slot_only_before_a_price_request():
    def keeping(has_tomorrow):
        return [h for h in range(24) if price_policy.cost_keep_free(_local(2026, 10, 4, h, 5, 30), has_tomorrow)]

    assert keeping(True) == [23]  # the 00:05 refresh
    assert keeping(False) == list(range(11, 24))  # the checks from 12:05


@pytest.mark.parametrize(
    "now, expected",
    [
        (_local(2026, 10, 4, 0, 1), _local(2026, 10, 4, 0, 5)),
        (_local(2026, 10, 4, 0, 5), _local(2026, 10, 5, 0, 5)),
        (_local(2026, 10, 4, 23, 59), _local(2026, 10, 5, 0, 5)),
    ],
)
def test_next_midnight_refresh(now, expected):
    assert price_policy.next_midnight_refresh(now) == expected


@pytest.mark.parametrize(
    "now, expected",
    [
        (_local(2026, 10, 4, 0, 1), _local(2026, 10, 4, 12, 5)),
        (_local(2026, 10, 4, 12, 0, 4), _local(2026, 10, 4, 12, 5)),
        (_local(2026, 10, 4, 12, 5, 0, 5000), _local(2026, 10, 4, 12, 25)),
        (_local(2026, 10, 4, 12, 26), _local(2026, 10, 4, 12, 45)),
        (_local(2026, 10, 4, 12, 45, 1), _local(2026, 10, 4, 13, 5)),
        (_local(2026, 10, 4, 23, 25, 1), _local(2026, 10, 4, 23, 45)),
        (_local(2026, 10, 4, 23, 45, 1), _local(2026, 10, 5, 12, 5)),
    ],
)
def test_next_tomorrow_check(now, expected):
    assert price_policy.next_tomorrow_check(now) == expected


def test_tomorrow_checks_fit_the_hourly_budget():
    checks, now = [], _local(2026, 10, 4, 0, 1)
    while True:
        now = price_policy.next_tomorrow_check(now)
        if now.day != 4:
            break
        checks.append(now)
    assert checks[:3] == [_local(2026, 10, 4, 12, m) for m in (5, 25, 45)]
    assert max(sum(1 for c in checks if s <= c < s + timedelta(hours=1)) for s in checks) == 3


def test_dst_change_keeps_local_check_times():
    nxt = price_policy.next_tomorrow_check(_local(2026, 10, 24, 23, 55))
    assert (nxt.day, nxt.hour, nxt.minute) == (25, 12, 5)
    assert nxt.utcoffset().total_seconds() == 3600
