"""When the integration may spend API requests: prices first, cost on leftovers.

Pure functions with no Home Assistant imports. Times are local (Europe/Warsaw).
"""
from datetime import datetime, timedelta, timezone

# Pstryk publishes tomorrow's prices shortly after 12:00 (seen 2026-10-01 to
# 10-04; on 10-04 the API still had none at 12:00:04).
TOMORROW_EXPECTED_FROM = (12, 5)

# One hourly rhythm at :05 (fork kriskomp/ha_Pstryk). Pstryk serves a closed
# hour's meter data within 3 minutes of its end (measured 2026-10-18: hour
# 23:00 empty at 00:00:15, filled at 00:03:03); a running hour stays empty.
# Prices go first at :05:00 when they are needed, cost follows at :05:30.

# Checks for tomorrow's prices: 12:05, 12:25, 12:45, ... every 20 minutes until
# they are in. Three per hour is the whole hourly budget, so cost waits.
TOMORROW_FIRST_CHECK = (12, 5)
TOMORROW_INTERVAL_MINUTES = 20
TOMORROW_LAST_CHECK = (23, 45)

# Midnight price refresh at 00:05, in the same rhythm (was 00:01).
MIDNIGHT_REFRESH = (0, 5)

# Cost runs every hour at :05:30, after the price requests of :05:00. It waits
# while tomorrow's prices are missing after 12:00. Its last-hour slots free at
# the next :05:32, so a price request at the next :05:00 still finds room as
# long as cost leaves one slot free: it does so in the hours before a price
# request is due (23: the 00:05 refresh; 11 and later without tomorrow's
# prices: the checks from 12:05). Otherwise cost may use the whole budget.
COST_RUN_MINUTE = 5
COST_RUN_SECOND = 30
COST_KEEP_FREE = 1

# Start-up (first install, or restored cost data no longer current): fetch cost
# right away instead of waiting up to an hour for :05:30, unless that run is
# this close anyway.
STARTUP_COST_GRACE = timedelta(minutes=10)


def today_published(entries: list[dict], now: datetime) -> bool:
    """Whether cached price entries hold today's real prices, current hour included.

    Before publication Pstryk sends rows anyway: buy with price null, sell 0.0,
    both with tge_price null. Entries cached before tge_price was stored lack
    the key and count as published (the caller also applies the placeholder check).
    """
    day = now.strftime("%Y-%m-%d")
    hour = now.strftime("%Y-%m-%dT%H")
    published = [
        p for p in entries
        if p.get("start", "").startswith(day)
        and p.get("price") is not None
        and ("tge_price" not in p or p["tge_price"] is not None)
    ]
    return len(published) >= 20 and any(p["start"].startswith(hour) for p in published)


def tomorrow_fetch_due(has_tomorrow: bool, now: datetime) -> bool:
    """Whether a start-up with today's prices cached should still fetch, for tomorrow."""
    return not has_tomorrow and (now.hour, now.minute) >= TOMORROW_EXPECTED_FROM


def next_tomorrow_check(now: datetime) -> datetime:
    """The next check for tomorrow's prices strictly after `now`."""
    first = now.replace(hour=TOMORROW_FIRST_CHECK[0], minute=TOMORROW_FIRST_CHECK[1], second=0, microsecond=0)
    last = now.replace(hour=TOMORROW_LAST_CHECK[0], minute=TOMORROW_LAST_CHECK[1], second=0, microsecond=0)
    if now < first:
        return first
    minutes_since_first = int((now - first).total_seconds() // 60)
    check = first + timedelta(
        minutes=(minutes_since_first // TOMORROW_INTERVAL_MINUTES + 1) * TOMORROW_INTERVAL_MINUTES
    )
    if check <= last:
        return check
    return (now + timedelta(days=1)).replace(
        hour=TOMORROW_FIRST_CHECK[0], minute=TOMORROW_FIRST_CHECK[1], second=0, microsecond=0
    )


def next_cost_run(now: datetime) -> datetime:
    """The next :05:30 strictly after `now`, in `now`'s time zone.

    Counted in UTC: on the day clocks go back, local wall time would skip the
    repeated hour (Poland's offsets are whole hours, so :05:30 is the same).
    """
    now_utc = now.astimezone(timezone.utc)
    run = now_utc.replace(minute=COST_RUN_MINUTE, second=COST_RUN_SECOND, microsecond=0)
    if run <= now_utc:
        run += timedelta(hours=1)
    return run.astimezone(now.tzinfo)


def cost_run_allowed(now: datetime, has_tomorrow: bool) -> bool:
    return has_tomorrow or now.hour < 12


def cost_keep_free(now: datetime, has_tomorrow: bool) -> int:
    """Slots a cost run leaves free for a price request due within the hour."""
    if now.hour == 23 or (now.hour >= 11 and not has_tomorrow):
        return COST_KEEP_FREE
    return 0


def next_midnight_refresh(now: datetime) -> datetime:
    """The next 00:05 strictly after `now`."""
    run = now.replace(hour=MIDNIGHT_REFRESH[0], minute=MIDNIGHT_REFRESH[1], second=0, microsecond=0)
    if run <= now:
        run = (now + timedelta(days=1)).replace(
            hour=MIDNIGHT_REFRESH[0], minute=MIDNIGHT_REFRESH[1], second=0, microsecond=0
        )
    return run


def startup_cost_fetch_due(now: datetime, missing_periods) -> bool:
    """Whether a start-up with these cost periods missing should fetch now."""
    return bool(missing_periods) and next_cost_run(now) - now > STARTUP_COST_GRACE
