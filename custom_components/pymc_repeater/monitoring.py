"""Conservative monitoring normalization independent of Home Assistant."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
import json
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


def parse_radio_aliases(value: Any, *, radio_ids: Iterable[str] = ()) -> dict[str, str]:
    """Validate explicit runtime-ID -> HA-ID aliases without normalizing IDs.

    Chains (including self aliases/cycles), duplicate keys/targets, and alias
    pairs whose source and target are both declared at runtime are rejected.
    Empty objects disable aliasing; invalid persisted values must fail closed.
    """
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, target in pairs:
            if key in result:
                raise ValueError("Duplicate radio alias source")
            result[key] = target
        return result

    if isinstance(value, str):
        try:
            value = json.loads(value, object_pairs_hook=unique_object)
        except (ValueError, RecursionError) as err:
            raise ValueError("Invalid radio alias JSON") from err
    if not isinstance(value, dict):
        raise ValueError("Radio aliases must be an object")
    for source, target in value.items():
        for identity in (source, target):
            if (not isinstance(identity, str) or not identity or not identity.isprintable()
                    or any(char.isspace() for char in identity)):
                raise ValueError("Radio IDs must be nonempty strings without whitespace")
    targets = set(value.values())
    if len(targets) != len(value) or targets.intersection(value):
        raise ValueError("Radio aliases must be one-to-one without chains or cycles")
    occupied = set(radio_ids)
    if any(source in occupied and target in occupied for source, target in value.items()):
        raise ValueError("Radio alias source and target are both runtime IDs")
    return dict(value)


_NO_RADIO_ALIASES = object()


def radio_source_ids(data: dict) -> set[str]:
    """Return all declared runtime IDs, including ambiguous rows, for safety."""
    stats = data.get("stats")
    if not isinstance(stats, dict):
        return set()
    stack = stats.get("radio_stack")
    ids = stack.get("radio_ids") if isinstance(stack, dict) else None
    result = {rid for rid in ids if isinstance(rid, str) and rid} if isinstance(ids, list) else set()
    rows = stats.get("radios")
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            result.update(value for key in ("id", "radio_id")
                          if isinstance(value := row.get(key), str) and value)
    return result


def radio_inventory(data: dict, aliases: Any = _NO_RADIO_ALIASES) -> dict[str, dict]:
    """Expose allowlisted radio configuration, not aggregate health or traffic.

    Installed /api/stats radios[] is configuration, NOT per-radio telemetry.
    """
    stats = data.get("stats")
    if not isinstance(stats, dict) or stats.get("error") or stats.get("success") is False:
        return {}
    stack = stats.get("radio_stack")
    stack = stack if isinstance(stack, dict) else {}
    ids = stack.get("radio_ids")
    result: dict[str, dict] = {}
    ambiguous = set()
    for rid in ids if isinstance(ids, list) else []:
        if not isinstance(rid, str) or not rid:
            continue
        if rid in result:
            ambiguous.add(rid)
        result[rid] = {}
    rows = stats.get("radios")
    seen_rows = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if "id" in row and "radio_id" in row and row["id"] != row["radio_id"]:
            ambiguous.update(value for value in (row["id"], row["radio_id"]) if isinstance(value, str))
            continue
        rid = row.get("id") or row.get("radio_id")
        if not isinstance(rid, str) or not rid:
            continue
        if rid in seen_rows:
            ambiguous.add(rid)
            continue
        seen_rows.add(rid)
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
    config = stats.get("config")
    if (stack.get("mode") == "single" and len(result) == 1 and isinstance(default, str) and default in result
            and isinstance(config, dict) and not config.get("error")):
        settings = config.get("radio")
        if isinstance(settings, dict):
            for field in RADIO_FIELDS:
                value = finite_number(settings.get(field))
                if value is not None:
                    result[default].setdefault(field, value)
    try:
        mapping = parse_radio_aliases({} if aliases is _NO_RADIO_ALIASES else aliases)
    except ValueError:
        return {}
    # An explicit alias joins two alternate names for the same identity. The
    # canonical name remains valid when the alias source disappears (for example
    # multi -> single mode). Only simultaneous declarations are a collision;
    # include malformed/ambiguous rows so they cannot bypass that protection.
    occupied = radio_source_ids(data)
    conflicts = {
        rid for source, target in mapping.items()
        if source in occupied and target in occupied
        for rid in (source, target)
    }
    return {
        mapping.get(rid, rid): radio for rid, radio in result.items()
        if rid not in ambiguous and rid not in conflicts
    }


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
