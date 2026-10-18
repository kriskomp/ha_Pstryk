import logging
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util
from .const import (
    DOMAIN,
    API_URL,
    UNIFIED_METRICS_ENDPOINT,
    SELL_HISTORY_START,
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_RETRY_DELAY
)
from .api_client import BudgetExhausted, PstrykAPIClient
from .price_policy import (
    COST_KEEP_FREE,
    cost_keep_free,
    cost_run_allowed,
    next_cost_run,
    startup_cost_fetch_due,
)

_LOGGER = logging.getLogger(__name__)

COST_DATA_STORE_VERSION = 1

# A saved period is restored only within the day, month or year it was fetched in.
PERIOD_FORMATS = {"daily": "%Y-%m-%d", "monthly": "%Y-%m", "yearly": "%Y", "history": "%Y"}

# The two cost requests and the periods each one feeds. "month" goes first: it
# feeds three periods and every total sensor, so it gets a lone free slot.
COST_PARTS = {"month": ("monthly", "yearly", "history"), "day": ("daily",)}
# A catch-up waits this long after the slot it needs frees.
CATCH_UP_MARGIN = timedelta(seconds=3)


def restorable_periods(saved, now):
    """The saved periods still current at `now` (local), as coordinator data."""
    restored = {}
    for period, fmt in PERIOD_FORMATS.items():
        entry = (saved or {}).get(period)
        if not isinstance(entry, dict) or not entry.get("data"):
            continue
        fetched = dt_util.parse_datetime(entry.get("fetched") or "")
        if fetched and dt_util.as_local(fetched).strftime(fmt) == now.strftime(fmt):
            restored[period] = entry["data"]
    return restored


class PstrykCostDataUpdateCoordinator(DataUpdateCoordinator):

    def __init__(self, hass: HomeAssistant, api_client: PstrykAPIClient, retry_attempts=None, retry_delay=None, entry_id=None):
        self.api_client = api_client
        self.entry_id = entry_id
        self._unsub_hourly = None
        self._unsub_midnight = None
        self._unsub_catch_up = None
        # Parts the budget refused in the last run: {part: when a slot frees}.
        self._blocked = {}
        # Set by sensor.py: cost waits until these have tomorrow's prices.
        self.price_coordinators = []
        # Slots each cost request leaves free for prices; set per run.
        self._keep_free = COST_KEEP_FREE
        # The last data fetched per period, kept across restarts: cost runs only
        # at :05:30 on leftover budget, so the sensors would otherwise stay empty
        # for up to an hour after every restart.
        self._store = Store(hass, COST_DATA_STORE_VERSION, f"{DOMAIN}_cost_data")
        self._saved = {}

        if retry_attempts is None:
            retry_attempts = DEFAULT_RETRY_ATTEMPTS
        if retry_delay is None:
            retry_delay = DEFAULT_RETRY_DELAY

        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_cost",
        )

    async def _async_update_data(self, parts=("month", "day")):
        """Fetch the given cost parts. A part the budget refuses is recorded in
        self._blocked (normal, not an error); BudgetExhausted is raised only when
        every part was refused and nothing was fetched."""
        _LOGGER.debug("Starting energy cost and usage data fetch: %s", list(parts))
        self._blocked = {}

        try:
            now = dt_util.now()

            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start = today_start - timedelta(days=1)
            day_after_tomorrow = today_start + timedelta(days=2)

            year_start = today_start.replace(month=1, day=1)
            next_year_start = year_start.replace(year=now.year + 1)

            format_time = lambda dt: dt_util.as_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")

            data = {}
            failed = []

            async def fetch(part, url):
                try:
                    return await self.api_client.fetch(
                        url,
                        max_retries=self.retry_attempts,
                        base_delay=self.retry_delay,
                        keep_free=self._keep_free
                    )
                except BudgetExhausted as e:
                    self._blocked[part] = e.free_at
                    _LOGGER.info("Cost data (%s) waits for the API limit: %s", part, e)
                except UpdateFailed as e:
                    failed.append(part)
                    _LOGGER.warning("Failed to fetch cost data (%s): %s", part, e)
                return None

            for part in ("month", "day"):
                if part not in parts:
                    continue
                if part == "month":
                    # One request covers the current year and the whole sell history:
                    # the window starts at SELL_HISTORY_START instead of 1 January.
                    y, m, d = SELL_HISTORY_START
                    history_start = min(year_start, today_start.replace(year=y, month=m, day=d))
                    url = API_URL + UNIFIED_METRICS_ENDPOINT.format(
                        resolution="month",
                        start=format_time(history_start),
                        end=format_time(next_year_start),
                    )
                    yearly_data = await fetch(part, url)
                    if yearly_data:
                        current_year = self._frames_of_year(yearly_data, now.year)
                        data["yearly"] = self._process_yearly_data_simple(current_year)
                        data["monthly"] = self._process_monthly_data_simple(current_year)
                        data["history"] = self._process_sell_history(yearly_data)
                else:
                    url = API_URL + UNIFIED_METRICS_ENDPOINT.format(
                        resolution="day",
                        start=format_time(yesterday_start),
                        end=format_time(day_after_tomorrow),
                    )
                    daily_data = await fetch(part, url)
                    if daily_data:
                        data["daily"] = self._process_daily_data_simple(daily_data)

            if data:
                _LOGGER.debug("Fetched energy cost and usage data for: %s", list(data.keys()))
                return data
            if self._blocked and not failed:
                free_at = min((t for t in self._blocked.values() if t), default=None)
                raise BudgetExhausted("unified-metrics", free_at)
            raise UpdateFailed("Failed to fetch energy cost data for any resolution")

        except BudgetExhausted:
            raise
        except Exception as err:
            _LOGGER.error("Error fetching energy cost data: %s", err, exc_info=True)
            raise UpdateFailed(f"Error fetching energy cost data: {err}")

    def _normalize_frame(self, frame):
        metrics = frame.get("metrics", {})
        meter_values = metrics.get("meter_values") or metrics.get("meterValues") or {}
        cost = metrics.get("cost") or {}

        return {
            "start": frame.get("start"),
            "end": frame.get("end"),
            "is_live": frame.get("is_live", False),
            "fae_usage": frame.get("fae_usage", meter_values.get("energy_active_import_register", 0) or 0),
            "rae": frame.get("rae", meter_values.get("energy_active_export_register", 0) or 0),
            "energy_balance": frame.get("energy_balance", meter_values.get("energy_balance", 0) or 0),
            "fae_cost": frame.get(
                "fae_cost",
                cost.get("energy_import_cost", cost.get("energy_active_import_register_cost", 0) or 0),
            ),
            "var_dist_cost_net": frame.get("var_dist_cost_net", cost.get("var_dist_cost_net", 0) or 0),
            "fix_dist_cost_net": frame.get("fix_dist_cost_net", cost.get("fix_dist_cost_net", 0) or 0),
            "energy_cost_net": frame.get(
                "energy_cost_net",
                cost.get("energy_cost_net", cost.get("energy_import_cost", 0) or 0),
            ),
            "service_cost_net": frame.get("service_cost_net", cost.get("service_cost_net", 0) or 0),
            "power_fee_cost_net": frame.get("power_fee_cost_net", cost.get("power_fee_cost_net", 0) or 0),
            "excise": frame.get("excise", cost.get("excise", 0) or 0),
            "vat": frame.get("vat", cost.get("vat", 0) or 0),
            "energy_sold_value": frame.get(
                "energy_sold_value",
                cost.get("energy_sold_value", cost.get("energy_active_export_register_value", 0) or 0),
            ),
            "energy_balance_value": frame.get(
                "energy_balance_value",
                cost.get("energy_balance_value", 0) or 0,
            ),
        }

    def _normalized_frames(self, response):
        return [self._normalize_frame(frame) for frame in response.get("frames", [])]

    def _frames_of_year(self, response, year):
        """The response limited to frames starting in the given local year."""
        def local_year(frame):
            parsed = dt_util.parse_datetime(frame.get("start") or "")
            return dt_util.as_local(parsed).year if parsed else None
        return {**response,
                "frames": [f for f in response.get("frames", []) if local_year(f) == year]}

    def _process_sell_history(self, response):
        """Real totals per local year: sold/bought energy (kWh), sell revenue and buy cost (PLN)."""
        years = {}
        for frame in self._normalized_frames(response):
            parsed = dt_util.parse_datetime(frame.get("start") or "")
            if not parsed:
                continue
            year = str(dt_util.as_local(parsed).year)
            entry = years.setdefault(year, {"sell_revenue": 0.0, "energy_sold": 0.0,
                                            "buy_cost": 0.0, "energy_bought": 0.0})
            entry["sell_revenue"] += frame.get("energy_sold_value", 0) or 0
            entry["energy_sold"] += frame.get("rae", 0) or 0
            # Same sum as the yearly total_cost / fae_usage of the current year.
            entry["buy_cost"] += abs(frame.get("fae_cost", 0) or 0)
            entry["energy_bought"] += frame.get("fae_usage", 0) or 0
        for entry in years.values():
            for key in ("sell_revenue", "buy_cost"):
                entry[key] = round(entry[key], 2)
            for key in ("energy_sold", "energy_bought"):
                entry[key] = round(entry[key], 3)
        _LOGGER.info("Sell history loaded: %s", years)
        return {"years": dict(sorted(years.items())),
                "fetched_at": dt_util.now().isoformat()}

    def _process_monthly_data_simple(self, response):
        _LOGGER.info("Processing monthly data - simple version")

        result = {
            "frame": {},
            "total_balance": 0,
            "total_sold": 0,
            "total_cost": 0,
            "fae_usage": 0,
            "rae_usage": 0
        }

        frames = self._normalized_frames(response)

        current_month = dt_util.now().strftime("%Y-%m")

        def frame_month(f):
            parsed = dt_util.parse_datetime(f.get("start") or "")
            return dt_util.as_local(parsed).strftime("%Y-%m") if parsed else ""

        frame = next(
            (f for f in frames if frame_month(f) == current_month),
            frames[-1] if frames else None,
        )

        if frame:
            result["frame"] = frame
            result["total_balance"] = frame.get("energy_balance_value", 0)
            result["total_sold"] = frame.get("energy_sold_value", 0)
            result["total_cost"] = abs(frame.get("fae_cost", 0))
            result["fae_usage"] = frame.get("fae_usage", 0)
            result["rae_usage"] = frame.get("rae", 0)
            _LOGGER.info(f"Monthly data from frame {frame.get('start')}: balance={result['total_balance']}, "
                        f"sold={result['total_sold']}, cost={result['total_cost']}, "
                        f"fae={result['fae_usage']}, rae={result['rae_usage']}")

        return result

    def _process_daily_data_simple(self, response):
        _LOGGER.info("=== SIMPLE DAILY DATA PROCESSOR ===")

        result = {
            "frame": {},
            "total_balance": 0,
            "total_sold": 0,
            "total_cost": 0,
            "fae_usage": 0,
            "rae_usage": 0
        }

        live_date = None

        frames = self._normalized_frames(response)

        if frames:
            _LOGGER.info(f"Processing {len(frames)} unified metric frames")

            for i, frame in enumerate(frames):
                _LOGGER.info(f"Frame {i}: start={frame.get('start')}, "
                           f"is_live={frame.get('is_live', False)}, "
                           f"fae_usage={frame.get('fae_usage')}, "
                           f"rae={frame.get('rae')}")

                if frame.get("is_live", False):
                    result["fae_usage"] = frame.get("fae_usage", 0)
                    result["rae_usage"] = frame.get("rae", 0)
                    _LOGGER.info(f"*** FOUND LIVE FRAME: fae_usage={result['fae_usage']}, rae={result['rae_usage']} ***")

                    live_start = frame.get("start")
                    if live_start:
                        live_date = live_start.split("T")[0]
                        _LOGGER.info(f"Live frame date: {live_date}")
                    break

        if live_date:
            _LOGGER.info(f"Looking for matching frame date: {live_date}")

            for frame in frames:
                frame_start = frame.get("start", "")
                frame_date = frame_start.split("T")[0] if frame_start else ""

                _LOGGER.info(f"Checking cost frame: start={frame_start}, date={frame_date}, "
                           f"balance={frame.get('energy_balance_value', 0)}, "
                           f"cost={frame.get('fae_cost', 0)}")

                if frame_date == live_date:
                    result["frame"] = frame
                    result["total_balance"] = frame.get("energy_balance_value", 0)
                    result["total_sold"] = frame.get("energy_sold_value", 0)
                    result["total_cost"] = abs(frame.get("fae_cost", 0))
                    _LOGGER.info(f"*** MATCHED cost frame for date {live_date}: balance={result['total_balance']}, "
                               f"cost={result['total_cost']}, sold={result['total_sold']} ***")
                    break
            else:
                _LOGGER.warning(f"No unified metrics frame found matching live date {live_date}")
        elif not live_date:
            _LOGGER.warning("No live frame found in unified metrics data, cannot match daily frame")

        _LOGGER.info(f"=== FINAL RESULT: fae_usage={result['fae_usage']}, "
                    f"rae_usage={result['rae_usage']}, "
                    f"balance={result['total_balance']}, "
                    f"cost={result['total_cost']}, "
                    f"sold={result['total_sold']} ===")
        return result

    def _process_yearly_data_simple(self, response):
        _LOGGER.info("Processing yearly data - simple version")

        total_balance = 0
        total_sold = 0
        total_cost = 0
        fae_usage = 0
        rae_usage = 0

        frames = self._normalized_frames(response)

        if frames:
            for frame in frames:
                total_balance += frame.get("energy_balance_value", 0)
                total_sold += frame.get("energy_sold_value", 0)
                total_cost += abs(frame.get("fae_cost", 0))
            _LOGGER.info(f"Yearly cost totals: balance={total_balance}, "
                        f"sold={total_sold}, cost={total_cost}")

        if frames:
            for frame in frames:
                fae_usage += frame.get("fae_usage", 0)
                rae_usage += frame.get("rae", 0)
            _LOGGER.info(f"Yearly usage totals: fae={fae_usage}, rae={rae_usage}")

        return {
            "frame": {},
            "total_balance": total_balance,
            "total_sold": total_sold,
            "total_cost": total_cost,
            "fae_usage": fae_usage,
            "rae_usage": rae_usage
        }

    async def async_restore(self):
        """Serve the last saved data until the next cost run. Sends no request."""
        try:
            self._saved = await self._store.async_load() or {}
        except Exception as err:
            _LOGGER.warning("Failed to load saved cost data: %s", err)
            self._saved = {}
        # Like the price cache: the store outlives its entry, and an entry added
        # later may belong to another account.
        if self._saved and self._saved.get("owner") != self.entry_id:
            _LOGGER.info("Saved cost data was written by another entry; not using it")
            self._saved = {}
        restored = restorable_periods(self._saved, dt_util.now())
        if restored:
            self.data = restored
            self.last_update_success = True
            _LOGGER.debug("Restored cost data for %s", sorted(restored))

    async def _async_save(self, data):
        fetched = dt_util.utcnow().isoformat()
        self._saved["owner"] = self.entry_id
        for period, period_data in data.items():
            self._saved[period] = {"fetched": fetched, "data": period_data}
        try:
            await self._store.async_save(self._saved)
        except Exception as err:
            _LOGGER.warning("Failed to save cost data: %s", err)

    def schedule_hourly_update(self):
        if self._unsub_hourly:
            self._unsub_hourly()
            self._unsub_hourly = None

        # Prices come first. Cost runs every hour at :05:30, after the price
        # requests of :05:00, on the budget the prices don't need.
        next_run = next_cost_run(dt_util.now())

        _LOGGER.debug("Scheduling next cost update at %s",
                     next_run.strftime("%Y-%m-%d %H:%M:%S"))

        self._unsub_hourly = async_track_point_in_time(
            self.hass, self._handle_hourly_update, dt_util.as_utc(next_run)
        )

    def _period_current(self, period, now) -> bool:
        """Whether `period` holds data fetched within its own day, month or year."""
        if period not in (self.data or {}):
            return False
        fetched = dt_util.parse_datetime(((self._saved or {}).get(period) or {}).get("fetched") or "")
        if not fetched:
            return False
        fmt = PERIOD_FORMATS[period]
        return dt_util.as_local(fetched).strftime(fmt) == now.strftime(fmt)

    def missing_parts(self, now=None) -> list:
        """Cost parts whose periods have no current data (sensors would be unavailable)."""
        now = now or dt_util.now()
        return [part for part, periods in COST_PARTS.items()
                if not all(self._period_current(p, now) for p in periods)]

    async def _async_run(self, parts, keep_free, reason) -> str:
        """One cost fetch of `parts`; then a catch-up for parts still missing."""
        self._keep_free = keep_free
        try:
            data = await self._async_update_data(parts)
        except BudgetExhausted:
            data = {}
        except Exception as err:
            _LOGGER.error("Cost update (%s) failed: %s - next try at :05:30", reason, err)
            if not self.data:
                self.last_update_success = False  # nothing to show; data kept otherwise
            self._schedule_catch_up()
            return "failed"
        if data:
            self.data = {**(self.data or {}), **data}
            self.last_update_success = True
            self.async_update_listeners()
            await self._async_save(data)
        self._schedule_catch_up()
        if not data:
            return "budget"
        return "partial" if self._blocked else "fetched"

    def _cancel_catch_up(self):
        if self._unsub_catch_up:
            self._unsub_catch_up()
            self._unsub_catch_up = None

    def _schedule_catch_up(self):
        """A one-off fetch, when the budget frees, of parts with no current data.

        Only for missing data (first install, restart after a long stop): a part
        that still has current data waits for the regular :05:30 run, so
        catch-ups never become an hourly habit that eats the next run's slots.
        """
        self._cancel_catch_up()
        now = dt_util.now()
        waiting = [p for p in self.missing_parts(now) if self._blocked.get(p)]
        if not waiting:
            return
        run_at = min(self._blocked[p] for p in waiting) + CATCH_UP_MARGIN
        # A regular run before it reschedules or cancels it (see _async_run).
        _LOGGER.info("Cost data (%s) will be fetched at %s, when the API limit frees",
                     ", ".join(waiting), dt_util.as_local(run_at).strftime("%H:%M:%S"))
        self._unsub_catch_up = async_track_point_in_time(
            self.hass, self._handle_catch_up, dt_util.as_utc(run_at)
        )

    async def _handle_catch_up(self, _):
        self._unsub_catch_up = None
        now = dt_util.now()
        parts = self.missing_parts(now)
        if not parts:
            return
        tomorrow = all(c._has_tomorrow for c in self.price_coordinators)
        await self._async_run(parts, cost_keep_free(now, tomorrow), "catch-up")

    def _block_all_until_free(self, keep_free):
        free_at = self.api_client.budget_free_at(keep_free=keep_free)
        self._blocked = {part: free_at for part in COST_PARTS} if free_at else {}

    async def async_startup_refresh(self) -> str:
        """Fetch cost at start-up when the restored data does not cover every period.

        After a first install (nothing saved) or a long stop (a new day, month or
        year), the cost sensors would stay unavailable until the next :05:30.
        Runs after the price start-up and only on budget the prices leave free;
        what the budget refuses is caught up as soon as a slot frees.
        """
        now = dt_util.now()
        missing = self.missing_parts(now)
        if not missing:
            _LOGGER.debug("Cost data restored for every period; next update at :05:30")
            return "restored"
        if not startup_cost_fetch_due(now, missing):
            _LOGGER.debug("Cost data missing (%s); the :05:30 update is close", missing)
            return "next_run_soon"
        tomorrow = all(c._has_tomorrow for c in self.price_coordinators)
        keep_free = cost_keep_free(now, tomorrow)
        if not self.api_client.budget_room_soon(keep_free=keep_free):
            self._block_all_until_free(keep_free)
            self._schedule_catch_up()
            return "budget"
        _LOGGER.info("Cost data missing (%s); fetching now (start-up)", ", ".join(missing))
        return await self._async_run(missing, keep_free, "start-up")

    async def _handle_hourly_update(self, now):
        local_now = dt_util.now()
        tomorrow = all(c._has_tomorrow for c in self.price_coordinators)
        if not cost_run_allowed(local_now, tomorrow):
            _LOGGER.debug("Skipping cost update at %s: prices first", local_now.strftime("%H:%M"))
            self.schedule_hourly_update()
            return
        keep_free = cost_keep_free(local_now, tomorrow)
        try:
            if not self.api_client.budget_room_soon(keep_free=keep_free):
                _LOGGER.info("Cost update at %s waits for the API limit", local_now.strftime("%H:%M"))
                self._block_all_until_free(keep_free)
                self._schedule_catch_up()
                return
            _LOGGER.debug("Triggering cost update")
            await self._async_run(tuple(COST_PARTS), keep_free, "hourly")
        finally:
            self.schedule_hourly_update()
            return
        self._keep_free = cost_keep_free(local_now, tomorrow)
        if not self.api_client.budget_room_soon(keep_free=self._keep_free):
            _LOGGER.debug("Skipping cost update at %s: API budget kept for prices", local_now.strftime("%H:%M"))
            self.schedule_hourly_update()
            return

        _LOGGER.debug("Triggering cost update")
        try:
            data = await self._async_update_data()
            self.data = {**(self.data or {}), **data}
            self.last_update_success = True
            self.async_update_listeners()
            await self._async_save(data)
        except Exception as err:
            _LOGGER.error("Hourly cost update failed: %s - will retry next hour", err)
            self.last_update_success = False
        finally:
            self.schedule_hourly_update()
