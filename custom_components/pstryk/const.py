
DOMAIN = "pstryk"
API_URL = "https://api.pstryk.pl/integrations/"
API_TIMEOUT = 60
# pstryk.pl/regulamin-api: 3 requests/hour per endpoint. Prices and costs share one endpoint.
API_HOURLY_LIMIT = 3
REQUEST_LOG_STORE_VERSION = 1
# A slot is counted from the moment its request is sent and frees this long
# after the hour: we time the send, Pstryk times the arrival.
API_WINDOW_MARGIN_SECONDS = 2
# A request that finds the budget full waits this long for a slot to free.
# Checks repeat on the hour, so last hour's request leaves the window a moment
# after the timer fires; each hour on the limit starts the margin later, and
# 30 s covers the longest run (12:05 to 23:45).
API_SLOT_WAIT_SECONDS = 30

PRICING_ENDPOINT = (
    "meter-data/unified-metrics/?metrics=pricing"
    "&resolution=hour&window_start={start}&window_end={end}"
)

UNIFIED_METRICS_ENDPOINT = (
    "meter-data/unified-metrics/?metrics=meter_values,cost"
    "&resolution={resolution}&window_start={start}&window_end={end}&for_tz=Europe/Warsaw"
)

# Earliest date for the all-time sell revenue history (Pstryk market start).
# Months before a customer's contract are returned by the API as zeros.
SELL_HISTORY_START = (2024, 10, 1)

ATTR_BUY_PRICE = "buy_price"
ATTR_SELL_PRICE = "sell_price"
ATTR_HOURS = "hours"

DEFAULT_MQTT_TOPIC_BUY = "energy/forecast/buy"
DEFAULT_MQTT_TOPIC_SELL = "energy/forecast/sell"
CONF_MQTT_ENABLED = "mqtt_enabled"
CONF_MQTT_TOPIC_BUY = "mqtt_topic_buy"
CONF_MQTT_TOPIC_SELL = "mqtt_topic_sell"
CONF_MQTT_48H_MODE = "mqtt_48h_mode"
CONF_JSON_SENSOR = "json_sensor_enabled"

# Sell-side entities (revenue, energy sold, sell averages) of someone who does
# not sell energy are only noise; see prosumer.py. "auto" disables them while no
# sale has ever been seen and shows them again on the first one.
CONF_PROSUMER_ENTITIES = "prosumer_entities"
PROSUMER_AUTO = "auto"
PROSUMER_SHOW = "show"
PROSUMER_DISABLE = "disable"
DEFAULT_PROSUMER_ENTITIES = PROSUMER_AUTO
# unique_id of the entities that only describe selling (checked against the real
# sensors by the tests). migrate.py leaves them to prosumer.py.
SELL_UNIQUE_IDS = tuple(
    [f"pstryk_sell_revenue_{p}" for p in ("daily", "monthly", "yearly", "total")]
    + [f"pstryk_energy_sold_{p}" for p in ("daily", "monthly", "yearly", "total")]
    + [f"pstryk_sell_{p}_average" for p in ("daily", "monthly", "yearly", "total")]
)

CONF_RETRY_ATTEMPTS = "retry_attempts"
CONF_RETRY_DELAY = "retry_delay"
# Attempts per request, the first one included. Every attempt is one of the
# API_HOURLY_LIMIT requests an hour that prices and costs share, so more than
# that can never be sent, and a failing API would spend the whole hour on
# retries. Two (one retry) leaves a slot for the next job.
DEFAULT_RETRY_ATTEMPTS = 2
DEFAULT_RETRY_DELAY = 30
MIN_RETRY_ATTEMPTS = 1
MAX_RETRY_ATTEMPTS = API_HOURLY_LIMIT
MIN_RETRY_DELAY = 5
MAX_RETRY_DELAY = 300

# Migration from Pstryk AiO (szkocot/Pstryk-all-in-one), 2.3.0.
AIO_DOMAIN = "pstryk_aio"
CONF_MIGRATE_FROM = "migrate_from"  # entry_id of the AiO entry; removed once done
CONF_AIO_ACTION = "aio_action"
AIO_ACTION_DISABLE = "disable"
AIO_ACTION_REMOVE = "remove"
ISSUE_MIGRATED = "migrated_from_aio"


def retry_attempts_setting(value) -> int:
    """The attempts to use for a stored setting.

    Up to 2.2.x the limit of the setting was 10 and the default 5, but only
    API_HOURLY_LIMIT requests an hour can be sent, so a stored larger value is
    used as the largest meaningful one (the extra attempts only waited for a
    slot that could not come). Anything unusable gives the default.
    """
    try:
        return max(MIN_RETRY_ATTEMPTS, min(MAX_RETRY_ATTEMPTS, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_RETRY_ATTEMPTS


def prosumer_setting(value) -> str:
    """A stored "prosumer_entities" option, or the default if it is missing or unknown."""
    return value if value in (PROSUMER_AUTO, PROSUMER_SHOW, PROSUMER_DISABLE) else DEFAULT_PROSUMER_ENTITIES
