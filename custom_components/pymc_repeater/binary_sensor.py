"""Binary sensors for pyMC Repeater."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import DOMAIN
from .sensor import PyMCBaseEntity, _companion_items, _nested, _room_items


@dataclass(frozen=True, kw_only=True)
class PyMCBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description."""

    value_fn: Callable[[dict[str, Any]], bool]


def _any_mqtt_connected(data: dict[str, Any]) -> bool:
    brokers = _nested(data, "mqtt_status", "brokers") or []
    return any(_nested(broker, "status", "connected") for broker in brokers)


BINARY_SENSORS: tuple[PyMCBinarySensorDescription, ...] = (
    PyMCBinarySensorDescription(
        key="mqtt_handler_active",
        translation_key="mqtt_handler_active",
        name="MQTT handler active",
        icon="mdi:lan",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: bool(_nested(data, "mqtt_status", "handler_active")),
    ),
    PyMCBinarySensorDescription(
        key="mqtt_any_connected",
        translation_key="mqtt_any_connected",
        name="MQTT broker connected",
        icon="mdi:lan-connect",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=_any_mqtt_connected,
    ),
    PyMCBinarySensorDescription(
        key="advert_adaptive_enabled",
        translation_key="advert_adaptive_enabled",
        name="Advert adaptive enabled",
        icon="mdi:tune-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: bool(_nested(data, "advert_rate_limit_stats", "adaptive", "enabled")),
    ),
    PyMCBinarySensorDescription(
        key="advert_dedupe_enabled",
        translation_key="advert_dedupe_enabled",
        name="Advert dedupe enabled",
        icon="mdi:content-duplicate",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: bool(_nested(data, "advert_rate_limit_stats", "dedupe", "enabled")),
    ),
    PyMCBinarySensorDescription(
        key="update_available",
        name="Update available",
        icon="mdi:update",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: bool(_nested(data, "update_status", "has_update")),
    ),
    PyMCBinarySensorDescription(
        key="gps_enabled",
        name="GPS enabled",
        icon="mdi:satellite-uplink",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: bool(_nested(data, "gps", "enabled")),
    ),
    PyMCBinarySensorDescription(
        key="gps_running",
        name="GPS running",
        icon="mdi:run-fast",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: bool(_nested(data, "gps", "running")),
    ),
    PyMCBinarySensorDescription(
        key="gps_fix_valid",
        name="GPS fix valid",
        icon="mdi:crosshairs-gps",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: bool(_nested(data, "gps", "status", "fix_valid")),
    ),
    PyMCBinarySensorDescription(
        key="gps_stale",
        name="GPS stale",
        icon="mdi:timer-off-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: bool(_nested(data, "gps", "status", "stale")),
    ),
    PyMCBinarySensorDescription(
        key="gps_location_update_enabled",
        name="GPS location updates enabled",
        icon="mdi:map-marker-plus-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: bool(_nested(data, "gps", "location_update", "enabled")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up pyMC Repeater binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[BinarySensorEntity] = [
        PyMCBinarySensorEntity(entry, coordinator, description)
        for description in BINARY_SENSORS
    ]

    brokers = _nested(coordinator.data, "mqtt_status", "brokers") or []
    for broker in brokers:
        if isinstance(broker, dict):
            entities.append(PyMCMqttBrokerBinarySensor(entry, coordinator, broker))

    acls = _nested(coordinator.data, "acl_info", "acls") or []
    for acl in acls:
        if isinstance(acl, dict) and acl.get("type") == "companion" and acl.get("name"):
            entities.append(PyMCCompanionBinarySensor(entry, coordinator, acl))

    for room in _room_items(coordinator.data):
        if isinstance(room, dict) and room.get("room_name"):
            entities.append(PyMCRoomSyncBinarySensor(entry, coordinator, room))

    for companion in _companion_items(coordinator.data):
        if isinstance(companion, dict) and companion.get("companion_name"):
            entities.append(PyMCCompanionBridgeBinarySensor(entry, coordinator, companion))

    async_add_entities(entities)


class PyMCBinarySensorEntity(PyMCBaseEntity, BinarySensorEntity):
    """Representation of a pyMC Repeater binary sensor."""

    entity_description: PyMCBinarySensorDescription

    def __init__(self, entry: ConfigEntry, coordinator, description: PyMCBinarySensorDescription) -> None:
        super().__init__(entry, coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.coordinator.data)


class PyMCMqttBrokerBinarySensor(PyMCBaseEntity, BinarySensorEntity):
    """Representation of a single MQTT broker connectivity sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_icon = "mdi:access-point-network"

    def __init__(self, entry: ConfigEntry, coordinator, broker: dict[str, Any]) -> None:
        super().__init__(entry, coordinator)
        self._broker_name = str(broker.get("name") or broker.get("host") or "Broker")
        self._broker_host = str(broker.get("host") or "")
        identity = slugify(f"{self._broker_name}_{self._broker_host}") or "mqtt_broker"
        self._identity = identity
        self._attr_name = f"MQTT {self._broker_name}"
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_mqtt_broker_{identity}"

    def _get_broker(self) -> dict[str, Any] | None:
        brokers = _nested(self.coordinator.data, "mqtt_status", "brokers") or []
        for broker in brokers:
            if not isinstance(broker, dict):
                continue
            name = str(broker.get("name") or broker.get("host") or "Broker")
            host = str(broker.get("host") or "")
            identity = slugify(f"{name}_{host}") or "mqtt_broker"
            if identity == self._identity:
                return broker
        return None

    @property
    def available(self) -> bool:
        return super().available and self._get_broker() is not None

    @property
    def is_on(self) -> bool:
        broker = self._get_broker()
        return bool(_nested(broker or {}, "status", "connected"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        broker = self._get_broker() or {}
        return {
            "broker_name": broker.get("name"),
            "host": broker.get("host"),
            "enabled": broker.get("enabled"),
            "format": broker.get("format"),
            "connected": _nested(broker, "status", "connected"),
            "reconnecting": _nested(broker, "status", "reconnecting"),
        }


class PyMCCompanionBinarySensor(PyMCBaseEntity, BinarySensorEntity):
    """Connectivity sensor for a configured companion."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, coordinator, acl: dict[str, Any]) -> None:
        super().__init__(entry, coordinator)
        self._companion_name = str(acl.get("name") or "Companion")
        identity = slugify(self._companion_name) or "companion"
        self._identity = identity
        self._attr_name = f"Companion {self._companion_name}"
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_companion_{identity}"

    def _get_companion(self) -> dict[str, Any] | None:
        acls = _nested(self.coordinator.data, "acl_info", "acls") or []
        for acl in acls:
            if not isinstance(acl, dict):
                continue
            if acl.get("type") != "companion":
                continue
            identity = slugify(str(acl.get("name") or "")) or "companion"
            if identity == self._identity:
                return acl
        return None

    @property
    def available(self) -> bool:
        return super().available and self._get_companion() is not None

    @property
    def is_on(self) -> bool:
        companion = self._get_companion() or {}
        return bool(companion.get("active"))

    @property
    def icon(self) -> str:
        return "mdi:account-link" if self.is_on else "mdi:account-off-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        companion = self._get_companion() or {}
        return {
            "name": companion.get("name"),
            "hash": companion.get("hash"),
            "registered": companion.get("registered"),
            "active": companion.get("active"),
            "client_ip": companion.get("client_ip"),
        }


class PyMCRoomSyncBinarySensor(PyMCBaseEntity, BinarySensorEntity):
    """Binary sensor showing whether a room server sync loop is running."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_icon = "mdi:chat-processing"

    def __init__(self, entry: ConfigEntry, coordinator, room: dict[str, Any]) -> None:
        super().__init__(entry, coordinator)
        self._room_name = str(room.get("room_name") or "Room")
        identity = slugify(self._room_name) or "room"
        self._identity = identity
        self._attr_name = f"Room {self._room_name} sync"
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_room_sync_{identity}"

    def _get_room(self) -> dict[str, Any] | None:
        for room in _room_items(self.coordinator.data):
            if not isinstance(room, dict):
                continue
            identity = slugify(str(room.get("room_name") or "")) or "room"
            if identity == self._identity:
                return room
        return None

    @property
    def available(self) -> bool:
        return super().available and self._get_room() is not None

    @property
    def is_on(self) -> bool:
        room = self._get_room() or {}
        return bool(room.get("sync_running"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        room = self._get_room() or {}
        return {
            "room_hash": room.get("room_hash"),
            "total_messages": room.get("total_messages"),
            "total_clients": room.get("total_clients"),
            "active_clients": room.get("active_clients"),
        }


class PyMCCompanionBridgeBinarySensor(PyMCBaseEntity, BinarySensorEntity):
    """Binary sensor showing whether a companion bridge is running."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_icon = "mdi:account-link"

    def __init__(self, entry: ConfigEntry, coordinator, companion: dict[str, Any]) -> None:
        super().__init__(entry, coordinator)
        self._companion_name = str(companion.get("companion_name") or "Companion")
        identity = slugify(self._companion_name) or "companion"
        self._identity = identity
        self._attr_name = f"Companion bridge {self._companion_name}"
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_companion_bridge_{identity}_running"
        )

    def _get_companion(self) -> dict[str, Any] | None:
        for companion in _companion_items(self.coordinator.data):
            if not isinstance(companion, dict):
                continue
            identity = slugify(str(companion.get("companion_name") or "")) or "companion"
            if identity == self._identity:
                return companion
        return None

    @property
    def available(self) -> bool:
        return super().available and self._get_companion() is not None

    @property
    def is_on(self) -> bool:
        companion = self._get_companion() or {}
        return bool(companion.get("is_running"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        companion = self._get_companion() or {}
        return {
            "companion_hash": companion.get("companion_hash"),
            "node_name": companion.get("node_name"),
            "contacts_count": companion.get("contacts_count"),
            "channels_count": companion.get("channels_count"),
        }
