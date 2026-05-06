"""Sensor platform for pyMC Repeater."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, PERCENTAGE, UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .api import get_repeater_name_from_stats
from .const import (
    CONF_DATA_SIZE_UNIT,
    CONF_UPTIME_UNIT,
    DEFAULT_DATA_SIZE_UNIT,
    DEFAULT_UPTIME_UNIT,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)


def _nested(data: dict[str, Any], *keys: str) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _parse_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _packet_drop_rate(data: dict[str, Any]) -> float | None:
    total = _nested(data, "packet_stats", "total_packets")
    dropped = _nested(data, "packet_stats", "dropped_packets")
    if not total:
        return 0.0
    if dropped is None:
        return None
    return round((float(dropped) / float(total)) * 100, 1)


def _mqtt_connected_count(data: dict[str, Any]) -> int:
    brokers = _nested(data, "mqtt_status", "brokers") or []
    return sum(1 for broker in brokers if _nested(broker, "status", "connected"))


def _transport_key_count(data: dict[str, Any]) -> int:
    keys = data.get("transport_keys") or []
    return len(keys) if isinstance(keys, list) else 0


def _room_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("room_stats") or {}
    rooms = payload.get("rooms") if isinstance(payload, dict) else None
    return rooms if isinstance(rooms, list) else []


def _companion_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("companions") or []
    return payload if isinstance(payload, list) else []


def _running_companion_bridges(data: dict[str, Any]) -> int:
    return sum(1 for item in _companion_items(data) if item.get("is_running"))


def _convert_uptime(seconds: float | int | None, unit: str) -> float | int | None:
    if seconds is None:
        return None
    value = float(seconds)
    if unit == "seconds":
        return round(value, 0)
    if unit == "minutes":
        return round(value / 60, 2)
    if unit == "hours":
        return round(value / 3600, 2)
    if unit == "days":
        return round(value / 86400, 2)
    return round(value / 3600, 2)


DATA_SIZE_SENSOR_KEYS = {
    "database_size",
    "rrd_size",
    "memory_used",
    "network_bytes_sent",
    "network_bytes_recv",
}


def _convert_data_size(value_bytes: float | int | None, unit: str) -> float | int | None:
    if value_bytes is None:
        return None
    value = float(value_bytes)
    if unit == "bytes":
        return round(value, 0)
    if unit == "kibibytes":
        return round(value / 1024, 2)
    if unit == "mebibytes":
        return round(value / (1024 * 1024), 2)
    if unit == "gibibytes":
        return round(value / (1024 * 1024 * 1024), 3)
    return round(value / (1024 * 1024), 2)


@dataclass(frozen=True, kw_only=True)
class PyMCSensorDescription(SensorEntityDescription):
    """Describes a pyMC sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


SENSORS: tuple[PyMCSensorDescription, ...] = (
    PyMCSensorDescription(
        key="repeater_version",
        translation_key="repeater_version",
        name="Repeater version",
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "stats", "version"),
        attrs_fn=lambda data: {
            "core_version": _nested(data, "stats", "core_version"),
            "image_name": _nested(data, "stats", "image_name"),
            "image_version": _nested(data, "stats", "image_version"),
            "node_name": get_repeater_name_from_stats(_nested(data, "stats") or {}),
        },
    ),
    PyMCSensorDescription(
        key="update_latest_version",
        name="Update latest version",
        icon="mdi:update",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "update_status", "latest_version"),
        attrs_fn=lambda data: {
            "current_version": _nested(data, "update_status", "current_version"),
            "has_update": _nested(data, "update_status", "has_update"),
            "channel": _nested(data, "update_status", "channel"),
            "state": _nested(data, "update_status", "state"),
            "last_checked": _nested(data, "update_status", "last_checked"),
            "error": _nested(data, "update_status", "error"),
            "rate_limit_until": _nested(data, "update_status", "rate_limit_until"),
        },
    ),
    PyMCSensorDescription(
        key="update_channel",
        name="Update channel",
        icon="mdi:source-branch",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "update_status", "channel")
        or _nested(data, "update_channels", "current_channel"),
        attrs_fn=lambda data: {
            "available_channels": _nested(data, "update_channels", "channels"),
        },
    ),
    PyMCSensorDescription(
        key="update_state",
        name="Update state",
        icon="mdi:progress-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "update_status", "state"),
        attrs_fn=lambda data: {
            "error": _nested(data, "update_status", "error"),
            "last_checked": _nested(data, "update_status", "last_checked"),
        },
    ),
    PyMCSensorDescription(
        key="gps_state",
        name="GPS state",
        icon="mdi:crosshairs-gps",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "gps", "status", "state"),
        attrs_fn=lambda data: {
            "enabled": _nested(data, "gps", "enabled"),
            "running": _nested(data, "gps", "running"),
            "fix_valid": _nested(data, "gps", "status", "fix_valid"),
            "stale": _nested(data, "gps", "status", "stale"),
            "age_seconds": _nested(data, "gps", "status", "age_seconds"),
            "last_update": _nested(data, "gps", "status", "last_update"),
            "last_error": _nested(data, "gps", "status", "last_error"),
            "source": _nested(data, "gps", "source"),
        },
    ),
    PyMCSensorDescription(
        key="gps_quality",
        name="GPS quality",
        icon="mdi:satellite-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "gps", "fix", "quality_label")
        or _nested(data, "gps", "fix", "status"),
        attrs_fn=lambda data: {
            "quality_code": _nested(data, "gps", "fix", "quality"),
            "gsa_fix_type": _nested(data, "gps", "fix", "gsa_fix_type"),
            "gsa_fix_type_label": _nested(data, "gps", "fix", "gsa_fix_type_label"),
        },
    ),
    PyMCSensorDescription(
        key="gps_latitude",
        name="GPS latitude",
        icon="mdi:latitude",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "position", "latitude"),
    ),
    PyMCSensorDescription(
        key="gps_longitude",
        name="GPS longitude",
        icon="mdi:longitude",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "position", "longitude"),
    ),
    PyMCSensorDescription(
        key="gps_altitude",
        name="GPS altitude",
        icon="mdi:image-filter-hdr",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "position", "altitude_m"),
    ),
    PyMCSensorDescription(
        key="gps_geoid_separation",
        name="GPS geoid separation",
        icon="mdi:image-filter-center-focus",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "position", "geoid_separation_m"),
    ),
    PyMCSensorDescription(
        key="gps_speed",
        name="GPS speed",
        icon="mdi:speedometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="km/h",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "motion", "speed_kmh"),
        attrs_fn=lambda data: {
            "speed_knots": _nested(data, "gps", "motion", "speed_knots"),
            "course_degrees": _nested(data, "gps", "motion", "course_degrees"),
            "magnetic_variation_degrees": _nested(
                data, "gps", "motion", "magnetic_variation_degrees"
            ),
        },
    ),
    PyMCSensorDescription(
        key="gps_course",
        name="GPS course",
        icon="mdi:compass-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="°",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "motion", "course_degrees"),
        attrs_fn=lambda data: {
            "magnetic_variation_degrees": _nested(
                data, "gps", "motion", "magnetic_variation_degrees"
            ),
        },
    ),
    PyMCSensorDescription(
        key="gps_magnetic_variation",
        name="GPS magnetic variation",
        icon="mdi:compass-rose",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="°",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(
            data, "gps", "motion", "magnetic_variation_degrees"
        ),
    ),
    PyMCSensorDescription(
        key="gps_hdop",
        name="GPS HDOP",
        icon="mdi:map-marker-radius",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "accuracy", "hdop"),
        attrs_fn=lambda data: {
            "pdop": _nested(data, "gps", "accuracy", "pdop"),
            "vdop": _nested(data, "gps", "accuracy", "vdop"),
        },
    ),
    PyMCSensorDescription(
        key="gps_pdop",
        name="GPS PDOP",
        icon="mdi:map-marker-distance",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "accuracy", "pdop"),
    ),
    PyMCSensorDescription(
        key="gps_vdop",
        name="GPS VDOP",
        icon="mdi:axis-z-arrow",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "accuracy", "vdop"),
    ),
    PyMCSensorDescription(
        key="gps_datetime_utc",
        name="GPS UTC time",
        icon="mdi:clock-time-eight-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _parse_datetime(_nested(data, "gps", "time", "datetime_utc")),
        attrs_fn=lambda data: {
            "utc_time": _nested(data, "gps", "time", "utc_time"),
            "date": _nested(data, "gps", "time", "date"),
        },
    ),
    PyMCSensorDescription(
        key="gps_location_update_state",
        name="GPS location update state",
        icon="mdi:map-marker-path",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "gps", "location_update", "state"),
        attrs_fn=lambda data: {
            "enabled": _nested(data, "gps", "location_update", "enabled"),
            "last_attempt": _nested(data, "gps", "location_update", "last_attempt"),
            "last_success": _nested(data, "gps", "location_update", "last_success"),
            "last_error": _nested(data, "gps", "location_update", "last_error"),
            "last_latitude": _nested(data, "gps", "location_update", "last_latitude"),
            "last_longitude": _nested(data, "gps", "location_update", "last_longitude"),
            "interval_seconds": _nested(data, "gps", "location_update", "interval_seconds"),
        },
    ),
    PyMCSensorDescription(
        key="gps_checksum_valid_count",
        name="GPS valid checksums",
        icon="mdi:check-decagram-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "nmea", "valid_checksum_count"),
        attrs_fn=lambda data: {
            "invalid_checksum_count": _nested(
                data, "gps", "nmea", "invalid_checksum_count"
            ),
            "missing_checksum_count": _nested(
                data, "gps", "nmea", "missing_checksum_count"
            ),
        },
    ),
    PyMCSensorDescription(
        key="gps_last_sentence_type",
        name="GPS last sentence type",
        icon="mdi:message-text-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "gps", "nmea", "last_sentence_type"),
        attrs_fn=lambda data: {
            "last_talker": _nested(data, "gps", "nmea", "last_talker"),
            "last_sentence": _nested(data, "gps", "nmea", "last_sentence"),
            "seen_sentence_types": _nested(data, "gps", "nmea", "seen_sentence_types"),
            "sentence_counters": _nested(data, "gps", "nmea", "sentence_counters"),
            "recent_sentences": _nested(data, "gps", "nmea", "recent_sentences"),
            "raw_attributes": _nested(data, "gps", "raw_attributes"),
        },
    ),
    PyMCSensorDescription(
        key="gps_satellites_used",
        name="GPS satellites used",
        icon="mdi:satellite-uplink",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "satellites", "used_count"),
        attrs_fn=lambda data: {
            "used_prns": _nested(data, "gps", "satellites", "used_prns"),
        },
    ),
    PyMCSensorDescription(
        key="gps_satellites_in_view",
        name="GPS satellites in view",
        icon="mdi:satellite-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "gps", "satellites", "in_view_count"),
        attrs_fn=lambda data: {
            "snr_min": _nested(data, "gps", "satellites", "snr", "min"),
            "snr_max": _nested(data, "gps", "satellites", "snr", "max"),
            "snr_avg": _nested(data, "gps", "satellites", "snr", "avg"),
            "in_view": _nested(data, "gps", "satellites", "in_view"),
        },
    ),
    PyMCSensorDescription(
        key="packets_24h",
        translation_key="packets_24h",
        name="Packets (24h)",
        icon="mdi:radio-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "packet_stats", "total_packets"),
        attrs_fn=lambda data: {
            "packet_types": _nested(data, "packet_stats", "packet_types"),
            "drop_reasons": _nested(data, "packet_stats", "drop_reasons"),
            "route_totals": _nested(data, "route_stats", "route_totals"),
        },
    ),
    PyMCSensorDescription(
        key="transmitted_packets_24h",
        translation_key="transmitted_packets_24h",
        name="Transmitted packets (24h)",
        icon="mdi:send",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "packet_stats", "transmitted_packets"),
    ),
    PyMCSensorDescription(
        key="dropped_packets_24h",
        translation_key="dropped_packets_24h",
        name="Dropped packets (24h)",
        icon="mdi:delete-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "packet_stats", "dropped_packets"),
    ),
    PyMCSensorDescription(
        key="packet_drop_rate_24h",
        translation_key="packet_drop_rate_24h",
        name="Packet drop rate (24h)",
        icon="mdi:percent",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_packet_drop_rate,
    ),
    PyMCSensorDescription(
        key="avg_rssi_24h",
        translation_key="avg_rssi_24h",
        name="Average RSSI (24h)",
        icon="mdi:signal",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "packet_stats", "avg_rssi"),
    ),
    PyMCSensorDescription(
        key="avg_snr_24h",
        translation_key="avg_snr_24h",
        name="Average SNR (24h)",
        icon="mdi:waves",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "packet_stats", "avg_snr"),
    ),
    PyMCSensorDescription(
        key="avg_tx_delay_24h",
        translation_key="avg_tx_delay_24h",
        name="Average TX delay (24h)",
        icon="mdi:timer-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "packet_stats", "avg_tx_delay"),
    ),
    PyMCSensorDescription(
        key="avg_score_24h",
        translation_key="avg_score_24h",
        name="Average score (24h)",
        icon="mdi:chart-line",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "packet_stats", "avg_score"),
    ),
    PyMCSensorDescription(
        key="avg_payload_length_24h",
        translation_key="avg_payload_length_24h",
        name="Average payload length (24h)",
        icon="mdi:package-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "packet_stats", "avg_payload_length"),
    ),
    PyMCSensorDescription(
        key="avg_noise_floor_24h",
        translation_key="avg_noise_floor_24h",
        name="Average noise floor (24h)",
        icon="mdi:chart-bell-curve",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "noise_floor_stats", "avg_noise_floor"),
        attrs_fn=lambda data: {
            "measurement_count": _nested(data, "noise_floor_stats", "measurement_count"),
            "min_noise_floor": _nested(data, "noise_floor_stats", "min_noise_floor"),
            "max_noise_floor": _nested(data, "noise_floor_stats", "max_noise_floor"),
        },
    ),
    PyMCSensorDescription(
        key="current_noise_floor",
        translation_key="current_noise_floor",
        name="Current noise floor",
        icon="mdi:waveform",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "stats", "noise_floor_dbm"),
    ),
    PyMCSensorDescription(
        key="crc_errors_24h",
        translation_key="crc_errors_24h",
        name="CRC errors (24h)",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "crc_error_count", "crc_error_count"),
    ),
    PyMCSensorDescription(
        key="mqtt_connected_brokers",
        translation_key="mqtt_connected_brokers",
        name="Connected MQTT brokers",
        icon="mdi:lan-connect",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_mqtt_connected_count,
        attrs_fn=lambda data: {
            "handler_active": _nested(data, "mqtt_status", "handler_active"),
            "brokers": _nested(data, "mqtt_status", "brokers"),
        },
    ),
    PyMCSensorDescription(
        key="running_companion_bridges",
        name="Running companion bridges",
        icon="mdi:account-link",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_running_companion_bridges,
        attrs_fn=lambda data: {"companions": _companion_items(data)},
    ),
    PyMCSensorDescription(
        key="room_servers",
        name="Room servers",
        icon="mdi:chat-processing-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "room_stats", "total_rooms") or len(_room_items(data)),
        attrs_fn=lambda data: {"rooms": _room_items(data)},
    ),
    PyMCSensorDescription(
        key="rx_per_hour",
        translation_key="rx_per_hour",
        name="Packets received per hour",
        icon="mdi:download-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "stats", "rx_per_hour"),
    ),
    PyMCSensorDescription(
        key="forwarded_per_hour",
        translation_key="forwarded_per_hour",
        name="Packets forwarded per hour",
        icon="mdi:upload-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "stats", "forwarded_per_hour"),
    ),
    PyMCSensorDescription(
        key="radio_utilization",
        translation_key="radio_utilization",
        name="Radio utilization",
        icon="mdi:chart-arc",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "stats", "utilization_percent"),
    ),
    PyMCSensorDescription(
        key="current_airtime",
        translation_key="current_airtime",
        name="Current airtime",
        icon="mdi:timer-sand",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "stats", "current_airtime_ms"),
    ),
    PyMCSensorDescription(
        key="acl_total_clients",
        translation_key="acl_total_clients",
        name="ACL clients",
        icon="mdi:account-multiple-check-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "acl_stats", "total_clients"),
        attrs_fn=lambda data: {
            "admin_clients": _nested(data, "acl_stats", "admin_clients"),
            "guest_clients": _nested(data, "acl_stats", "guest_clients"),
            "total_identities": _nested(data, "acl_stats", "total_identities"),
            "by_identity_type": _nested(data, "acl_stats", "by_identity_type"),
        },
    ),
    PyMCSensorDescription(
        key="acl_authenticated_clients",
        translation_key="acl_authenticated_clients",
        name="Authenticated clients",
        icon="mdi:account-check-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "acl_info", "total_authenticated_clients"),
        attrs_fn=lambda data: {
            "acls": _nested(data, "acl_info", "acls"),
        },
    ),
    PyMCSensorDescription(
        key="identities_registered",
        translation_key="identities_registered",
        name="Registered identities",
        icon="mdi:badge-account-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "identities", "total_registered"),
        attrs_fn=lambda data: {
            "total_configured": _nested(data, "identities", "total_configured"),
            "total_configured_companions": _nested(
                data, "identities", "total_configured_companions"
            ),
        },
    ),
    PyMCSensorDescription(
        key="configured_companions",
        translation_key="configured_companions",
        name="Configured companions",
        icon="mdi:account-group-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "identities", "total_configured_companions"),
        attrs_fn=lambda data: {
            "configured_companions": _nested(data, "identities", "configured_companions"),
        },
    ),
    PyMCSensorDescription(
        key="database_size",
        translation_key="database_size",
        name="Database size",
        icon="mdi:database",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "db_stats", "database_size_bytes"),
        attrs_fn=lambda data: {
            "rrd_size_bytes": _nested(data, "db_stats", "rrd_size_bytes"),
            "tables": _nested(data, "db_stats", "tables"),
        },
    ),
    PyMCSensorDescription(
        key="rrd_size",
        translation_key="rrd_size",
        name="Metrics history size",
        icon="mdi:database-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "db_stats", "rrd_size_bytes"),
    ),
    PyMCSensorDescription(
        key="transport_key_count",
        translation_key="transport_key_count",
        name="Transport keys",
        icon="mdi:key-chain",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_transport_key_count,
        attrs_fn=lambda data: {"keys": data.get("transport_keys")},
    ),
    PyMCSensorDescription(
        key="advert_tier",
        translation_key="advert_tier",
        name="Advert tier",
        icon="mdi:stairs",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "advert_rate_limit_stats", "adaptive", "current_tier"),
        attrs_fn=lambda data: {
            "adaptive": _nested(data, "advert_rate_limit_stats", "adaptive"),
            "metrics": _nested(data, "advert_rate_limit_stats", "metrics"),
            "effective_limits": _nested(data, "advert_rate_limit_stats", "effective_limits"),
        },
    ),
    PyMCSensorDescription(
        key="adverts_allowed",
        translation_key="adverts_allowed",
        name="Adverts allowed",
        icon="mdi:check-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "advert_rate_limit_stats", "stats", "adverts_allowed"),
    ),
    PyMCSensorDescription(
        key="adverts_dropped",
        translation_key="adverts_dropped",
        name="Adverts dropped",
        icon="mdi:cancel",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "advert_rate_limit_stats", "stats", "adverts_dropped"),
    ),
    PyMCSensorDescription(
        key="advert_drop_rate",
        translation_key="advert_drop_rate",
        name="Advert drop rate",
        icon="mdi:percent-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            round(float(_nested(data, "advert_rate_limit_stats", "stats", "drop_rate") or 0) * 100, 2)
        ),
    ),
    PyMCSensorDescription(
        key="advert_tracked_hashes",
        translation_key="advert_tracked_hashes",
        name="Tracked advert hashes",
        icon="mdi:pound-box-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "advert_rate_limit_stats", "dedupe", "tracked_hashes"),
    ),
    PyMCSensorDescription(
        key="advert_tracked_pubkeys",
        translation_key="advert_tracked_pubkeys",
        name="Tracked advert pubkeys",
        icon="mdi:key-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "advert_rate_limit_stats", "tracked_pubkeys"),
    ),
    PyMCSensorDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        name="CPU usage",
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "hardware_stats", "cpu", "usage_percent"),
    ),
    PyMCSensorDescription(
        key="memory_usage",
        translation_key="memory_usage",
        name="Memory usage",
        icon="mdi:memory",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "hardware_stats", "memory", "usage_percent"),
    ),
    PyMCSensorDescription(
        key="memory_used",
        translation_key="memory_used",
        name="Memory used",
        icon="mdi:memory-arrow-down",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "hardware_stats", "memory", "used"),
    ),
    PyMCSensorDescription(
        key="disk_usage",
        translation_key="disk_usage",
        name="Disk usage",
        icon="mdi:harddisk",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "hardware_stats", "disk", "usage_percent"),
    ),
    PyMCSensorDescription(
        key="network_bytes_sent",
        translation_key="network_bytes_sent",
        name="Network bytes sent",
        icon="mdi:upload",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _nested(data, "hardware_stats", "network", "bytes_sent"),
    ),
    PyMCSensorDescription(
        key="network_bytes_recv",
        translation_key="network_bytes_recv",
        name="Network bytes received",
        icon="mdi:download",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _nested(data, "hardware_stats", "network", "bytes_recv"),
    ),
    PyMCSensorDescription(
        key="network_packets_sent",
        translation_key="network_packets_sent",
        name="Network packets sent",
        icon="mdi:upload-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _nested(data, "hardware_stats", "network", "packets_sent"),
    ),
    PyMCSensorDescription(
        key="network_packets_recv",
        translation_key="network_packets_recv",
        name="Network packets received",
        icon="mdi:download-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _nested(data, "hardware_stats", "network", "packets_recv"),
    ),
    PyMCSensorDescription(
        key="total_processes",
        translation_key="total_processes",
        name="Total processes",
        icon="mdi:format-list-bulleted-square",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "hardware_processes", "total_processes"),
        attrs_fn=lambda data: {
            "processes": _nested(data, "hardware_processes", "processes"),
        },
    ),
    PyMCSensorDescription(
        key="system_uptime",
        translation_key="system_uptime",
        name="System uptime",
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "hardware_stats", "system", "uptime"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up pyMC Repeater sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[SensorEntity] = [
        PyMCSensorEntity(entry, coordinator, description) for description in SENSORS
    ]

    for route_name in ((_nested(coordinator.data, "route_stats", "route_totals") or {}).keys()):
        entities.append(PyMCRouteTotalSensor(entry, coordinator, str(route_name)))

    tables = _nested(coordinator.data, "db_stats", "tables") or []
    for table in tables:
        if isinstance(table, dict) and table.get("name"):
            entities.append(PyMCDatabaseTableSensor(entry, coordinator, str(table["name"])))

    temps = _nested(coordinator.data, "hardware_stats", "temperatures") or {}
    for temp_name in temps.keys():
        entities.append(PyMCTemperatureSensor(entry, coordinator, str(temp_name)))

    for room in _room_items(coordinator.data):
        if isinstance(room, dict) and room.get("room_name"):
            entities.extend(
                [
                    PyMCRoomMetricSensor(entry, coordinator, str(room["room_name"]), "total_messages"),
                    PyMCRoomMetricSensor(entry, coordinator, str(room["room_name"]), "total_clients"),
                    PyMCRoomMetricSensor(entry, coordinator, str(room["room_name"]), "active_clients"),
                ]
            )

    for companion in _companion_items(coordinator.data):
        if isinstance(companion, dict) and companion.get("companion_name"):
            entities.extend(
                [
                    PyMCCompanionMetricSensor(
                        entry, coordinator, str(companion["companion_name"]), "contacts_count"
                    ),
                    PyMCCompanionMetricSensor(
                        entry, coordinator, str(companion["companion_name"]), "channels_count"
                    ),
                ]
            )

    async_add_entities(entities)


class PyMCBaseEntity(CoordinatorEntity):
    """Common entity behavior for pyMC Repeater."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, coordinator) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        stats = self.coordinator.data.get("stats", {})
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.unique_id or self._entry.entry_id)},
            name=get_repeater_name_from_stats(stats) or self._entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=stats.get("version"),
            configuration_url=f"http://{self._entry.data[CONF_HOST]}:{self._entry.data[CONF_PORT]}",
        )


class PyMCSensorEntity(PyMCBaseEntity, SensorEntity):
    """Representation of a pyMC Repeater sensor."""

    entity_description: PyMCSensorDescription

    def __init__(self, entry: ConfigEntry, coordinator, description: PyMCSensorDescription) -> None:
        super().__init__(entry, coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        if self.entity_description.key == "system_uptime":
            raw_seconds = self.entity_description.value_fn(self.coordinator.data)
            return _convert_uptime(
                raw_seconds,
                self._entry.options.get(CONF_UPTIME_UNIT, DEFAULT_UPTIME_UNIT),
            )
        if self.entity_description.key in DATA_SIZE_SENSOR_KEYS:
            raw_bytes = self.entity_description.value_fn(self.coordinator.data)
            return _convert_data_size(
                raw_bytes,
                self._entry.options.get(CONF_DATA_SIZE_UNIT, DEFAULT_DATA_SIZE_UNIT),
            )
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.key in DATA_SIZE_SENSOR_KEYS:
            unit = self._entry.options.get(CONF_DATA_SIZE_UNIT, DEFAULT_DATA_SIZE_UNIT)
            return {
                "bytes": UnitOfInformation.BYTES,
                "kibibytes": UnitOfInformation.KIBIBYTES,
                "mebibytes": UnitOfInformation.MEBIBYTES,
                "gibibytes": UnitOfInformation.GIBIBYTES,
            }.get(unit, UnitOfInformation.MEBIBYTES)

        if self.entity_description.key != "system_uptime":
            return self.entity_description.native_unit_of_measurement

        unit = self._entry.options.get(CONF_UPTIME_UNIT, DEFAULT_UPTIME_UNIT)
        return {
            "seconds": UnitOfTime.SECONDS,
            "minutes": UnitOfTime.MINUTES,
            "hours": UnitOfTime.HOURS,
            "days": UnitOfTime.DAYS,
        }.get(unit, UnitOfTime.HOURS)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = self.entity_description.attrs_fn(self.coordinator.data) if self.entity_description.attrs_fn else None
        if self.entity_description.key in DATA_SIZE_SENSOR_KEYS:
            raw_bytes = self.entity_description.value_fn(self.coordinator.data)
            merged = dict(attrs or {})
            merged["raw_bytes"] = raw_bytes
            merged["display_unit"] = self._entry.options.get(
                CONF_DATA_SIZE_UNIT, DEFAULT_DATA_SIZE_UNIT
            )
            return merged

        if self.entity_description.key != "system_uptime":
            return attrs

        raw_seconds = self.entity_description.value_fn(self.coordinator.data)
        merged = dict(attrs or {})
        merged["raw_seconds"] = raw_seconds
        merged["display_unit"] = self._entry.options.get(CONF_UPTIME_UNIT, DEFAULT_UPTIME_UNIT)
        return merged


class PyMCRouteTotalSensor(PyMCBaseEntity, SensorEntity):
    """Named route total sensor."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:routes"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry, coordinator, route_name: str) -> None:
        super().__init__(entry, coordinator)
        self._route_name = route_name
        self._attr_name = f"Route {route_name}"
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_route_{slugify(route_name) or 'route'}"
        )

    @property
    def native_value(self) -> Any:
        return (_nested(self.coordinator.data, "route_stats", "route_totals") or {}).get(
            self._route_name
        )


class PyMCRoomMetricSensor(PyMCBaseEntity, SensorEntity):
    """Dynamic room metric sensor."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    _FIELD_NAMES = {
        "total_messages": "messages",
        "total_clients": "clients",
        "active_clients": "active clients",
    }
    _FIELD_ICONS = {
        "total_messages": "mdi:message-text-outline",
        "total_clients": "mdi:account-group-outline",
        "active_clients": "mdi:account-check-outline",
    }

    def __init__(self, entry: ConfigEntry, coordinator, room_name: str, field: str) -> None:
        super().__init__(entry, coordinator)
        self._room_name = room_name
        self._field = field
        self._attr_name = f"Room {room_name} {self._FIELD_NAMES[field]}"
        self._attr_icon = self._FIELD_ICONS[field]
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_room_{slugify(room_name) or 'room'}_{field}"
        )

    def _get_room(self) -> dict[str, Any] | None:
        for room in _room_items(self.coordinator.data):
            if isinstance(room, dict) and room.get("room_name") == self._room_name:
                return room
        return None

    @property
    def available(self) -> bool:
        return super().available and self._get_room() is not None

    @property
    def native_value(self) -> Any:
        room = self._get_room() or {}
        return room.get(self._field)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        room = self._get_room() or {}
        return {
            "room_hash": room.get("room_hash"),
            "sync_running": room.get("sync_running"),
            "max_posts": room.get("max_posts"),
        }


class PyMCCompanionMetricSensor(PyMCBaseEntity, SensorEntity):
    """Dynamic companion bridge metric sensor."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    _FIELD_NAMES = {
        "contacts_count": "contacts",
        "channels_count": "channels",
    }
    _FIELD_ICONS = {
        "contacts_count": "mdi:account-multiple-outline",
        "channels_count": "mdi:radio-handheld",
    }

    def __init__(self, entry: ConfigEntry, coordinator, companion_name: str, field: str) -> None:
        super().__init__(entry, coordinator)
        self._companion_name = companion_name
        self._field = field
        self._attr_name = f"Companion {companion_name} {self._FIELD_NAMES[field]}"
        self._attr_icon = self._FIELD_ICONS[field]
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_companion_bridge_"
            f"{slugify(companion_name) or 'companion'}_{field}"
        )

    def _get_companion(self) -> dict[str, Any] | None:
        for item in _companion_items(self.coordinator.data):
            if isinstance(item, dict) and item.get("companion_name") == self._companion_name:
                return item
        return None

    @property
    def available(self) -> bool:
        return super().available and self._get_companion() is not None

    @property
    def native_value(self) -> Any:
        companion = self._get_companion() or {}
        return companion.get(self._field)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        companion = self._get_companion() or {}
        return {
            "companion_hash": companion.get("companion_hash"),
            "node_name": companion.get("node_name"),
            "public_key": companion.get("public_key"),
            "is_running": companion.get("is_running"),
        }


class PyMCDatabaseTableSensor(PyMCBaseEntity, SensorEntity):
    """Database table row count sensor."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:table"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry, coordinator, table_name: str) -> None:
        super().__init__(entry, coordinator)
        self._table_name = table_name
        self._attr_name = f"DB rows {table_name}"
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_db_table_{slugify(table_name) or 'table'}"
        )

    def _get_table(self) -> dict[str, Any] | None:
        tables = _nested(self.coordinator.data, "db_stats", "tables") or []
        for table in tables:
            if isinstance(table, dict) and table.get("name") == self._table_name:
                return table
        return None

    @property
    def available(self) -> bool:
        return super().available and self._get_table() is not None

    @property
    def native_value(self) -> Any:
        table = self._get_table() or {}
        return table.get("row_count")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        table = self._get_table() or {}
        return {
            "has_timestamp": table.get("has_timestamp"),
            "oldest_timestamp": table.get("oldest_timestamp"),
            "newest_timestamp": table.get("newest_timestamp"),
        }


class PyMCTemperatureSensor(PyMCBaseEntity, SensorEntity):
    """Temperature sensor from hardware stats."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = "°C"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer"

    def __init__(self, entry: ConfigEntry, coordinator, temp_name: str) -> None:
        super().__init__(entry, coordinator)
        self._temp_name = temp_name
        self._attr_name = f"Temperature {temp_name}"
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_temp_{slugify(temp_name) or 'temp'}"
        )

    @property
    def native_value(self) -> Any:
        return (_nested(self.coordinator.data, "hardware_stats", "temperatures") or {}).get(
            self._temp_name
        )
