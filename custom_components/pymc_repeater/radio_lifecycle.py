"""Retire missing radio children reversibly, never delete registry identities."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_RADIO_ID_ALIASES, DOMAIN
from .coordinator import PyMCRepeaterDataUpdateCoordinator
from .monitoring import parse_radio_aliases, radio_inventory


def _has_error(value: Any) -> bool:
    """Any endpoint failure makes a full snapshot unsuitable for retirement."""
    if isinstance(value, dict):
        return bool(value.get("error")) or value.get("success") is False or any(
            _has_error(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_has_error(child) for child in value)
    return False


def _valid_id(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and value.isprintable()
            and not any(char.isspace() for char in value))


def authoritative_radio_ids(
    coordinator: PyMCRepeaterDataUpdateCoordinator, entry: ConfigEntry
) -> set[str] | None:
    """Return canonical IDs only when the complete inventory is unambiguous.

    Empty inventories are deliberately unknown: neither supported mode proves a
    healthy zero-radio topology. Optional settings rows may be omitted, but any
    supplied rows must agree with the authoritative stack IDs. Validate before
    normalization, which intentionally drops ambiguous telemetry rows.
    """
    if not coordinator.last_update_success or coordinator.last_successful_poll is None:
        return None
    data = coordinator.data
    if not isinstance(data, dict):
        return None
    stats = data.get("stats")
    if not isinstance(stats, dict) or stats.get("error") or stats.get("success") is False:
        return None
    try:
        if _has_error({"stack": stats.get("radio_stack"), "rows": stats.get("radios")}):
            return None
    except RecursionError:
        return None
    stack = stats.get("radio_stack")
    if not isinstance(stack, dict) or stack.get("mode") not in ("single", "multi"):
        return None
    ids = stack.get("radio_ids")
    if not isinstance(ids, list) or not ids or not all(_valid_id(rid) for rid in ids):
        return None
    sources = set(ids)
    if len(sources) != len(ids) or (stack["mode"] == "single" and len(ids) != 1):
        return None
    rows = stats.get("radios", [])
    if not isinstance(rows, list):
        return None
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            return None
        if "id" in row and "radio_id" in row and row["id"] != row["radio_id"]:
            return None
        rid = row.get("id", row.get("radio_id"))
        if not _valid_id(rid) or rid not in sources or rid in seen:
            return None
        if "radio" in row and not isinstance(row["radio"], dict):
            return None
        seen.add(rid)
    try:
        aliases = parse_radio_aliases(entry.options.get(CONF_RADIO_ID_ALIASES, {}))
    except ValueError:
        return None
    # A target returning alone is the original canonical radio, not a collision.
    # Both runtime identities present at once are ambiguous: do not retire ANY.
    if any(source in sources and target in sources for source, target in aliases.items()):
        return None
    canonical = {aliases.get(rid, rid) for rid in sources}
    if len(canonical) != len(sources) or set(radio_inventory(data, aliases)) != canonical:
        return None
    return canonical


class RadioLifecycle:
    """Entry-owned full-poll listener with two-snapshot absence confirmation.

    Only disabled_by is written. HA's native device/entity registry propagation
    disables enabled child entities with DEVICE and restores only those entities
    when the device returns; the native config-entry listener schedules reload.
    No entity names, unique IDs, entity IDs, histories, or alias options change.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry,
        coordinator: PyMCRepeaterDataUpdateCoordinator,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._last_poll: datetime | None = None
        self._absences: dict[str, int] = {}
        self._started = False

    def async_start(self) -> None:
        """Register once after first refresh; entry unload owns the subscription."""
        if self._started:
            return
        self._started = True
        self._entry.async_on_unload(
            self._coordinator.async_add_listener(self.async_reconcile)
        )
        self.async_reconcile()

    def _radio_id(self, device: dr.DeviceEntry) -> str | None:
        """Manage only exclusively owned, exact single-identifier radio children."""
        if device.config_entries != {self._entry.entry_id} or len(device.identifiers) != 1:
            return None
        domain, identifier = next(iter(device.identifiers))
        prefix = f"{self._entry.unique_id or self._entry.entry_id}_radio_"
        if domain != DOMAIN or not isinstance(identifier, str) or not identifier.startswith(prefix):
            return None
        rid = identifier[len(prefix):]
        return rid if _valid_id(rid) else None

    def async_reconcile(self) -> None:
        """Count only new successful full polls, never GPS listener notifications."""
        active = authoritative_radio_ids(self._coordinator, self._entry)
        stamp = self._coordinator.last_successful_poll
        if active is None or not isinstance(stamp, datetime) or stamp.tzinfo is None:
            self._absences.clear()
            return
        if self._last_poll is not None and stamp <= self._last_poll:
            return
        self._last_poll = stamp
        registry = dr.async_get(self._hass)
        absent = {}
        for device in dr.async_entries_for_config_entry(registry, self._entry.entry_id):
            rid = self._radio_id(device)
            if rid is None:
                continue
            if rid in active:
                if device.disabled_by is dr.DeviceEntryDisabler.INTEGRATION:
                    registry.async_update_device(device.id, disabled_by=None)
                continue
            absent[device.id] = min(2, self._absences.get(device.id, 0) + 1)
            if absent[device.id] >= 2 and device.disabled_by is None:
                registry.async_update_device(
                    device.id, disabled_by=dr.DeviceEntryDisabler.INTEGRATION
                )
        self._absences = absent

    def can_remove(self, device: dr.DeviceEntry) -> bool:
        """Authorize explicit HA removal only after confirmed, still-valid absence."""
        active = authoritative_radio_ids(self._coordinator, self._entry)
        rid = self._radio_id(device)
        return (active is not None and rid is not None and rid not in active
                and self._coordinator.last_successful_poll == self._last_poll
                and self._absences.get(device.id, 0) >= 2)
