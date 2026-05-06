"""Async API client for pyMC Repeater."""

from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from aiohttp import ClientError, ClientResponse, ClientSession
from yarl import URL

from .const import CLIENT_ID_PREFIX, DEFAULT_PACKET_WINDOW_HOURS

REQUEST_TIMEOUT = 10


class PyMCRepeaterError(Exception):
    """Base error for the pyMC Repeater client."""


class PyMCRepeaterCannotConnect(PyMCRepeaterError):
    """Raised when the repeater cannot be reached."""


class PyMCRepeaterAuthenticationError(PyMCRepeaterError):
    """Raised when login or token auth fails."""


class PyMCRepeaterApiError(PyMCRepeaterError):
    """Raised when the repeater returns an unexpected API error."""


@dataclass(slots=True)
class BootstrapResult:
    """Config flow bootstrap result."""

    title: str
    api_token: str
    token_id: int | None
    token_name: str
    stats: dict[str, Any]


def get_repeater_name_from_stats(stats: dict[str, Any]) -> str | None:
    """Extract the best repeater name from a stats payload."""
    if not isinstance(stats, dict):
        return None

    candidates = (
        stats.get("node_name"),
        stats.get("name"),
        ((stats.get("config") or {}).get("node_name") if isinstance(stats.get("config"), dict) else None),
        (
            (((stats.get("config") or {}).get("repeater") or {}).get("node_name"))
            if isinstance((stats.get("config") or {}).get("repeater"), dict)
            else None
        ),
    )

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    return None


def normalize_host(value: str) -> str:
    """Normalize host/user input for the repeater address."""
    raw = value.strip()
    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.hostname:
            return parsed.hostname
    return raw.rstrip("/")


def build_home_assistant_token_name(home_assistant_hostname: str | None = None) -> str:
    """Build the pyMC API token label for this Home Assistant instance."""
    hostname = (home_assistant_hostname or "").strip() or socket.gethostname()
    return f"Home Assistant ({hostname})"


class PyMCRepeaterApiClient:
    """HTTP client for pyMC Repeater."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        port: int,
        api_token: str | None = None,
    ) -> None:
        self._session = session
        self.host = normalize_host(host)
        self.port = int(port)
        self.api_token = api_token

    @property
    def base_url(self) -> str:
        """Return the repeater base URL."""
        return str(URL.build(scheme="http", host=self.host, port=self.port))

    async def async_bootstrap(
        self, admin_password: str, home_assistant_hostname: str | None = None
    ) -> BootstrapResult:
        """Log in with the admin password, create an API token, and fetch stats."""
        client_id = self._build_client_id()
        jwt = await self._async_login(admin_password, client_id)
        token_name = build_home_assistant_token_name(home_assistant_hostname)
        token_data = await self._async_create_token(jwt, token_name)
        self.api_token = token_data["token"]
        stats = await self.async_get_stats()
        title = get_repeater_name_from_stats(stats) or f"{self.host}:{self.port}"
        return BootstrapResult(
            title=title,
            api_token=token_data["token"],
            token_id=token_data.get("token_id"),
            token_name=token_name,
            stats=stats,
        )

    async def async_fetch_all(self) -> dict[str, Any]:
        """Fetch the main endpoint set used by the integration."""
        endpoints = {
            "stats": self.async_get_stats(),
            "hardware_stats": self.async_get_hardware_stats(),
            "hardware_processes": self.async_get_hardware_processes(),
            "mqtt_status": self.async_get_mqtt_status(),
            "packet_stats": self.async_get_packet_stats(),
            "route_stats": self.async_get_route_stats(),
            "noise_floor_stats": self.async_get_noise_floor_stats(),
            "crc_error_count": self.async_get_crc_error_count(),
            "advert_rate_limit_stats": self.async_get_advert_rate_limit_stats(),
            "acl_stats": self.async_get_acl_stats(),
            "acl_info": self.async_get_acl_info(),
            "identities": self.async_get_identities(),
            "db_stats": self.async_get_db_stats(),
            "transport_keys": self.async_get_transport_keys(),
            "room_stats": self.async_get_room_stats(),
            "update_status": self.async_get_update_status(),
            "update_channels": self.async_get_update_channels(),
            "companions": self.async_get_companions(),
            "gps": self.async_get_gps(),
        }

        results = await asyncio.gather(*endpoints.values(), return_exceptions=True)
        payload: dict[str, Any] = {}

        for key, result in zip(endpoints, results, strict=True):
            if isinstance(result, PyMCRepeaterAuthenticationError):
                raise result
            if isinstance(result, PyMCRepeaterCannotConnect):
                raise result
            if isinstance(result, Exception):
                payload[key] = {"error": str(result)}
                continue
            payload[key] = result

        return payload

    async def async_get_stats(self) -> dict[str, Any]:
        """Return the base repeater stats payload."""
        return await self._async_request_json("GET", "/api/stats", auth="api_token")

    async def async_get_hardware_stats(self) -> dict[str, Any]:
        """Return hardware stats."""
        return await self._async_request_wrapped("GET", "/api/hardware_stats")

    async def async_get_mqtt_status(self) -> dict[str, Any]:
        """Return MQTT status."""
        return await self._async_request_wrapped("GET", "/api/mqtt_status")

    async def async_get_hardware_processes(self) -> dict[str, Any]:
        """Return process summary stats."""
        return await self._async_request_wrapped("GET", "/api/hardware_processes")

    async def async_get_packet_stats(self) -> dict[str, Any]:
        """Return packet stats."""
        return await self._async_request_wrapped(
            "GET",
            "/api/packet_stats",
            params={"hours": DEFAULT_PACKET_WINDOW_HOURS},
        )

    async def async_get_route_stats(self) -> dict[str, Any]:
        """Return route stats."""
        return await self._async_request_wrapped(
            "GET",
            "/api/route_stats",
            params={"hours": DEFAULT_PACKET_WINDOW_HOURS},
        )

    async def async_get_noise_floor_stats(self) -> dict[str, Any]:
        """Return noise floor stats."""
        payload = await self._async_request_wrapped(
            "GET",
            "/api/noise_floor_stats",
            params={"hours": DEFAULT_PACKET_WINDOW_HOURS},
        )
        return payload.get("stats", payload)

    async def async_get_crc_error_count(self) -> dict[str, Any]:
        """Return CRC error count."""
        return await self._async_request_wrapped(
            "GET",
            "/api/crc_error_count",
            params={"hours": DEFAULT_PACKET_WINDOW_HOURS},
        )

    async def async_get_advert_rate_limit_stats(self) -> dict[str, Any]:
        """Return advert rate limiting stats."""
        return await self._async_request_wrapped("GET", "/api/advert_rate_limit_stats")

    async def async_get_acl_stats(self) -> dict[str, Any]:
        """Return ACL stats."""
        return await self._async_request_wrapped("GET", "/api/acl_stats")

    async def async_get_acl_info(self) -> dict[str, Any]:
        """Return detailed ACL info."""
        return await self._async_request_wrapped("GET", "/api/acl_info")

    async def async_get_identities(self) -> dict[str, Any]:
        """Return identity stats."""
        return await self._async_request_wrapped("GET", "/api/identities")

    async def async_get_db_stats(self) -> dict[str, Any]:
        """Return database stats."""
        return await self._async_request_wrapped("GET", "/api/db_stats")

    async def async_get_transport_keys(self) -> list[dict[str, Any]]:
        """Return transport keys."""
        return await self._async_request_wrapped("GET", "/api/transport_keys")

    async def async_get_room_stats(self) -> dict[str, Any]:
        """Return room server stats."""
        return await self._async_request_wrapped("GET", "/api/room_stats")

    async def async_get_update_status(self) -> dict[str, Any]:
        """Return repeater update status."""
        return await self._async_request_wrapped("GET", "/api/update/status")

    async def async_get_update_channels(self) -> dict[str, Any]:
        """Return available repeater update channels."""
        return await self._async_request_wrapped("GET", "/api/update/channels")

    async def async_get_companions(self) -> list[dict[str, Any]]:
        """Return configured companion bridge summaries."""
        return await self._async_request_wrapped("GET", "/api/companion/")

    async def async_get_gps(self) -> dict[str, Any]:
        """Return local GPS receiver diagnostics."""
        return await self._async_request_wrapped("GET", "/api/gps")

    async def async_open_gps_stream(self) -> ClientResponse:
        """Open the GPS SSE stream."""
        return await self._async_open_stream("GET", "/api/gps_stream")

    async def async_get_logs(self) -> dict[str, Any]:
        """Return buffered repeater logs."""
        payload = await self._async_request_json("GET", "/api/logs", auth="api_token")
        if payload.get("error"):
            raise PyMCRepeaterApiError(str(payload["error"]))
        return {"logs": payload.get("logs", [])}

    async def async_get_recent_packets(self, limit: int = 100) -> dict[str, Any]:
        """Return recent packet history."""
        payload = await self._async_request_json(
            "GET",
            "/api/recent_packets",
            params={"limit": limit},
            auth="api_token",
        )
        if payload.get("success") is False:
            raise PyMCRepeaterApiError(
                payload.get("error", "Failed to fetch recent packets")
            )
        packets = payload.get("data", [])
        return {"packets": packets, "count": payload.get("count", len(packets))}

    async def async_get_filtered_packets(
        self,
        *,
        packet_type: int | None = None,
        route: int | None = None,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Return filtered packet history."""
        params: dict[str, Any] = {"limit": limit}
        if packet_type is not None:
            params["type"] = packet_type
        if route is not None:
            params["route"] = route
        if start_timestamp is not None:
            params["start_timestamp"] = start_timestamp
        if end_timestamp is not None:
            params["end_timestamp"] = end_timestamp

        payload = await self._async_request_json(
            "GET",
            "/api/filtered_packets",
            params=params,
            auth="api_token",
        )
        if payload.get("success") is False:
            raise PyMCRepeaterApiError(
                payload.get("error", "Failed to fetch filtered packets")
            )
        packets = payload.get("data", [])
        return {
            "packets": packets,
            "count": payload.get("count", len(packets)),
            "filters": payload.get("filters"),
        }

    async def async_get_packet_by_hash(self, packet_hash: str) -> dict[str, Any]:
        """Return one stored packet by packet hash."""
        payload = await self._async_request_json(
            "GET",
            "/api/packet_by_hash",
            params={"packet_hash": packet_hash},
            auth="api_token",
        )
        if payload.get("success") is False:
            raise PyMCRepeaterApiError(
                payload.get("error", f"Failed to fetch packet {packet_hash}")
            )
        return {"packet": payload.get("data")}

    async def async_get_acl_clients(
        self,
        *,
        identity_hash: str | None = None,
        identity_name: str | None = None,
    ) -> dict[str, Any]:
        """Return authenticated ACL client details."""
        params: dict[str, Any] = {}
        if identity_hash:
            params["identity_hash"] = identity_hash
        if identity_name:
            params["identity_name"] = identity_name
        return await self._async_request_wrapped("GET", "/api/acl_clients", params=params)

    async def async_remove_acl_client(
        self,
        *,
        public_key: str,
        identity_hash: str | None = None,
    ) -> dict[str, Any]:
        """Remove an authenticated client from one or more ACLs."""
        payload: dict[str, Any] = {"public_key": public_key}
        if identity_hash:
            payload["identity_hash"] = identity_hash
        return await self._async_request_wrapped(
            "POST",
            "/api/acl_remove_client",
            json_body=payload,
        )

    async def async_get_room_messages(
        self,
        *,
        room_name: str | None = None,
        room_hash: str | None = None,
        limit: int = 50,
        offset: int = 0,
        since_timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Return stored room messages."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if room_name:
            params["room_name"] = room_name
        if room_hash:
            params["room_hash"] = room_hash
        if since_timestamp is not None:
            params["since_timestamp"] = since_timestamp
        return await self._async_request_wrapped("GET", "/api/room_messages", params=params)

    async def async_get_room_clients(
        self, *, room_name: str | None = None, room_hash: str | None = None
    ) -> dict[str, Any]:
        """Return synced room clients."""
        params: dict[str, Any] = {}
        if room_name:
            params["room_name"] = room_name
        if room_hash:
            params["room_hash"] = room_hash
        return await self._async_request_wrapped("GET", "/api/room_clients", params=params)

    async def async_delete_room_message(
        self,
        *,
        message_id: int,
        room_name: str | None = None,
        room_hash: str | None = None,
    ) -> dict[str, Any]:
        """Delete one room message."""
        params: dict[str, Any] = {"message_id": message_id}
        if room_name:
            params["room_name"] = room_name
        if room_hash:
            params["room_hash"] = room_hash
        return await self._async_request_wrapped("DELETE", "/api/room_message", params=params)

    async def async_send_advert(self) -> Any:
        """Trigger a repeater advert send."""
        return await self._async_request_wrapped("POST", "/api/send_advert", json_body={})

    async def async_restart_service(self) -> dict[str, Any]:
        """Restart the repeater service."""
        payload = await self._async_request_json(
            "POST", "/api/restart_service", json_body={}, auth="api_token"
        )
        if payload.get("success") is False:
            raise PyMCRepeaterApiError(payload.get("error", "Failed to restart service"))
        return payload

    async def async_set_mode(self, mode: str) -> dict[str, Any]:
        """Set repeater mode."""
        payload = await self._async_request_json(
            "POST", "/api/set_mode", json_body={"mode": mode}, auth="api_token"
        )
        if payload.get("success") is False:
            raise PyMCRepeaterApiError(payload.get("error", "Failed to set mode"))
        return payload

    async def async_set_duty_cycle_enforcement(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable duty cycle enforcement."""
        payload = await self._async_request_json(
            "POST", "/api/set_duty_cycle", json_body={"enabled": enabled}, auth="api_token"
        )
        if payload.get("success") is False:
            raise PyMCRepeaterApiError(
                payload.get("error", "Failed to set duty cycle enforcement")
            )
        return payload

    async def async_update_duty_cycle_config(self, **kwargs: Any) -> Any:
        """Update duty cycle configuration."""
        return await self._async_request_wrapped(
            "POST", "/api/update_duty_cycle_config", json_body=kwargs
        )

    async def async_update_advert_rate_limit_config(self, **kwargs: Any) -> Any:
        """Update advert rate limit configuration."""
        return await self._async_request_wrapped(
            "POST", "/api/update_advert_rate_limit_config", json_body=kwargs
        )

    async def async_set_unscoped_flood_policy(
        self, unscoped_flood_allow: bool
    ) -> dict[str, Any]:
        """Update the unscoped flood policy."""
        return await self._async_request_wrapped(
            "POST",
            "/api/unscoped_flood_policy",
            json_body={"unscoped_flood_allow": unscoped_flood_allow},
        )

    async def async_db_vacuum(self) -> Any:
        """Vacuum the database."""
        return await self._async_request_wrapped("POST", "/api/db_vacuum", json_body={})

    async def async_db_purge(self, tables: str | list[str]) -> Any:
        """Purge one or more database tables."""
        return await self._async_request_wrapped(
            "POST", "/api/db_purge", json_body={"tables": tables}
        )

    async def async_ping_neighbor(self, target_id: str, timeout: int = 10) -> Any:
        """Ping a neighbor."""
        return await self._async_request_wrapped(
            "POST",
            "/api/ping_neighbor",
            json_body={"target_id": target_id, "timeout": timeout},
        )

    async def async_room_post_message(
        self,
        *,
        room_name: str | None = None,
        room_hash: str | None = None,
        message: str,
        author_pubkey: str = "server",
        txt_type: int = 0,
    ) -> Any:
        """Post a room message."""
        payload: dict[str, Any] = {
            "message": message,
            "author_pubkey": author_pubkey,
            "txt_type": txt_type,
        }
        if room_name:
            payload["room_name"] = room_name
        if room_hash:
            payload["room_hash"] = room_hash
        return await self._async_request_wrapped("POST", "/api/room_post_message", json_body=payload)

    async def async_room_messages_clear(
        self, *, room_name: str | None = None, room_hash: str | None = None
    ) -> Any:
        """Clear all room messages."""
        params: dict[str, Any] = {}
        if room_name:
            params["room_name"] = room_name
        if room_hash:
            params["room_hash"] = room_hash
        return await self._async_request_wrapped(
            "DELETE", "/api/room_messages_clear", params=params
        )

    async def async_cad_calibration_start(self, samples: int = 8, delay: int = 100) -> Any:
        """Start CAD calibration."""
        return await self._async_request_wrapped(
            "POST",
            "/api/cad_calibration_start",
            json_body={"samples": samples, "delay": delay},
        )

    async def async_cad_calibration_stop(self) -> Any:
        """Stop CAD calibration."""
        return await self._async_request_wrapped(
            "POST", "/api/cad_calibration_stop", json_body={}
        )

    async def async_save_cad_settings(
        self, *, peak: int, min_val: int, detection_rate: int = 0
    ) -> Any:
        """Save CAD settings."""
        return await self._async_request_wrapped(
            "POST",
            "/api/save_cad_settings",
            json_body={
                "peak": peak,
                "min_val": min_val,
                "detection_rate": detection_rate,
            },
        )

    async def async_update_radio_config(self, payload: dict[str, Any]) -> Any:
        """Update radio configuration with a raw payload."""
        return await self._async_request_wrapped(
            "POST", "/api/update_radio_config", json_body=payload
        )

    async def async_update_mqtt_config(self, payload: dict[str, Any]) -> Any:
        """Update MQTT configuration with a raw payload."""
        return await self._async_request_wrapped(
            "POST", "/api/update_mqtt_config", json_body=payload
        )

    async def async_update_check(self, force: bool = False) -> Any:
        """Trigger an update check."""
        return await self._async_request_wrapped(
            "POST", "/api/update/check", json_body={"force": force}
        )

    async def async_update_install(self, force: bool = False) -> Any:
        """Trigger installation of the latest update."""
        return await self._async_request_wrapped(
            "POST", "/api/update/install", json_body={"force": force}
        )

    async def async_update_set_channel(self, channel: str) -> Any:
        """Set the active update channel."""
        return await self._async_request_wrapped(
            "POST", "/api/update/set_channel", json_body={"channel": channel}
        )

    async def async_companion_send_text(
        self,
        *,
        pub_key: str,
        text: str,
        txt_type: int = 0,
        companion_name: str | None = None,
    ) -> Any:
        """Send a text message via a companion bridge."""
        payload: dict[str, Any] = {"pub_key": pub_key, "text": text, "txt_type": txt_type}
        if companion_name:
            payload["companion_name"] = companion_name
        return await self._async_request_wrapped(
            "POST", "/api/companion/send_text", json_body=payload
        )

    async def async_companion_send_channel_message(
        self,
        *,
        channel_idx: int,
        text: str,
        companion_name: str | None = None,
    ) -> Any:
        """Send a channel message via a companion bridge."""
        payload: dict[str, Any] = {"channel_idx": channel_idx, "text": text}
        if companion_name:
            payload["companion_name"] = companion_name
        return await self._async_request_wrapped(
            "POST", "/api/companion/send_channel_message", json_body=payload
        )

    async def async_companion_login(
        self,
        *,
        pub_key: str,
        password: str = "",
        companion_name: str | None = None,
    ) -> Any:
        """Send a companion login request."""
        payload: dict[str, Any] = {"pub_key": pub_key, "password": password}
        if companion_name:
            payload["companion_name"] = companion_name
        return await self._async_request_wrapped(
            "POST", "/api/companion/login", json_body=payload
        )

    async def async_companion_request_status(
        self,
        *,
        pub_key: str,
        timeout: float = 15.0,
        companion_name: str | None = None,
    ) -> Any:
        """Request status from a companion target."""
        payload: dict[str, Any] = {"pub_key": pub_key, "timeout": timeout}
        if companion_name:
            payload["companion_name"] = companion_name
        return await self._async_request_wrapped(
            "POST", "/api/companion/request_status", json_body=payload
        )

    async def async_companion_request_telemetry(
        self,
        *,
        pub_key: str,
        timeout: float = 20.0,
        companion_name: str | None = None,
        want_base: bool = True,
        want_location: bool = True,
        want_environment: bool = True,
    ) -> Any:
        """Request telemetry from a companion target."""
        payload: dict[str, Any] = {
            "pub_key": pub_key,
            "timeout": timeout,
            "want_base": want_base,
            "want_location": want_location,
            "want_environment": want_environment,
        }
        if companion_name:
            payload["companion_name"] = companion_name
        return await self._async_request_wrapped(
            "POST", "/api/companion/request_telemetry", json_body=payload
        )

    async def async_companion_send_command(
        self,
        *,
        pub_key: str,
        command: str,
        parameters: dict[str, Any] | list[Any] | str | None = None,
        companion_name: str | None = None,
    ) -> Any:
        """Send a repeater command through a companion bridge."""
        payload: dict[str, Any] = {"pub_key": pub_key, "command": command}
        if parameters is not None:
            payload["parameters"] = parameters
        if companion_name:
            payload["companion_name"] = companion_name
        return await self._async_request_wrapped(
            "POST", "/api/companion/send_command", json_body=payload
        )

    async def async_companion_reset_path(
        self,
        *,
        pub_key: str,
        companion_name: str | None = None,
    ) -> Any:
        """Reset stored routing path for a companion target."""
        payload: dict[str, Any] = {"pub_key": pub_key}
        if companion_name:
            payload["companion_name"] = companion_name
        return await self._async_request_wrapped(
            "POST", "/api/companion/reset_path", json_body=payload
        )

    async def async_companion_set_advert_name(
        self, *, advert_name: str, companion_name: str | None = None
    ) -> Any:
        """Set the advert name for a companion."""
        payload: dict[str, Any] = {"advert_name": advert_name}
        if companion_name:
            payload["companion_name"] = companion_name
        return await self._async_request_wrapped(
            "POST", "/api/companion/set_advert_name", json_body=payload
        )

    async def async_companion_set_advert_location(
        self,
        *,
        latitude: float,
        longitude: float,
        companion_name: str | None = None,
    ) -> Any:
        """Set the advert location for a companion."""
        payload: dict[str, Any] = {"latitude": latitude, "longitude": longitude}
        if companion_name:
            payload["companion_name"] = companion_name
        return await self._async_request_wrapped(
            "POST", "/api/companion/set_advert_location", json_body=payload
        )

    async def _async_login(self, password: str, client_id: str) -> str:
        payload = await self._async_request_json(
            "POST",
            "/auth/login",
            json_body={
                "username": "admin",
                "password": password,
                "client_id": client_id,
            },
            auth="none",
        )
        token = payload.get("token")
        if not token:
            raise PyMCRepeaterAuthenticationError("Missing JWT token in login response")
        return token

    async def _async_create_token(self, jwt: str, token_name: str) -> dict[str, Any]:
        payload = await self._async_request_json(
            "POST",
            "/api/auth/tokens",
            json_body={"name": token_name},
            auth="bearer",
            bearer_token=jwt,
        )
        token = payload.get("token")
        if not token:
            raise PyMCRepeaterAuthenticationError("Missing API token in token response")
        return payload

    async def _async_request_wrapped(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        payload = await self._async_request_json(
            method, path, params=params, json_body=json_body, auth="api_token"
        )
        if payload.get("success") is False:
            raise PyMCRepeaterApiError(payload.get("error", f"Request failed for {path}"))
        return payload.get("data", payload)

    async def _async_open_stream(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> ClientResponse:
        headers = {"Accept": "text/event-stream"}
        if not self.api_token:
            raise PyMCRepeaterAuthenticationError("API token is not configured")
        headers["X-API-Key"] = self.api_token
        url = f"{self.base_url}{path}"

        try:
            response = await self._session.request(
                method,
                url,
                params=params,
                headers=headers,
                timeout=None,
            )
        except ClientError as err:
            raise PyMCRepeaterCannotConnect(
                f"Cannot connect to {self.host}:{self.port}"
            ) from err

        if response.status in (401, 403):
            response.release()
            raise PyMCRepeaterAuthenticationError(f"Authentication failed for {path}")
        if response.status >= 400:
            detail = await response.text()
            response.release()
            raise PyMCRepeaterApiError(f"HTTP {response.status} from {path}: {detail[:200]}")
        return response

    async def _async_request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: str = "api_token",
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}

        if auth == "api_token":
            if not self.api_token:
                raise PyMCRepeaterAuthenticationError("API token is not configured")
            headers["X-API-Key"] = self.api_token
        elif auth == "bearer":
            if not bearer_token:
                raise PyMCRepeaterAuthenticationError("Bearer token is not available")
            headers["Authorization"] = f"Bearer {bearer_token}"

        url = f"{self.base_url}{path}"

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                ) as response:
                    if response.status in (401, 403):
                        raise PyMCRepeaterAuthenticationError(
                            f"Authentication failed for {path}"
                        )
                    if response.status >= 400:
                        detail = await response.text()
                        raise PyMCRepeaterApiError(
                            f"HTTP {response.status} from {path}: {detail[:200]}"
                        )
                    payload = await response.json(content_type=None)
        except PyMCRepeaterError:
            raise
        except TimeoutError as err:
            raise PyMCRepeaterCannotConnect(
                f"Timed out connecting to {self.host}:{self.port}"
            ) from err
        except ClientError as err:
            raise PyMCRepeaterCannotConnect(
                f"Cannot connect to {self.host}:{self.port}"
            ) from err
        except ValueError as err:
            raise PyMCRepeaterApiError(f"Invalid JSON returned by {path}") from err

        if isinstance(payload, dict) and payload.get("success") is False:
            error = str(payload.get("error", "Unknown API error"))
            if "unauthorized" in error.lower() or "invalid username or password" in error.lower():
                raise PyMCRepeaterAuthenticationError(error)

        return payload

    @staticmethod
    def decode_sse_payload(line: bytes) -> dict[str, Any] | None:
        """Decode one SSE data line from the GPS stream."""
        if not line.startswith(b"data:"):
            return None
        payload = line[5:].strip()
        if not payload:
            return None
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _build_client_id(self) -> str:
        """Create a stable-enough client identifier for HA bootstrap."""
        hostname = socket.gethostname().lower().replace(" ", "-")
        return f"{CLIENT_ID_PREFIX}-{hostname}"
