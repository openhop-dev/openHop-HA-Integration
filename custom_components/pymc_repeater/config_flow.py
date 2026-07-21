"""Config flow for openHop Repeater."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .api import (
    PyMCRepeaterApiClient,
    PyMCRepeaterApiError,
    PyMCRepeaterAuthenticationError,
    PyMCRepeaterCannotConnect,
    build_home_assistant_token_name,
    normalize_host,
)
from .const import (
    CONF_API_TOKEN,
    CONF_DATA_SIZE_UNIT,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN_ID,
    CONF_TOKEN_NAME,
    CONF_UPTIME_UNIT,
    DATA_SIZE_UNITS,
    DEFAULT_DATA_SIZE_UNIT,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DEFAULT_UPTIME_UNIT,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
    UPTIME_UNITS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


def _get_home_assistant_hostname(hass: HomeAssistant) -> str | None:
    """Return the best available Home Assistant hostname for token labeling."""
    try:
        return normalize_host(get_url(hass))
    except NoURLAvailableError:
        return None


async def _async_validate_and_bootstrap(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate config flow data against the repeater."""
    session = async_get_clientsession(hass)
    client = PyMCRepeaterApiClient(
        session=session,
        host=normalize_host(user_input[CONF_HOST]),
        port=user_input[CONF_PORT],
    )
    home_assistant_hostname = _get_home_assistant_hostname(hass)
    result = await client.async_bootstrap(
        user_input[CONF_PASSWORD],
        home_assistant_hostname=home_assistant_hostname,
    )
    return {
        "title": result.title,
        "data": {
            CONF_HOST: client.host,
            CONF_PORT: client.port,
            CONF_API_TOKEN: result.api_token,
            CONF_TOKEN_ID: result.token_id,
            CONF_TOKEN_NAME: result.token_name
            or build_home_assistant_token_name(home_assistant_hostname),
        },
    }


class PyMCRepeaterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for openHop Repeater."""

    VERSION = 1

    _reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            normalized_host = normalize_host(user_input[CONF_HOST])
            unique_id = f"{normalized_host}:{int(user_input[CONF_PORT])}"

            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                info = await _async_validate_and_bootstrap(
                    self.hass,
                    {**user_input, CONF_HOST: normalized_host},
                )
            except PyMCRepeaterCannotConnect:
                errors["base"] = "cannot_connect"
            except PyMCRepeaterAuthenticationError:
                errors["base"] = "invalid_auth"
            except PyMCRepeaterApiError:
                errors["base"] = "api_error"
            except Exception:  # pragma: no cover - defensive
                _LOGGER.exception("Unexpected exception during config flow")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=info["data"])

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> FlowResult:
        """Start reauthentication."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm reauth with a fresh admin password."""
        errors: dict[str, str] = {}

        if self._reauth_entry is None:
            return self.async_abort(reason="unknown")

        if user_input is not None:
            try:
                info = await _async_validate_and_bootstrap(
                    self.hass,
                    {
                        CONF_HOST: self._reauth_entry.data[CONF_HOST],
                        CONF_PORT: self._reauth_entry.data[CONF_PORT],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
            except PyMCRepeaterCannotConnect:
                errors["base"] = "cannot_connect"
            except PyMCRepeaterAuthenticationError:
                errors["base"] = "invalid_auth"
            except PyMCRepeaterApiError:
                errors["base"] = "api_error"
            except Exception:  # pragma: no cover - defensive
                _LOGGER.exception("Unexpected exception during reauth")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    title=info["title"],
                    data={**self._reauth_entry.data, **info["data"]},
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return PyMCRepeaterOptionsFlow(config_entry)


class PyMCRepeaterOptionsFlow(config_entries.OptionsFlow):
    """Handle openHop Repeater options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_unit = self._config_entry.options.get(CONF_UPTIME_UNIT, DEFAULT_UPTIME_UNIT)
        current_data_size_unit = self._config_entry.options.get(
            CONF_DATA_SIZE_UNIT, DEFAULT_DATA_SIZE_UNIT
        )
        current_scan_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_DATA_SIZE_UNIT, default=current_data_size_unit): vol.In(
                    DATA_SIZE_UNITS
                ),
                vol.Required(CONF_UPTIME_UNIT, default=current_unit): vol.In(UPTIME_UNITS),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current_scan_interval,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_SCAN_INTERVAL_SECONDS,
                        max=MAX_SCAN_INTERVAL_SECONDS,
                    ),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
