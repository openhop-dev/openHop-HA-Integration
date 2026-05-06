"""The pyMC Repeater integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PyMCRepeaterApiClient, get_repeater_name_from_stats
from .const import CONF_API_TOKEN, DOMAIN
from .coordinator import PyMCRepeaterDataUpdateCoordinator

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.NUMBER,
]

SERVICE_PING_NEIGHBOR = "ping_neighbor"
SERVICE_ROOM_POST_MESSAGE = "room_post_message"
SERVICE_ROOM_MESSAGES_CLEAR = "room_messages_clear"
SERVICE_CAD_CALIBRATION_START = "cad_calibration_start"
SERVICE_CAD_CALIBRATION_STOP = "cad_calibration_stop"
SERVICE_SAVE_CAD_SETTINGS = "save_cad_settings"
SERVICE_DB_PURGE = "db_purge"
SERVICE_UPDATE_RADIO_CONFIG = "update_radio_config"
SERVICE_UPDATE_MQTT_CONFIG = "update_mqtt_config"
SERVICE_COMPANION_SEND_TEXT = "companion_send_text"
SERVICE_COMPANION_SEND_CHANNEL_MESSAGE = "companion_send_channel_message"
SERVICE_COMPANION_LOGIN = "companion_login"
SERVICE_COMPANION_REQUEST_STATUS = "companion_request_status"
SERVICE_COMPANION_REQUEST_TELEMETRY = "companion_request_telemetry"
SERVICE_COMPANION_SEND_COMMAND = "companion_send_command"
SERVICE_COMPANION_RESET_PATH = "companion_reset_path"
SERVICE_COMPANION_SET_ADVERT_NAME = "companion_set_advert_name"
SERVICE_COMPANION_SET_ADVERT_LOCATION = "companion_set_advert_location"
SERVICE_GET_LOGS = "get_logs"
SERVICE_GET_RECENT_PACKETS = "get_recent_packets"
SERVICE_GET_FILTERED_PACKETS = "get_filtered_packets"
SERVICE_GET_PACKET_BY_HASH = "get_packet_by_hash"
SERVICE_GET_ACL_CLIENTS = "get_acl_clients"
SERVICE_REMOVE_ACL_CLIENT = "remove_acl_client"
SERVICE_GET_ROOM_MESSAGES = "get_room_messages"
SERVICE_GET_ROOM_CLIENTS = "get_room_clients"
SERVICE_DELETE_ROOM_MESSAGE = "delete_room_message"

CONF_ENTRY_ID = "config_entry_id"
LEGACY_CONF_ENTRY_ID = "entry_id"
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML."""
    await _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up pyMC Repeater from a config entry."""
    session = async_get_clientsession(hass)
    api = PyMCRepeaterApiClient(
        session=session,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        api_token=entry.data[CONF_API_TOKEN],
    )
    coordinator = PyMCRepeaterDataUpdateCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_start_runtime()

    repeater_name = get_repeater_name_from_stats(coordinator.data.get("stats", {}))
    if repeater_name and repeater_name != entry.title:
        hass.config_entries.async_update_entry(entry, title=repeater_name)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "unsub_options_listener": entry.add_update_listener(_async_update_listener),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if entry_data:
            await entry_data["coordinator"].async_stop_runtime()
        if entry_data and (unsub := entry_data.get("unsub_options_listener")):
            unsub()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _resolve_entry_id(hass: HomeAssistant, service_data: dict) -> str:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("No pyMC Repeater entries are loaded")

    requested = service_data.get(CONF_ENTRY_ID) or service_data.get(LEGACY_CONF_ENTRY_ID)
    if requested:
        if requested not in entries:
            raise HomeAssistantError(f"Unknown pyMC Repeater entry_id: {requested}")
        return requested

    if len(entries) == 1:
        return next(iter(entries))

    raise HomeAssistantError(
        "Multiple pyMC Repeater entries are configured; provide entry_id"
    )


async def _async_refresh_entry(hass: HomeAssistant, entry_id: str) -> None:
    entry_data = hass.data[DOMAIN][entry_id]
    await entry_data["coordinator"].async_request_refresh()


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain services for advanced operations."""
    if hass.services.has_service(DOMAIN, SERVICE_PING_NEIGHBOR):
        return

    async def _with_api(
        call: ServiceCall,
        func: Callable[[PyMCRepeaterApiClient, str], Awaitable[Any]],
        *,
        refresh: bool = True,
    ) -> None:
        entry_id = _resolve_entry_id(hass, call.data)
        api: PyMCRepeaterApiClient = hass.data[DOMAIN][entry_id]["api"]
        await func(api, entry_id)
        if refresh:
            await _async_refresh_entry(hass, entry_id)

    async def _with_api_response(
        call: ServiceCall,
        func: Callable[[PyMCRepeaterApiClient, str], Awaitable[Any]],
        *,
        refresh: bool = False,
        always_return: bool = False,
    ) -> ServiceResponse | None:
        entry_id = _resolve_entry_id(hass, call.data)
        api: PyMCRepeaterApiClient = hass.data[DOMAIN][entry_id]["api"]
        result = await func(api, entry_id)
        if refresh:
            await _async_refresh_entry(hass, entry_id)
        if not always_return and not getattr(call, "return_response", False):
            return None
        if isinstance(result, dict):
            return result
        return {"result": result}

    hass.services.async_register(
        DOMAIN,
        SERVICE_PING_NEIGHBOR,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_ping_neighbor(
                target_id=call.data["target_id"],
                timeout=call.data.get("timeout", 10),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("target_id"): str,
                vol.Optional("timeout", default=10): vol.Coerce(int),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ROOM_POST_MESSAGE,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_room_post_message(
                room_name=call.data.get("room_name"),
                room_hash=call.data.get("room_hash"),
                message=call.data["message"],
                author_pubkey=call.data.get("author_pubkey", "server"),
                txt_type=call.data.get("txt_type", 0),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("room_name"): str,
                vol.Optional("room_hash"): str,
                vol.Required("message"): str,
                vol.Optional("author_pubkey", default="server"): str,
                vol.Optional("txt_type", default=0): vol.Coerce(int),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ROOM_MESSAGES_CLEAR,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_room_messages_clear(
                room_name=call.data.get("room_name"),
                room_hash=call.data.get("room_hash"),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("room_name"): str,
                vol.Optional("room_hash"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAD_CALIBRATION_START,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_cad_calibration_start(
                samples=call.data.get("samples", 8),
                delay=call.data.get("delay", 100),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("samples", default=8): vol.Coerce(int),
                vol.Optional("delay", default=100): vol.Coerce(int),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAD_CALIBRATION_STOP,
        lambda call: _with_api(
            call, lambda api, _: api.async_cad_calibration_stop(), refresh=False
        ),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_CAD_SETTINGS,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_save_cad_settings(
                peak=call.data["peak"],
                min_val=call.data["min_val"],
                detection_rate=call.data.get("detection_rate", 0),
            ),
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("peak"): vol.Coerce(int),
                vol.Required("min_val"): vol.Coerce(int),
                vol.Optional("detection_rate", default=0): vol.Coerce(int),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DB_PURGE,
        lambda call: _with_api(
            call, lambda api, _: api.async_db_purge(call.data["tables"])
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("tables"): vol.Any("all", [str]),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_RADIO_CONFIG,
        lambda call: _with_api(
            call, lambda api, _: api.async_update_radio_config(call.data["payload"])
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("payload"): dict,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_MQTT_CONFIG,
        lambda call: _with_api(
            call, lambda api, _: api.async_update_mqtt_config(call.data["payload"])
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("payload"): dict,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_SEND_TEXT,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_send_text(
                pub_key=call.data["pub_key"],
                text=call.data["text"],
                txt_type=call.data.get("txt_type", 0),
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("pub_key"): str,
                vol.Required("text"): str,
                vol.Optional("txt_type", default=0): vol.Coerce(int),
                vol.Optional("companion_name"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_SEND_CHANNEL_MESSAGE,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_send_channel_message(
                channel_idx=call.data["channel_idx"],
                text=call.data["text"],
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("channel_idx"): vol.Coerce(int),
                vol.Required("text"): str,
                vol.Optional("companion_name"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_LOGIN,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_login(
                pub_key=call.data["pub_key"],
                password=call.data.get("password", ""),
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("pub_key"): str,
                vol.Optional("password", default=""): str,
                vol.Optional("companion_name"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_REQUEST_STATUS,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_request_status(
                pub_key=call.data["pub_key"],
                timeout=call.data.get("timeout", 15.0),
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("pub_key"): str,
                vol.Optional("timeout", default=15.0): vol.Coerce(float),
                vol.Optional("companion_name"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_REQUEST_TELEMETRY,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_request_telemetry(
                pub_key=call.data["pub_key"],
                timeout=call.data.get("timeout", 20.0),
                companion_name=call.data.get("companion_name"),
                want_base=call.data.get("want_base", True),
                want_location=call.data.get("want_location", True),
                want_environment=call.data.get("want_environment", True),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("pub_key"): str,
                vol.Optional("timeout", default=20.0): vol.Coerce(float),
                vol.Optional("companion_name"): str,
                vol.Optional("want_base", default=True): bool,
                vol.Optional("want_location", default=True): bool,
                vol.Optional("want_environment", default=True): bool,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_SEND_COMMAND,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_send_command(
                pub_key=call.data["pub_key"],
                command=call.data["command"],
                parameters=call.data.get("parameters"),
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("pub_key"): str,
                vol.Required("command"): str,
                vol.Optional("parameters"): vol.Any(dict, list, str, int, float, bool),
                vol.Optional("companion_name"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_RESET_PATH,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_reset_path(
                pub_key=call.data["pub_key"],
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("pub_key"): str,
                vol.Optional("companion_name"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_SET_ADVERT_NAME,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_set_advert_name(
                advert_name=call.data["advert_name"],
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("advert_name"): str,
                vol.Optional("companion_name"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_SET_ADVERT_LOCATION,
        lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_set_advert_location(
                latitude=call.data["latitude"],
                longitude=call.data["longitude"],
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("latitude"): vol.Coerce(float),
                vol.Required("longitude"): vol.Coerce(float),
                vol.Optional("companion_name"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_LOGS,
        lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_logs(),
            always_return=True,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_RECENT_PACKETS,
        lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_recent_packets(
                limit=call.data.get("limit", 100),
            ),
            always_return=True,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("limit", default=100): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_FILTERED_PACKETS,
        lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_filtered_packets(
                packet_type=call.data.get("packet_type"),
                route=call.data.get("route"),
                start_timestamp=call.data.get("start_timestamp"),
                end_timestamp=call.data.get("end_timestamp"),
                limit=call.data.get("limit", 1000),
            ),
            always_return=True,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("packet_type"): vol.Coerce(int),
                vol.Optional("route"): vol.Coerce(int),
                vol.Optional("start_timestamp"): vol.Coerce(float),
                vol.Optional("end_timestamp"): vol.Coerce(float),
                vol.Optional("limit", default=1000): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PACKET_BY_HASH,
        lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_packet_by_hash(call.data["packet_hash"]),
            always_return=True,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("packet_hash"): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ACL_CLIENTS,
        lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_acl_clients(
                identity_hash=call.data.get("identity_hash"),
                identity_name=call.data.get("identity_name"),
            ),
            always_return=True,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("identity_hash"): str,
                vol.Optional("identity_name"): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_ACL_CLIENT,
        lambda call: _with_api_response(
            call,
            lambda api, _: api.async_remove_acl_client(
                public_key=call.data["public_key"],
                identity_hash=call.data.get("identity_hash"),
            ),
            refresh=True,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("public_key"): str,
                vol.Optional("identity_hash"): str,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ROOM_MESSAGES,
        lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_room_messages(
                room_name=call.data.get("room_name"),
                room_hash=call.data.get("room_hash"),
                limit=call.data.get("limit", 50),
                offset=call.data.get("offset", 0),
                since_timestamp=call.data.get("since_timestamp"),
            ),
            always_return=True,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("room_name"): str,
                vol.Optional("room_hash"): str,
                vol.Optional("limit", default=50): vol.Coerce(int),
                vol.Optional("offset", default=0): vol.Coerce(int),
                vol.Optional("since_timestamp"): vol.Coerce(float),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ROOM_CLIENTS,
        lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_room_clients(
                room_name=call.data.get("room_name"),
                room_hash=call.data.get("room_hash"),
            ),
            always_return=True,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("room_name"): str,
                vol.Optional("room_hash"): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_ROOM_MESSAGE,
        lambda call: _with_api_response(
            call,
            lambda api, _: api.async_delete_room_message(
                message_id=call.data["message_id"],
                room_name=call.data.get("room_name"),
                room_hash=call.data.get("room_hash"),
            ),
            refresh=True,
        ),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("room_name"): str,
                vol.Optional("room_hash"): str,
                vol.Required("message_id"): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
