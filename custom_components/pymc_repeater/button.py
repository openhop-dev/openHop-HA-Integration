"""Button entities for openHop Repeater."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import PyMCBaseEntity


@dataclass(frozen=True, kw_only=True)
class PyMCButtonDescription(ButtonEntityDescription):
    """Description for an openHop button."""

    press_fn: Callable[[object], Awaitable[object]]
    refresh_after: bool = True


BUTTONS: tuple[PyMCButtonDescription, ...] = (
    PyMCButtonDescription(
        key="send_advert",
        name="Send advert",
        icon="mdi:radio-tower",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda api: api.async_send_advert(),
    ),
    PyMCButtonDescription(
        key="restart_service",
        name="Restart repeater service",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda api: api.async_restart_service(),
        refresh_after=False,
    ),
    PyMCButtonDescription(
        key="db_vacuum",
        name="Vacuum metrics database",
        icon="mdi:database-refresh-outline",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda api: api.async_db_vacuum(),
    ),
    PyMCButtonDescription(
        key="update_check",
        name="Check for updates",
        icon="mdi:update",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda api: api.async_update_check(force=True),
    ),
    PyMCButtonDescription(
        key="update_install",
        name="Install latest update",
        icon="mdi:download-network-outline",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda api: api.async_update_install(force=False),
        refresh_after=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up openHop Repeater buttons."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    async_add_entities(PyMCButtonEntity(entry, coordinator, api, desc) for desc in BUTTONS)


class PyMCButtonEntity(PyMCBaseEntity, ButtonEntity):
    """An openHop button entity."""

    entity_description: PyMCButtonDescription

    def __init__(self, entry: ConfigEntry, coordinator, api, description: PyMCButtonDescription) -> None:
        super().__init__(entry, coordinator)
        self._api = api
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self._api)
        if self.entity_description.refresh_after:
            await self.coordinator.async_request_refresh()
