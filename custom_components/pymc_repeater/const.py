"""Constants for the openHop Repeater integration."""

from datetime import timedelta

DOMAIN = "pymc_repeater"
PLATFORMS = ["sensor", "binary_sensor"]

CONF_API_TOKEN = "api_token"
CONF_TOKEN_ID = "token_id"
CONF_TOKEN_NAME = "token_name"
CONF_DATA_SIZE_UNIT = "data_size_unit"
CONF_UPTIME_UNIT = "uptime_unit"

DEFAULT_PORT = 8000
DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)
DEFAULT_DATA_SIZE_UNIT = "mebibytes"
DEFAULT_PACKET_WINDOW_HOURS = 24
DEFAULT_UPTIME_UNIT = "hours"

MANUFACTURER = "openHop"
MODEL = "openHop Repeater"

CLIENT_ID_PREFIX = "home-assistant"

DATA_SIZE_UNITS = ("bytes", "kibibytes", "mebibytes", "gibibytes")
UPTIME_UNITS = ("seconds", "minutes", "hours", "days")
