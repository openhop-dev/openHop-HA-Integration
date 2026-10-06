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
    """Allow three source intervals, with a 60-second minimum.

    The reading envelope's poll_interval_seconds is the backend scheduler's
    effective cadence, including plugin defaults/overrides. ``interval`` is
    only the legacy global-summary fallback when that metadata is absent;
    it cannot establish a legacy plugin's actual cadence. Present but invalid
    metadata is unknown, not permission to substitute the global interval.
    """
    age = reading_age(reading, now=now)
    cadence = finite_number(reading.get("poll_interval_seconds", interval))
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
        radio_type = row.get("radio_type")
        if not isinstance(radio_type, str):
            radio_type = row.get("type")
        if isinstance(radio_type, str):
            result[rid]["type"] = radio_type
        settings = row.get("radio")
        if isinstance(settings, dict):
            for field in RADIO_FIELDS:
                value = finite_number(settings.get(field))
                if value is not None:
                    result[rid][field] = value
    # Legacy single-radio configuration is global, but belongs only to the
    # explicitly named sole default, including a single physical radio wrapped
    # by the fabric. Validate raw topology before normalization hides bad rows.
    default = stack.get("default_radio")
    config = stats.get("config")
    fallback_rows = stats.get("radios", [])
    valid_rows = isinstance(fallback_rows, list) and all(
        isinstance(row, dict)
        and row.get("id", row.get("radio_id")) == default
        and ("radio_id" not in row or row["radio_id"] == default)
        and not row.get("error") and row.get("success") is not False
        and isinstance(row.get("radio", {}), dict)
        and not row.get("radio", {}).get("error")
        and row.get("radio", {}).get("success") is not False
        for row in fallback_rows
    )
    if (stack.get("mode") in ("single", "single_fabric")
            and isinstance(default, str) and default and default.isprintable()
            and not any(char.isspace() for char in default)
            and ids == [default] and set(result) == {default} and not ambiguous
            and valid_rows and not stack.get("error") and stack.get("success") is not False
            and isinstance(config, dict) and not config.get("error") and config.get("success") is not False):
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


# Sliding windows and current shared channel budgets are measurements, not
# lifetime counters. Keep ledger values on each child; never sum them here.
RADIO_TELEMETRY: dict[str, tuple[str, str | None]] = {
    "channel_utilization": ("Channel utilization", "%"),
    "current_channel_airtime": ("Current channel airtime", "ms"),
    "max_channel_airtime": ("Maximum channel airtime", "ms"),
    "noise_floor": ("Cached noise floor", "dBm"),
}
for _window in ("1h", "24h"):
    for _field, _name, _unit in (
        ("received", "Packets received", None),
        ("duplicates", "Duplicate packets", None),
        ("transmissions", "Physical transmissions", None),
        ("avg_rssi", "Average RSSI", "dBm"),
        ("avg_snr", "Average SNR", "dB"),
    ):
        RADIO_TELEMETRY[f"{_field}_{_window}"] = (f"{_name} ({_window})", _unit)
for _field, _name, _unit in (
    ("total_transmissions", "LBT transmissions", None),
    ("retry_packets", "LBT retry packets", None),
    ("retry_rate_pct", "LBT retry rate", "%"),
    ("avg_attempts", "LBT average attempts", None),
    ("p95_attempts", "LBT p95 attempts", None),
    ("max_attempts", "LBT maximum attempts", None),
    ("failed_transmissions", "LBT failed transmissions", None),
    ("busy_channel_events", "LBT busy channel events", None),
    ("severe_contention_count", "LBT severe contention count", None),
    ("severe_contention_pct", "LBT severe contention rate", "%"),
):
    RADIO_TELEMETRY[f"lbt_{_field}_24h"] = (f"{_name} (24h)", _unit)

LBT_RADIO_FIELDS = (
    "total_transmissions", "retry_packets", "retry_rate_pct", "avg_attempts",
    "p95_attempts", "max_attempts", "failed_transmissions", "busy_channel_events",
    "severe_contention_count", "severe_contention_pct",
)


def radio_telemetry(data: dict, aliases: Any = _NO_RADIO_ALIASES) -> dict[str, dict]:
    """Expose only finite child summary scalars from already-polled endpoints."""
    inventory = radio_inventory(data, aliases)
    result: dict[str, dict] = {rid: {} for rid in inventory}
    if not inventory:
        return result
    mapping = parse_radio_aliases({} if aliases is _NO_RADIO_ALIASES else aliases)
    runtime = radio_inventory(data)

    def add_rows(payload: Any, source: str, fields: dict[str, str], *, summary: bool = False) -> None:
        if not isinstance(payload, dict) or payload.get("error") or payload.get("success") is False:
            return
        rows = payload.get(source)
        found: dict[str, dict] = {}
        ambiguous: set[str] = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            rid = row.get("radio_id")
            if not isinstance(rid, str) or not rid:
                continue
            identity = mapping.get(rid, rid)
            if identity in found or rid not in runtime or identity not in inventory:
                ambiguous.add(identity)
            found[identity] = row
        for identity, row in found.items():
            if identity in ambiguous or row.get("error") or row.get("success") is False:
                continue
            metrics = row.get("summary") if summary else row
            if (not isinstance(metrics, dict) or metrics.get("error")
                    or metrics.get("success") is False
                    or (summary and metrics.get("has_lbt_data") is not True)):
                continue
            for field, key in fields.items():
                value = finite_number(metrics.get(field))
                if value is not None:
                    result[identity][key] = value

    stats = data.get("stats")
    add_rows(stats, "airtime_radios", {
        "utilization_percent": "channel_utilization",
        "current_airtime_ms": "current_channel_airtime",
        "max_airtime_ms": "max_channel_airtime",
    })
    add_rows(stats, "noise_floor_radios", {"noise_floor_dbm": "noise_floor"})
    for endpoint, window in (("packet_stats_1h", "1h"), ("packet_stats", "24h")):
        add_rows(data.get(endpoint), "radios", {
            field: f"{field}_{window}"
            for field in ("received", "duplicates", "transmissions", "avg_rssi", "avg_snr")
        })
    add_rows(data.get("lbt_diagnostics"), "radios", {
        field: f"lbt_{field}_24h" for field in LBT_RADIO_FIELDS
    }, summary=True)
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
