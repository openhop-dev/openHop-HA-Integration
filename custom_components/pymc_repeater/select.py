"""Select entities for openHop Repeater."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import (
    PyMCBaseEntity,
    _default_region,
    _nested,
    _transport_key_names,
    _update_channel_options,
)

MODE_OPTIONS = ["forward", "monitor", "no_tx"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up openHop Repeater selects."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    async_add_entities(
        [
            PyMCModeSelect(entry, coordinator, api),
            PyMCUpdateChannelSelect(entry, coordinator, api),
            PyMCDefaultRegionSelect(entry, coordinator, api),
        ]
    )


class PyMCModeSelect(PyMCBaseEntity, SelectEntity):
    """Select entity for repeater mode."""

    _attr_has_entity_name = True
    _attr_name = "Repeater mode"
    _attr_icon = "mdi:swap-horizontal"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = MODE_OPTIONS

    def __init__(self, entry: ConfigEntry, coordinator, api) -> None:
        super().__init__(entry, coordinator)
        self._api = api
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_repeater_mode"

    @property
    def current_option(self) -> str | None:
        return _nested(self.coordinator.data, "stats", "config", "repeater", "mode")

    async def async_select_option(self, option: str) -> None:
        await self._api.async_set_mode(option)
        await self.coordinator.async_request_refresh()


class PyMCUpdateChannelSelect(PyMCBaseEntity, SelectEntity):
    """Select entity for repeater update channel."""

    _attr_has_entity_name = True
    _attr_name = "Update channel"
    _attr_icon = "mdi:source-branch"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, coordinator, api) -> None:
        super().__init__(entry, coordinator)
        self._api = api
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_update_channel"

    @property
    def options(self) -> list[str]:
        return _update_channel_options(self.coordinator.data)

    @property
    def current_option(self) -> str | None:
        return _nested(self.coordinator.data, "update_status", "channel") or _nested(
            self.coordinator.data, "update_channels", "current_channel"
        )

    async def async_select_option(self, option: str) -> None:
        await self._api.async_update_set_channel(option)
        await self.coordinator.async_request_refresh()


class PyMCDefaultRegionSelect(PyMCBaseEntity, SelectEntity):
    """Select entity for the mesh default region."""

    _attr_has_entity_name = True
    _attr_name = "Default region"
    _attr_icon = "mdi:map-marker-radius-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, coordinator, api) -> None:
        super().__init__(entry, coordinator)
        self._api = api
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_default_region"

    @property
    def options(self) -> list[str]:
        options = ["None"]
        current = _default_region(self.coordinator.data)
        if current and current not in options:
            options.append(current)
        for name in _transport_key_names(self.coordinator.data):
            if name not in options:
                options.append(name)
        return options

    @property
    def current_option(self) -> str | None:
        return _default_region(self.coordinator.data) or "None"

    async def async_select_option(self, option: str) -> None:
        default_region = None if option == "None" else option
        await self._api.async_set_default_region(default_region)
        await self.coordinator.async_request_refresh()
