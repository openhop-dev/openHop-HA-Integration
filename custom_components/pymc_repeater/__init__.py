"""The openHop Repeater integration."""

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
from homeassistant.helpers.device_registry import DeviceEntry

from .api import PyMCRepeaterApiClient, PyMCRepeaterError, get_repeater_name_from_stats
from .const import CONF_API_TOKEN, DOMAIN
from .coordinator import PyMCRepeaterDataUpdateCoordinator
from .radio_lifecycle import RadioLifecycle


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow operator removal only of a confirmed absent radio child."""
    lifecycle = hass.data.get(DOMAIN, {}).get(config_entry.entry_id, {}).get("radio_lifecycle")
    return lifecycle is not None and lifecycle.can_remove(device_entry)

PLATFORMS: list[Platform] = [
    Platform.UPDATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.NUMBER,
]

SERVICE_CHECK_PLUGIN_UPDATES = "check_plugin_updates"
SERVICE_UPDATE_PLUGIN = "update_plugin"
SERVICE_UPDATE_ALL_PLUGINS = "update_all_plugins"
SERVICE_PING_NEIGHBOR = "ping_neighbor"
SERVICE_SEND_ADVERT = "send_advert"
SERVICE_PUBLISH_NEIGHBORS = "publish_neighbors"
SERVICE_GET_NEIGHBOR_SCOPES = "get_neighbor_scopes"
SERVICE_QUERY_NEIGHBOR_SCOPES = "query_neighbor_scopes"
SERVICE_ROOM_POST_MESSAGE = "room_post_message"
SERVICE_ROOM_MESSAGES_CLEAR = "room_messages_clear"
SERVICE_CAD_CALIBRATION_START = "cad_calibration_start"
SERVICE_CAD_CALIBRATION_STOP = "cad_calibration_stop"
SERVICE_CAD_MANUAL_CHECK = "cad_manual_check"
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
SERVICE_GET_BROKER_PRESETS = "get_broker_presets"
SERVICE_GET_RECENT_PACKETS = "get_recent_packets"
SERVICE_GET_FILTERED_PACKETS = "get_filtered_packets"
SERVICE_GET_PACKET_BY_HASH = "get_packet_by_hash"
SERVICE_GET_NEIGHBOR_LINKS = "get_neighbor_links"
SERVICE_GET_NEIGHBOR_LINK_HISTORY = "get_neighbor_link_history"
SERVICE_GET_RADIO_PACKET_RATES = "get_radio_packet_rates"
SERVICE_GET_NOISE_FLOOR_STATS = "get_noise_floor_stats"
SERVICE_GET_CRC_ERROR_COUNT = "get_crc_error_count"
SERVICE_GET_COMPANION_STATS = "get_companion_stats"
SERVICE_GET_LBT_DIAGNOSTICS = "get_lbt_diagnostics"
SERVICE_GET_ADVERTS_BY_CONTACT_TYPE = "get_adverts_by_contact_type"
SERVICE_GET_ADVERTS_COUNT_BY_CONTACT_TYPE = "get_adverts_count_by_contact_type"
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
    """Set up openHop Repeater from a config entry."""
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

    lifecycle = RadioLifecycle(hass, entry, coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "radio_lifecycle": lifecycle,
        "unsub_options_listener": entry.add_update_listener(_async_update_listener),
    }

    lifecycle.async_start()
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
        raise HomeAssistantError("No openHop Repeater entries are loaded")

    requested = service_data.get(CONF_ENTRY_ID) or service_data.get(LEGACY_CONF_ENTRY_ID)
    if requested:
        if requested not in entries:
            raise HomeAssistantError(f"Unknown openHop Repeater entry_id: {requested}")
        return requested

    if len(entries) == 1:
        return next(iter(entries))

    raise HomeAssistantError(
        "Multiple openHop Repeater entries are configured; provide entry_id"
    )


async def _async_refresh_entry(hass: HomeAssistant, entry_id: str) -> None:
    entry_data = hass.data[DOMAIN][entry_id]
    await entry_data["coordinator"].async_request_refresh()


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain services for advanced operations."""
    if hass.services.has_service(DOMAIN, SERVICE_PING_NEIGHBOR):
        return

    def _bounded_query_integer(minimum: int, maximum: int) -> Callable:
        """Use the client's strict finite bounds in action schemas too."""
        def validate(value: Any) -> int:
            try:
                return PyMCRepeaterApiClient.validate_query_integer(value, minimum, maximum)
            except PyMCRepeaterError as err:
                raise vol.Invalid(str(err)) from err
        return validate


    def _radio_id(value: Any) -> str:
        """Validate exact radio identity without coercion."""
        try:
            return PyMCRepeaterApiClient.validate_radio_id(value)
        except PyMCRepeaterError as err:
            raise vol.Invalid(str(err)) from err

    async def _with_api(
        call: ServiceCall,
        func: Callable[[PyMCRepeaterApiClient, str], Awaitable[Any]],
        *,
        refresh: bool = True,
    ) -> None:
        entry_id = _resolve_entry_id(hass, call.data)
        api: PyMCRepeaterApiClient = hass.data[DOMAIN][entry_id]["api"]
        try:
            await func(api, entry_id)
        except PyMCRepeaterError as err:
            raise HomeAssistantError(str(err)) from err
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
        try:
            result = await func(api, entry_id)
        except PyMCRepeaterError as err:
            raise HomeAssistantError(str(err)) from err
        if refresh:
            await _async_refresh_entry(hass, entry_id)
        if not always_return and not getattr(call, "return_response", False):
            return None
        if isinstance(result, dict):
            return result
        return {"result": result}

    def _async_service_handler(
        handler: Callable[[ServiceCall], Awaitable[Any]],
    ) -> Callable[[ServiceCall], Awaitable[Any]]:
        """Expose native async handlers so HA awaits work on its event loop."""
        async def async_handle(call: ServiceCall) -> Any:
            return await handler(call)

        return async_handle

    def _plugin_text(value: Any) -> str:
        try:
            return PyMCRepeaterApiClient.validate_plugin_text(value)
        except PyMCRepeaterError as err:
            raise vol.Invalid(str(err)) from err

    def _management_object(value: Any) -> dict[str, Any]:
        try:
            return PyMCRepeaterApiClient.validate_json_object(value)
        except PyMCRepeaterError as err:
            raise vol.Invalid(str(err)) from err

    def _management_validator(method: str) -> Callable:
        def validate(value: Any) -> Any:
            try:
                return getattr(PyMCRepeaterApiClient, method)(value)
            except PyMCRepeaterError as err:
                raise vol.Invalid(str(err)) from err
        return validate

    hass.services.async_register(
        DOMAIN, "set_acl_permissions",
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_set_acl_permissions(
            identity_name=call.data["identity_name"], client_pubkey=call.data["client_pubkey"],
            permissions=call.data["permissions"]), refresh=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str,
                           vol.Required("identity_name"): _management_validator("validate_management_name"),
                           vol.Required("client_pubkey"): _management_validator("validate_acl_public_key"),
                           vol.Required("permissions"): _management_validator("validate_acl_permissions")}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    def _sensor_configuration(value: Any) -> dict[str, Any]:
        try:
            return PyMCRepeaterApiClient.validate_sensor_configuration(value)
        except PyMCRepeaterError as err:
            raise vol.Invalid(str(err)) from err

    hass.services.async_register(
        DOMAIN, "get_sensor_types",
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_get_sensor_types(), always_return=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str}), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "get_sensor_configuration",
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_get_sensor_configuration(
            include_sensitive=call.data.get("include_sensitive", False)), always_return=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str,
                           vol.Optional("include_sensitive", default=False): bool}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "update_sensor_configuration",
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_update_sensor_configuration(
            config=call.data["config"]), always_return=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str, vol.Required("config"): _sensor_configuration}),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN, "get_plugin_settings",
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_get_plugin_settings(
            plugin_id=call.data["plugin_id"], include_sensitive=call.data.get("include_sensitive", False)),
            always_return=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str, vol.Required("plugin_id"): _plugin_text,
                           vol.Optional("include_sensitive", default=False): bool}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "update_plugin_settings",
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_update_plugin_settings(
            plugin_id=call.data["plugin_id"], config=call.data["config"], restart=call.data.get("restart", False)),
            always_return=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str, vol.Required("plugin_id"): _plugin_text,
                           vol.Required("config"): _management_object,
                           vol.Optional("restart", default=False): bool}),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN, "get_plugin_catalogue",
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_get_plugin_catalogue(
            force_refresh=call.data.get("force_refresh", False)), always_return=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str,
                           vol.Optional("force_refresh", default=False): bool}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "install_catalogue_plugin",
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_install_catalogue_plugin(
            plugin_id=call.data["plugin_id"], version=call.data.get("version"),
            force_refresh=call.data.get("force_refresh", False)), always_return=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str,
                           vol.Required("plugin_id"): _plugin_text,
                           vol.Optional("version"): _plugin_text,
                           vol.Optional("force_refresh", default=False): bool}),
        supports_response=SupportsResponse.ONLY,
    )

    for operation in ("enable", "disable", "start", "stop", "restart", "uninstall"):
        fields = {vol.Optional(CONF_ENTRY_ID): str, vol.Required("plugin_id"): _plugin_text}
        if operation == "uninstall":
            fields[vol.Optional("delete_data", default=False)] = bool
        hass.services.async_register(
            DOMAIN, operation + "_plugin",
            _async_service_handler(lambda call, operation=operation: _with_api_response(
                call, lambda api, _: api.async_plugin_lifecycle(
                    plugin_id=call.data["plugin_id"], operation=operation,
                    delete_data=call.data.get("delete_data", False)), always_return=True)),
            schema=vol.Schema(fields), supports_response=SupportsResponse.ONLY,
        )

    hass.services.async_register(
        DOMAIN, SERVICE_CHECK_PLUGIN_UPDATES,
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_check_plugin_updates(
            plugin_id=call.data.get("plugin_id"), force_refresh=call.data.get("force_refresh", False)),
            always_return=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str,
                           vol.Optional("plugin_id"): _plugin_text,
                           vol.Optional("force_refresh", default=False): bool}),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_PLUGIN,
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_update_plugin(
            plugin_id=call.data["plugin_id"], version=call.data.get("version"),
            force_refresh=call.data.get("force_refresh", False)), always_return=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str,
                           vol.Required("plugin_id"): _plugin_text,
                           vol.Optional("version"): _plugin_text,
                           vol.Optional("force_refresh", default=False): bool}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_ALL_PLUGINS,
        _async_service_handler(lambda call: _with_api_response(call, lambda api, _: api.async_update_all_plugins(
            force_refresh=call.data.get("force_refresh", False)), always_return=True)),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str,
                           vol.Optional("force_refresh", default=False): bool}),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PING_NEIGHBOR,
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_ping_neighbor(
                target_id=call.data["target_id"],
                timeout=call.data.get("timeout", 10),
            ),
            refresh=False,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("target_id"): str,
                vol.Optional("timeout", default=10): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=60)
                ),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_ADVERT,
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_send_advert(call.data.get("mode", "flood")),
            refresh=False,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("mode", default="flood"): vol.In(["flood", "direct"]),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PUBLISH_NEIGHBORS,
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_publish_neighbors(),
            refresh=True,
        )),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_NEIGHBOR_SCOPES,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_neighbor_scopes(),
            always_return=True,
        )),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str}),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_QUERY_NEIGHBOR_SCOPES,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_query_neighbor_scopes(call.data["pubkey"]),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("pubkey"): vol.Match(r"(?i)^[0-9a-f]{64}$"),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ROOM_POST_MESSAGE,
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_room_post_message(
                room_name=call.data.get("room_name"),
                room_hash=call.data.get("room_hash"),
                message=call.data["message"],
                author_pubkey=call.data.get("author_pubkey", "server"),
                txt_type=call.data.get("txt_type", 0),
            ),
            refresh=False,
        )),
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
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_room_messages_clear(
                room_name=call.data.get("room_name"),
                room_hash=call.data.get("room_hash"),
            ),
            refresh=False,
        )),
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
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_cad_calibration_start(
                samples=call.data.get("samples", 8),
                delay=call.data.get("delay", 100),
                known_signal_present=call.data.get("known_signal_present", False),
                cad_symbol_num=call.data.get("cad_symbol_num", 2),
                cad_timeout_ms=call.data.get("cad_timeout_ms", 500),
            ),
            refresh=False,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("samples", default=8): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=64)
                ),
                vol.Optional("delay", default=100): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=2000)
                ),
                vol.Optional("known_signal_present", default=False): bool,
                vol.Optional("cad_symbol_num", default=2): vol.All(
                    vol.Coerce(int), vol.In([1, 2, 4, 8, 16])
                ),
                vol.Optional("cad_timeout_ms", default=500): vol.All(
                    vol.Coerce(int), vol.Range(min=50, max=5000)
                ),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAD_CALIBRATION_STOP,
        _async_service_handler(lambda call: _with_api(
            call, lambda api, _: api.async_cad_calibration_stop(), refresh=False
        )),
        schema=vol.Schema({vol.Optional(CONF_ENTRY_ID): str}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAD_MANUAL_CHECK,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_cad_manual_check(
                samples=call.data.get("samples", 1),
                det_peak=call.data.get("det_peak"),
                det_min=call.data.get("det_min"),
                cad_symbol_num=call.data.get("cad_symbol_num"),
                cad_timeout_ms=call.data.get("cad_timeout_ms", 500),
                apply_live=call.data.get("apply_live", False),
            ),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("samples", default=1): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=32)
                ),
                vol.Optional("det_peak"): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=255)
                ),
                vol.Optional("det_min"): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=255)
                ),
                vol.Optional("cad_symbol_num"): vol.All(
                    vol.Coerce(int), vol.In([1, 2, 4, 8, 16])
                ),
                vol.Optional("cad_timeout_ms", default=500): vol.All(
                    vol.Coerce(int), vol.Range(min=50, max=5000)
                ),
                vol.Optional("apply_live", default=False): bool,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_CAD_SETTINGS,
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_save_cad_settings(
                peak=call.data["peak"],
                min_val=call.data["min_val"],
                cad_symbol_num=call.data.get("cad_symbol_num", 2),
                detection_rate=call.data.get("detection_rate", 0),
            ),
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("peak"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
                vol.Required("min_val"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
                vol.Optional("cad_symbol_num", default=2): vol.All(
                    vol.Coerce(int), vol.In([1, 2, 4, 8, 16])
                ),
                vol.Optional("detection_rate", default=0): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=255)
                ),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DB_PURGE,
        _async_service_handler(lambda call: _with_api(
            call, lambda api, _: api.async_db_purge(call.data["tables"])
        )),
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
        _async_service_handler(lambda call: _with_api(
            call, lambda api, _: api.async_update_radio_config(call.data["payload"])
        )),
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
        _async_service_handler(lambda call: _with_api(
            call, lambda api, _: api.async_update_mqtt_config(call.data["payload"])
        )),
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
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_send_text(
                pub_key=call.data["pub_key"],
                text=call.data["text"],
                txt_type=call.data.get("txt_type", 0),
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        )),
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
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_send_channel_message(
                channel_idx=call.data["channel_idx"],
                text=call.data["text"],
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        )),
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
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_login(
                pub_key=call.data["pub_key"],
                password=call.data.get("password", ""),
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        )),
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
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_companion_request_status(
                pub_key=call.data["pub_key"],
                timeout=call.data.get("timeout", 15.0),
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("pub_key"): str,
                vol.Optional("timeout", default=15.0): vol.All(
                    vol.Coerce(float), vol.Range(min=1, max=120)
                ),
                vol.Optional("companion_name"): str,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_REQUEST_TELEMETRY,
        _async_service_handler(lambda call: _with_api_response(
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
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("pub_key"): str,
                vol.Optional("timeout", default=20.0): vol.All(
                    vol.Coerce(float), vol.Range(min=1, max=120)
                ),
                vol.Optional("companion_name"): str,
                vol.Optional("want_base", default=True): bool,
                vol.Optional("want_location", default=True): bool,
                vol.Optional("want_environment", default=True): bool,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPANION_SEND_COMMAND,
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_send_command(
                pub_key=call.data["pub_key"],
                command=call.data["command"],
                parameters=call.data.get("parameters"),
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        )),
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
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_reset_path(
                pub_key=call.data["pub_key"],
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        )),
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
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_set_advert_name(
                advert_name=call.data["advert_name"],
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        )),
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
        _async_service_handler(lambda call: _with_api(
            call,
            lambda api, _: api.async_companion_set_advert_location(
                latitude=call.data["latitude"],
                longitude=call.data["longitude"],
                companion_name=call.data.get("companion_name"),
            ),
            refresh=False,
        )),
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
        SERVICE_GET_BROKER_PRESETS,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_broker_presets(),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_LOGS,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_logs(),
            always_return=True,
        )),
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
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_recent_packets(
                limit=call.data.get("limit", 100),
            ),
            always_return=True,
        )),
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
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_filtered_packets(
                packet_type=call.data.get("packet_type"),
                route=call.data.get("route"),
                start_timestamp=call.data.get("start_timestamp"),
                end_timestamp=call.data.get("end_timestamp"),
                limit=call.data.get("limit", 1000),
            ),
            always_return=True,
        )),
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
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_packet_by_hash(call.data["packet_hash"]),
            always_return=True,
        )),
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
        SERVICE_GET_NEIGHBOR_LINKS,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_neighbor_links(
                active_within_seconds=call.data.get("active_within_seconds", 90),
                limit=call.data.get("limit", 500),
            ),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("active_within_seconds", default=90): vol.All(
                    vol.Coerce(int), vol.Range(min=1)
                ),
                vol.Optional("limit", default=500): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=5000)
                ),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_NEIGHBOR_LINK_HISTORY,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_neighbor_link_history(
                peer_hash=call.data["peer_hash"],
                path_hash_size=call.data["path_hash_size"],
                hours=call.data.get("hours", 24),
                limit=call.data.get("limit", 1000),
                bucket_seconds=call.data.get("bucket_seconds"),
                radio_id=call.data.get("radio_id"),
                by_radio=call.data.get("by_radio"),
            ),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("peer_hash"): str,
                vol.Optional("bucket_seconds"): _bounded_query_integer(60, 86400),
                vol.Optional("radio_id"): _radio_id,
                vol.Optional("by_radio"): bool,
                vol.Required("path_hash_size"): _bounded_query_integer(1, 3),
                vol.Optional("hours", default=24): _bounded_query_integer(1, 168),
                vol.Optional("limit", default=1000): _bounded_query_integer(1, 5000),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ADVERTS_BY_CONTACT_TYPE,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_adverts_by_contact_type(
                contact_type=call.data["contact_type"],
                limit=call.data.get("limit", 100),
                offset=call.data.get("offset", 0),
                hours=call.data.get("hours"),
            ),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("contact_type"): str,
                vol.Optional("limit", default=100): vol.Coerce(int),
                vol.Optional("offset", default=0): vol.Coerce(int),
                vol.Optional("hours"): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ADVERTS_COUNT_BY_CONTACT_TYPE,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_adverts_count_by_contact_type(
                contact_type=call.data["contact_type"],
                hours=call.data.get("hours"),
            ),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("contact_type"): str,
                vol.Optional("hours"): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ACL_CLIENTS,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_acl_clients(
                identity_hash=call.data.get("identity_hash"),
                identity_name=call.data.get("identity_name"),
            ),
            always_return=True,
        )),
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
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_remove_acl_client(
                public_key=call.data["public_key"],
                identity_hash=call.data.get("identity_hash"),
                identity_name=call.data.get("identity_name"),
            ),
            refresh=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Required("public_key"): str,
                vol.Optional("identity_hash"): str,
                vol.Optional("identity_name"): _management_validator("validate_management_name"),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ROOM_MESSAGES,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_room_messages(
                room_name=call.data.get("room_name"),
                room_hash=call.data.get("room_hash"),
                limit=call.data.get("limit", 50),
                offset=call.data.get("offset", 0),
                since_timestamp=call.data.get("since_timestamp"),
            ),
            always_return=True,
        )),
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
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_room_clients(
                room_name=call.data.get("room_name"),
                room_hash=call.data.get("room_hash"),
            ),
            always_return=True,
        )),
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
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_delete_room_message(
                message_id=call.data["message_id"],
                room_name=call.data.get("room_name"),
                room_hash=call.data.get("room_hash"),
            ),
            refresh=True,
        )),
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

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_RADIO_PACKET_RATES,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_radio_packet_rates(
                hours=call.data.get("hours", 24),
                bucket_seconds=call.data.get("bucket_seconds"),
            ),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("hours", default=24): _bounded_query_integer(1, 168),
                vol.Optional("bucket_seconds"): _bounded_query_integer(60, 86400),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_NOISE_FLOOR_STATS,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_noise_floor_stats(
                hours=call.data.get("hours", 24),
                radio_id=call.data.get("radio_id"),
            ),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("hours", default=24): _bounded_query_integer(1, 168),
                vol.Optional("radio_id"): _radio_id,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CRC_ERROR_COUNT,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_crc_error_count(
                hours=call.data.get("hours", 24),
                radio_id=call.data.get("radio_id"),
            ),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("hours", default=24): _bounded_query_integer(1, 168),
                vol.Optional("radio_id"): _radio_id,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_COMPANION_STATS,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_companion_stats(
                type=call.data.get("type", "packets"),
                companion_name=call.data.get("companion_name"),
            ),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("type", default="packets"): vol.In(["core", "radio", "packets"]),
                vol.Optional("companion_name"): vol.All(str, vol.Length(min=1)),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_LBT_DIAGNOSTICS,
        _async_service_handler(lambda call: _with_api_response(
            call,
            lambda api, _: api.async_get_lbt_diagnostics(
                hours=call.data.get("hours", 24),
                bucket_seconds=call.data.get("bucket_seconds"),
                severe_attempt_threshold=call.data.get("severe_attempt_threshold"),
            ),
            always_return=True,
        )),
        schema=vol.Schema(
            {
                vol.Optional(CONF_ENTRY_ID): str,
                vol.Optional("hours", default=24): _bounded_query_integer(1, 168),
                vol.Optional("bucket_seconds"): _bounded_query_integer(60, 3600),
                vol.Optional("severe_attempt_threshold"): _bounded_query_integer(2, 16),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
