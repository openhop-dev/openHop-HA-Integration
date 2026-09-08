"""Diagnostics support for openHop Repeater."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_TOKEN, DOMAIN

TO_REDACT = {
    CONF_API_TOKEN,
    "token",
    "password",
    "admin_password",
    "guest_password",
    "jwt_secret",
    "identity_key",
    "private_key",
    "transport_key",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "gps_position",
    "manual_position",
    "network_current_ip",
    "ip_address",
    "client_address",
    "host",
    "url",
    "public_key",
    "pubkey",
    "identity_hash",
    "companion_hash",
    "room_hash",
    "radio_error",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "data": async_redact_data(coordinator.data, TO_REDACT),
    }

