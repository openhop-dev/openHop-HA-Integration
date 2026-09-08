"""Read-only operational entities discovered on the shared coordinator."""
from __future__ import annotations

import json

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import CONF_RADIO_ID_ALIASES, DOMAIN, MANUFACTURER
from .monitoring import RADIO_FIELDS, charge_state, plugin_problem, radio_inventory, reading_age, reading_stale
from .sensor import PyMCBaseEntity, _external_sensor_identity, _external_sensor_readings, _nested


def _snapshot(coordinator, binary: bool) -> dict:
    """Only scalar values and stable source identifiers enter the entity model."""
    data = coordinator.data or {}
    values = {}
    if binary:
        values[("component", "api", "connected")] = coordinator.last_update_success
        for key in ("stats", "mqtt_status", "hardware_stats", "gps", "plugin_summary", "update_status"):
            payload = data.get(key)
            values[("component", key, "problem")] = (
                (bool(payload.get("error")) or payload.get("success") is False)
                if isinstance(payload, dict) and payload else None
            )
    else:
        values[("component", "api", "last_success")] = getattr(coordinator, "last_successful_poll", None)
        entry = getattr(coordinator, "config_entry", None)
        aliases = entry.options.get(CONF_RADIO_ID_ALIASES, {}) if entry is not None else {}
        # Invalid stored values fail closed, never create replacement identities.
        for radio_id, radio in radio_inventory(data, aliases).items():
            values[("radio", radio_id, "inventory")] = radio.get("type", "configured")
            for field in RADIO_FIELDS:
                if field in radio:
                    values[("radio", radio_id, field)] = radio[field]
    plugins = _nested(data, "plugin_summary", "plugins")
    for plugin in plugins if isinstance(plugins, list) else []:
        if not isinstance(plugin, dict) or not isinstance(plugin.get("id"), str):
            continue
        fields = {"enabled": plugin.get("enabled"), "running": (
            plugin.get("state") == "RUNNING" if plugin.get("state") in ("RUNNING", "STOPPED", "FAILED", "DISABLED") else None
        ), "problem": plugin_problem(plugin)} if binary else {
            "version": plugin.get("version"), "state": plugin.get("state")}
        for field, value in fields.items():
            values[("plugin", plugin["id"], field)] = value
    interval = _nested(data, "stats", "sensors", "poll_interval_seconds")
    for reading in _external_sensor_readings(data):
        if not isinstance(reading, dict) or not reading.get("name"):
            continue
        identity = _external_sensor_identity(reading)
        if binary:
            values[("reading", identity, "stale")] = reading_stale(reading, interval)
        else:
            values[("reading", identity, "age")] = reading_age(reading)
            payload = reading.get("data")
            if isinstance(payload, dict) and "solar_charge_rate_percent_per_hour" in payload:
                values[("reading", identity, "charge_state")] = charge_state(reading, interval)
    return values


def _setup(entry, coordinator, async_add_entities, binary: bool) -> None:
    seen = set()

    def discover() -> None:
        entities = []
        for key in _snapshot(coordinator, binary):
            if key in seen:
                continue
            seen.add(key)
            cls = MonitoringBinarySensor if binary else MonitoringSensor
            entities.append(cls(entry, coordinator, key))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


def setup_monitoring_sensors(entry, coordinator, async_add_entities) -> None:
    """Discover sensors initially and when optional sources appear."""
    _setup(entry, coordinator, async_add_entities, False)


def setup_monitoring_binary_sensors(entry, coordinator, async_add_entities) -> None:
    """Discover diagnostics without a second polling schedule."""
    _setup(entry, coordinator, async_add_entities, True)


class MonitoringEntity(PyMCBaseEntity):
    """Stable source-ID entity; missing sources are unavailable, not healthy."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _binary = False

    def __init__(self, entry, coordinator, key) -> None:
        super().__init__(entry, coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_monitor_{json.dumps(key, separators=(',', ':'))}"
        self._attr_name = " ".join(key).replace("_", " ").capitalize()

    @property
    def available(self) -> bool:
        if self._key == ("component", "api", "connected"):
            return True
        return super().available and self._key in _snapshot(self.coordinator, self._binary)

    @property
    def device_info(self) -> DeviceInfo:
        kind, identity, _field = self._key
        if kind != "radio":
            return super().device_info
        parent = self._entry.unique_id or self._entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, f"{parent}_radio_{identity}")},
            via_device=(DOMAIN, parent), name=f"Radio {identity}",
            manufacturer=MANUFACTURER, model="Configured radio",
        )


class MonitoringSensor(MonitoringEntity, SensorEntity):
    """Source age, inventory, plugin version and state."""

    def __init__(self, entry, coordinator, key) -> None:
        super().__init__(entry, coordinator, key)
        if key[0] == "radio":
            self._attr_native_unit_of_measurement = {"frequency": "Hz", "bandwidth": "Hz", "tx_power": "dBm"}.get(key[2])
        if key[2] == "charge_state":
            self._attr_icon = "mdi:battery-sync-outline"
        if key[2] == "age":
            self._attr_native_unit_of_measurement = "s"
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif key[2] == "last_success":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        return _snapshot(self.coordinator, False).get(self._key)


class MonitoringBinarySensor(MonitoringEntity, BinarySensorEntity):
    """Explicit component/plugin errors and source staleness."""

    _binary = True

    def __init__(self, entry, coordinator, key) -> None:
        super().__init__(entry, coordinator, key)
        if key[2] in ("problem", "stale"):
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        elif key[2] == "connected":
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        return _snapshot(self.coordinator, True).get(self._key)
