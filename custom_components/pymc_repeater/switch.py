"""Switch entities for openHop Repeater."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import PyMCBaseEntity, _nested


@dataclass(frozen=True, kw_only=True)
class PyMCSwitchDescription:
    """Description for an openHop switch."""

    key: str
    name: str
    icon: str
    value_fn: Callable[[dict], bool]
    set_fn: Callable[[object, bool], Awaitable[object]]


SWITCHES: tuple[PyMCSwitchDescription, ...] = (
    PyMCSwitchDescription(
        key="duty_cycle_enforcement",
        name="Duty cycle enforcement",
        icon="mdi:speedometer-medium",
        value_fn=lambda data: bool(
            _nested(data, "stats", "config", "duty_cycle", "enforcement_enabled")
        ),
        set_fn=lambda api, enabled: api.async_update_duty_cycle_config(
            enforcement_enabled=enabled
        ),
    ),
    PyMCSwitchDescription(
        key="advert_rate_limit_enabled",
        name="Advert rate limit",
        icon="mdi:traffic-cone",
        value_fn=lambda data: bool(
            _nested(data, "stats", "config", "repeater", "advert_rate_limit", "enabled")
        ),
        set_fn=lambda api, enabled: api.async_update_advert_rate_limit_config(
            rate_limit_enabled=enabled
        ),
    ),
    PyMCSwitchDescription(
        key="advert_penalty_enabled",
        name="Advert penalty box",
        icon="mdi:alert-octagon-outline",
        value_fn=lambda data: bool(
            _nested(data, "stats", "config", "repeater", "advert_penalty_box", "enabled")
        ),
        set_fn=lambda api, enabled: api.async_update_advert_rate_limit_config(
            penalty_enabled=enabled
        ),
    ),
    PyMCSwitchDescription(
        key="advert_adaptive_enabled",
        name="Advert adaptive control",
        icon="mdi:tune-variant",
        value_fn=lambda data: bool(
            _nested(data, "stats", "config", "repeater", "advert_adaptive", "enabled")
        ),
        set_fn=lambda api, enabled: api.async_update_advert_rate_limit_config(
            adaptive_enabled=enabled
        ),
    ),
    PyMCSwitchDescription(
        key="unscoped_flood_allow",
        name="Allow unscoped flood",
        icon="mdi:access-point-plus",
        value_fn=lambda data: bool(
            _nested(data, "stats", "config", "mesh", "unscoped_flood_allow")
        ),
        set_fn=lambda api, enabled: api.async_set_unscoped_flood_policy(enabled),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up openHop Repeater switches."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    async_add_entities(PyMCSwitchEntity(entry, coordinator, api, desc) for desc in SWITCHES)


class PyMCSwitchEntity(PyMCBaseEntity, SwitchEntity):
    """An openHop switch entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, coordinator, api, description: PyMCSwitchDescription) -> None:
        super().__init__(entry, coordinator)
        self._api = api
        self.description = description
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        return self.description.value_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs) -> None:
        await self.description.set_fn(self._api, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.description.set_fn(self._api, False)
        await self.coordinator.async_request_refresh()
