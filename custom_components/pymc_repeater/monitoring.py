"""Conservative monitoring normalization independent of Home Assistant."""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from time import time
from typing import Any


def finite_number(value: Any) -> float | None:
    """Reject booleans, nonnumeric values and nonfinite measurements."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def reading_age(reading: dict, *, now: float | None = None) -> float | None:
    """Return source age; absent, naive or future timestamps are unknown."""
    value = reading.get("timestamp")
    stamp = finite_number(value)
    if stamp is None and isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            stamp = parsed.timestamp()
        except (ValueError, OverflowError):
            return None
    if stamp is None or stamp <= 0:
        return None
    age = (time() if now is None else now) - stamp
    return round(age, 1) if age >= 0 else None


def reading_stale(reading: dict, interval: Any, *, now: float | None = None) -> bool | None:
    """Allow three source polling intervals, with a 60-second minimum."""
    age = reading_age(reading, now=now)
    cadence = finite_number(interval)
    if age is None or cadence is None or cadence <= 0:
        return None
    return age > max(60, cadence * 3)


def reading_usable(reading: dict, interval: Any, *, now: float | None = None) -> bool:
    """Never expose cached measurements as fresh without source evidence."""
    return reading.get("ok") is True and reading_stale(reading, interval, now=now) is False


RADIO_FIELDS = ("frequency", "tx_power", "bandwidth", "spreading_factor", "coding_rate", "preamble_length")


def charge_state(reading: dict, interval: Any, *, now: float | None = None) -> str | None:
    """Describe battery trend, not charger hardware or a full-battery claim."""
    if not reading_usable(reading, interval, now=now):
        return None
    payload = reading.get("data")
    rate = finite_number(payload.get("solar_charge_rate_percent_per_hour")) if isinstance(payload, dict) else None
    if rate is None:
        return None
    return "charging" if rate > 0 else "discharging" if rate < 0 else "neutral"


def plugin_problem(plugin: dict) -> bool | None:
    """UI-only/disabled plugins need no process; transition states are unknown."""
    if plugin.get("enabled") is False or plugin.get("has_runtime") is False:
        return False
    if plugin.get("enabled") is not True or plugin.get("has_runtime") is not True:
        return None
    state = plugin.get("state")
    if state in ("FAILED", "STOPPED"):
        return True
    if state == "RUNNING":
        return False
    return None


def radio_inventory(data: dict) -> dict[str, dict]:
    """Expose allowlisted radio configuration, not aggregate health or traffic.

    Installed /api/stats radios[] is configuration, NOT per-radio telemetry.
    """
    stats = data.get("stats")
    if not isinstance(stats, dict) or stats.get("error"):
        return {}
    stack = stats.get("radio_stack")
    stack = stack if isinstance(stack, dict) else {}
    ids = stack.get("radio_ids")
    result = {rid: {} for rid in ids if isinstance(rid, str) and rid} if isinstance(ids, list) else {}
    rows = stats.get("radios")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        rid = row.get("id") or row.get("radio_id")
        if not isinstance(rid, str) or not rid:
            continue
        result.setdefault(rid, {})
        if isinstance(row.get("type"), str):
            result[rid]["type"] = row["type"]
        settings = row.get("radio")
        if isinstance(settings, dict):
            for field in RADIO_FIELDS:
                value = finite_number(settings.get(field))
                if value is not None:
                    result[rid][field] = value
    # Legacy single-radio configuration is global, but belongs only to the
    # explicitly named default. Never copy global configuration across a fabric.
    default = stack.get("default_radio")
    config = data.get("config")
    if (stack.get("mode") == "single" and len(result) == 1 and isinstance(default, str) and default in result
            and isinstance(config, dict) and not config.get("error")):
        settings = config.get("radio")
        if isinstance(settings, dict):
            for field in RADIO_FIELDS:
                value = finite_number(settings.get(field))
                if value is not None:
                    result[default].setdefault(field, value)
    return result


def measurement_class(field: str) -> str | None:
    """Only classify measured fields with known physical units."""
    if field in ("battery_percent", "battery_percentage"):
        return "battery"
    if field.endswith(("voltage_v", "voltage_mv")):
        return "voltage"
    if field.endswith(("current_ma", "current_a")):
        return "current"
    if field.endswith(("power_mw", "power_w")):
        return "power"
    if field.endswith(("temperature_c", "temperature_f")):
        return "temperature"
    return None
