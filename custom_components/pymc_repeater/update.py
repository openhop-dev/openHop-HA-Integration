"""Native firmware update entity using cached status and explicit installation."""
from __future__ import annotations

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.exceptions import HomeAssistantError

from .api import PyMCRepeaterApiError
from .const import DOMAIN
from .sensor import PyMCBaseEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Add the update entity without triggering a remote release check."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([PyMCUpdateEntity(entry, coordinator)])


class PyMCUpdateEntity(PyMCBaseEntity, UpdateEntity):
    """Install only the backend's currently selected channel; never switch it."""

    _attr_name = "Repeater software"
    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator)
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_software_update"

    @property
    def _status(self) -> dict:
        value = self.coordinator.data.get("update_status")
        return value if isinstance(value, dict) else {}

    @property
    def available(self) -> bool:
        return (super().available and not self._status.get("error")
                and self._status.get("success") is not False
                and isinstance(self._status.get("has_update"), bool)
                and bool(self.installed_version) and bool(self.latest_version))

    @property
    def installed_version(self) -> str | None:
        value = self._status.get("current_version")
        return value if isinstance(value, str) and value else None

    @property
    def latest_version(self) -> str | None:
        if self._status.get("has_update") is False:
            return self.installed_version
        value = self._status.get("latest_version")
        return value if isinstance(value, str) and value else None

    @property
    def extra_state_attributes(self) -> dict:
        return {key: self._status.get(key) for key in ("channel", "state", "last_checked", "rate_limit_until")}

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        """The API cannot select versions, back up HA, or report percentages."""
        if version is not None or backup:
            raise HomeAssistantError("Version selection and backups are not supported")
        if not self.available or self._status.get("has_update") is not True:
            raise HomeAssistantError("No confirmed update is available")
        try:
            await self.coordinator.api.async_update_install(force=False)
        except PyMCRepeaterApiError as err:
            raise HomeAssistantError("Repeater update request failed") from err
        # Installation may restart the server. Let the existing shared poll confirm it.
