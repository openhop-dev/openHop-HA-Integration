"""Async API client for openHop Repeater."""

from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout
from yarl import URL

from .const import CLIENT_ID_PREFIX, DEFAULT_PACKET_WINDOW_HOURS

REQUEST_TIMEOUT = 10
PLUGIN_REQUEST_TIMEOUT = 930  # IPC completion 900 seconds plus HTTP margin
PLUGIN_MAX_BATCH = 100
NEIGHBOR_SCOPE_QUERY_TIMEOUT = 50
SENSITIVE_RESPONSE_KEYS = {
    "identity_key",
    "private_key",
    "admin_password",
    "guest_password",
    "password",
    "token",
    "transport_key",
    "jwt_secret",
}


def _drop_sensitive_fields(value: Any) -> Any:
    """Recursively remove private configuration fields from API payloads."""
    if isinstance(value, dict):
        return {
            key: _drop_sensitive_fields(item)
            for key, item in value.items()
            if key not in SENSITIVE_RESPONSE_KEYS
        }
    if isinstance(value, list):
        return [_drop_sensitive_fields(item) for item in value]
    return value


class PyMCRepeaterError(Exception):
    """Base error for the openHop Repeater client."""


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
    """Build the openHop API token label for this Home Assistant instance."""
    hostname = (home_assistant_hostname or "").strip() or socket.gethostname()
    return f"Home Assistant ({hostname})"


class PyMCRepeaterApiClient:
    """HTTP client for openHop Repeater."""

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
        self._plugin_upgrade_active = False
        self._plugin_upgrade_uncertain = False

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
            "packet_stats_1h": self.async_get_packet_stats(hours=1),
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
            "companions": self.async_get_companions(),
            "gps": self.async_get_gps(),
            "packet_type_stats": self.async_get_packet_type_stats(),
            "lbt_diagnostics": self.async_get_lbt_diagnostics(),
            "default_region": self.async_get_default_region(),
            "neighbor_links": self.async_get_neighbor_links(),
            "plugin_summary": self.async_get_plugin_summary(),
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

    @staticmethod
    def validate_plugin_text(value: Any, maximum: int = 128) -> str:
        """Bound exact plugin IDs/version tokens without trimming or coercion."""
        if (not isinstance(value, str) or not 1 <= len(value) <= maximum
                or not value.isascii() or not value[0].isalnum()
                or any(not (char.isalnum() or char in "._+-") for char in value)):
            raise PyMCRepeaterApiError("Invalid plugin ID or version token")
        return value

    async def _async_plugin_payload(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Use finite IPC-compatible budgets; never expose backend error text."""
        try:
            payload = await self._async_request_json(
                method, path, auth="api_token", timeout_seconds=PLUGIN_REQUEST_TIMEOUT,
                plugin_request=True, **kwargs,
            )
        except PyMCRepeaterAuthenticationError:
            return {"success": False, "reason": "authentication_failed"}
        except PyMCRepeaterCannotConnect:
            return {"success": False, "outcome": "unknown", "reason": "connection_lost"}
        except (PyMCRepeaterApiError, TimeoutError, ValueError):
            return {"success": False, "outcome": "unknown", "reason": "invalid_or_lost_response"}
        if not isinstance(payload, dict):
            return {"success": False, "outcome": "unknown", "reason": "invalid_response"}
        if payload.get("success") is not False and "data" in payload:
            payload = payload["data"]
            if not isinstance(payload, dict):
                return {"success": False, "outcome": "unknown", "reason": "invalid_response"}
        if payload.get("success") is False:
            status = payload.get("http_status")
            uncertain = payload.get("outcome") == "unknown" or status in (409, 502, 504)
            return {"success": False, "outcome": "unknown" if uncertain else "failure",
                    "reason": "operation_in_progress" if status == 409 else "backend_error"}
        return payload

    async def _async_plugin_inventory(self) -> list[dict[str, Any]]:
        """Keep only installed identity/version/provenance for action planning."""
        data = await self._async_plugin_payload("GET", "/api/plugins/")
        rows = data.get("plugins")
        if data.get("success") is False or not isinstance(rows, list) or len(rows) > PLUGIN_MAX_BATCH:
            raise PyMCRepeaterApiError("Plugin inventory unavailable or exceeds 100 plugins")
        result, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                raise PyMCRepeaterApiError("Invalid plugin inventory")
            plugin_id = self.validate_plugin_text(row.get("id"))
            if plugin_id in seen:
                raise PyMCRepeaterApiError("Duplicate plugin inventory identity")
            seen.add(plugin_id)
            try:
                version = self.validate_plugin_text(row.get("version"))
            except PyMCRepeaterApiError:
                version = None
            repository = row.get("repository")
            result.append({"id": plugin_id, "version": version,
                           "eligible": row.get("source") == "catalogue"
                           and isinstance(repository, str) and bool(repository.strip())})
        return result

    async def _async_plugin_check(self, row: dict[str, Any], force_refresh: bool) -> dict[str, Any]:
        result = {"id": row["id"], "installed_version": row["version"]}
        if not row["eligible"]:
            return {**result, "outcome": "skipped", "reason": "not_catalogue_or_repository_unavailable"}
        data = await self._async_plugin_payload(
            "GET", "/api/plugins/updates", params={"id": row["id"], "refresh": str(force_refresh).lower()},
        )
        if data.get("success") is False:
            return {**result, "outcome": data.get("outcome", "failure"), "reason": data["reason"]}
        latest = data.get("latestVersion")
        if not isinstance(data.get("updateAvailable"), bool) or data.get("id") != row["id"]:
            return {**result, "outcome": "unknown", "reason": "invalid_check_response"}
        if latest is not None:
            try:
                latest = self.validate_plugin_text(latest)
            except PyMCRepeaterApiError:
                return {**result, "outcome": "unknown", "reason": "invalid_version_response"}
        if data["updateAvailable"] and latest is None:
            return {**result, "outcome": "unknown", "reason": "missing_target_version"}
        return {**result, "outcome": "success", "latest_version": latest,
                "update_available": data["updateAvailable"]}

    @staticmethod
    def _plugin_summary(results: list[dict[str, Any]], *, stopped: bool = False) -> dict[str, Any]:
        return {"results": results, "counts": {outcome: sum(row["outcome"] == outcome for row in results)
                for outcome in ("success", "skipped", "failure", "unknown")}, "stopped": stopped}

    async def async_check_plugin_updates(
        self, *, plugin_id: str | None = None, force_refresh: bool = False
    ) -> dict[str, Any]:
        """Check installed catalogue plugins on demand, without changing polling."""
        if plugin_id is not None:
            plugin_id = self.validate_plugin_text(plugin_id)
        if not isinstance(force_refresh, bool):
            raise PyMCRepeaterApiError("force_refresh must be boolean")
        rows = await self._async_plugin_inventory()
        if plugin_id is not None:
            rows = [row for row in rows if row["id"] == plugin_id]
            if not rows:
                return self._plugin_summary([{"id": plugin_id, "outcome": "skipped", "reason": "not_installed"}])
        return self._plugin_summary([await self._async_plugin_check(row, force_refresh) for row in rows])

    async def _async_plugin_upgrade(
        self, row: dict[str, Any], *, version: str | None, force_refresh: bool
    ) -> dict[str, Any]:
        checked = await self._async_plugin_check(row, force_refresh)
        if checked["outcome"] != "success":
            return checked
        if version is None and not checked["update_available"]:
            return {**checked, "outcome": "skipped", "reason": "no_update"}
        target = version or checked["latest_version"]
        data = await self._async_plugin_payload(
            "POST", "/api/plugins/update",
            json_body={"id": row["id"], "version": target, "force_refresh": force_refresh},
        )
        if data.get("success") is False:
            return {**checked, "outcome": data.get("outcome", "failure"), "reason": data["reason"]}
        plugin = data.get("plugin")
        # Enabled plugins return enable()/status(), which has no updated flag.
        # Verify returned identity and exact installed target, not the HTTP envelope.
        if not isinstance(plugin, dict) or plugin.get("id") != row["id"]:
            return {**checked, "outcome": "unknown", "reason": "invalid_update_response"}
        if plugin.get("updated") is False:
            return {**checked, "outcome": "skipped", "reason": "no_update"}
        actual = plugin.get("version")
        if not isinstance(actual, str) or actual.removeprefix("v") != target.removeprefix("v"):
            return {**checked, "outcome": "unknown", "reason": "target_version_unconfirmed"}
        return {**checked, "outcome": "success", "version": actual, "updated": True}

    async def _async_plugin_upgrade_batch(
        self, *, plugin_id: str | None = None, version: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Fail-fast admission per client; never enqueue upgrades or retry writes."""
        if plugin_id is not None:
            plugin_id = self.validate_plugin_text(plugin_id)
        if version is not None:
            version = self.validate_plugin_text(version)
        if not isinstance(force_refresh, bool):
            raise PyMCRepeaterApiError("force_refresh must be boolean")
        if getattr(self, "_plugin_upgrade_active", False):
            raise PyMCRepeaterApiError("Plugin upgrade already in progress")
        if getattr(self, "_plugin_upgrade_uncertain", False):
            raise PyMCRepeaterApiError("Previous plugin upgrade outcome uncertain; reconcile on Repeater before reloading entry")
        self._plugin_upgrade_active = True
        write_possible = False
        try:
            rows = await self._async_plugin_inventory()
            if plugin_id is not None:
                rows = [row for row in rows if row["id"] == plugin_id]
                if not rows:
                    return self._plugin_summary([{"id": plugin_id, "outcome": "skipped", "reason": "not_installed"}])
            results, stopped = [], False
            for row in rows:
                if stopped:
                    results.append({"id": row["id"], "outcome": "skipped", "reason": "batch_stopped"})
                    continue
                write_possible = True
                result = await self._async_plugin_upgrade(row, version=version, force_refresh=force_refresh)
                write_possible = False
                results.append(result)
                if result["outcome"] == "unknown":
                    stopped = True
                    self._plugin_upgrade_uncertain = True
            return self._plugin_summary(results, stopped=stopped)
        except asyncio.CancelledError:
            # Cancellation cannot cancel an accepted remote IPC install.
            if write_possible:
                self._plugin_upgrade_uncertain = True
            raise
        finally:
            self._plugin_upgrade_active = False

    @staticmethod
    def validate_sensor_configuration(value: Any) -> dict[str, Any]:
        """Require complete replacement input, not a defaults-resetting patch."""
        import math
        value = PyMCRepeaterApiClient.validate_json_object(value)
        required = {"enabled", "poll_interval_seconds", "auto_install_packages", "definitions"}
        if set(value) != required:
            raise PyMCRepeaterApiError("Sensor configuration requires all four replacement fields")
        for key in ("enabled", "auto_install_packages"):
            if not isinstance(value[key], bool):
                raise PyMCRepeaterApiError(key + " must be boolean")
        interval = value["poll_interval_seconds"]
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
            raise PyMCRepeaterApiError("poll_interval_seconds must be finite and positive")
        definitions = value["definitions"]
        if not isinstance(definitions, list) or len(definitions) > 100:
            raise PyMCRepeaterApiError("definitions must be an array of at most 100 sensors")
        names, origins = set(), set()
        for definition in definitions:
            if not isinstance(definition, dict):
                raise PyMCRepeaterApiError("Sensor definitions must be objects")
            name = PyMCRepeaterApiClient.validate_management_name(definition.get("name"))
            PyMCRepeaterApiClient.validate_management_name(definition.get("type"))
            if name in names:
                raise PyMCRepeaterApiError("Duplicate sensor name")
            names.add(name)
            if "settings" in definition and not isinstance(definition["settings"], dict):
                raise PyMCRepeaterApiError("Sensor settings must be a JSON object")
            for key in ("enabled", "auto_install_packages"):
                if key in definition and not isinstance(definition[key], bool):
                    raise PyMCRepeaterApiError(key + " must be boolean")
            if "_original_name" in definition:
                origin = (definition["type"], PyMCRepeaterApiClient.validate_management_name(definition["_original_name"]))
                if origin in origins:
                    raise PyMCRepeaterApiError("Duplicate sensor origin")
                origins.add(origin)
        return value

    @staticmethod
    def validate_management_name(value: Any) -> str:
        """Bound an exact human-readable identity without changing it."""
        if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value):
            raise PyMCRepeaterApiError("Name must be a nonempty string of at most 256 characters without controls")
        return value

    async def _async_management_payload(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Use finite budgets and fixed errors for sensitive management calls."""
        try:
            data = await self._async_request_json(method, path, auth="api_token", timeout_seconds=30,
                                                  plugin_request=True, max_response_bytes=1024 * 1024, **kwargs)
        except PyMCRepeaterError as err:
            raise PyMCRepeaterApiError("Management request failed; reconcile before retrying writes") from err
        if not isinstance(data, dict) or data.get("success") is False:
            raise PyMCRepeaterApiError("Management request failed; reconcile before retrying writes")
        data = data.get("data", data)
        if not isinstance(data, dict) or data.get("success") is False:
            raise PyMCRepeaterApiError("Invalid management response")
        return self.validate_json_object(data, allow_redacted=True)

    async def async_get_sensor_types(self) -> dict[str, Any]:
        """Read available types/settings schemas without touching hardware."""
        data = await self._async_management_payload("GET", "/api/sensors_types")
        types = data.get("types")
        if not isinstance(types, list) or len(types) > 100 or any(not isinstance(row, dict) for row in types):
            raise PyMCRepeaterApiError("Invalid sensor types response")
        return {"types": self._management_config_response(types, include_sensitive=False)}

    async def async_get_sensor_configuration(self, *, include_sensitive: bool = False) -> dict[str, Any]:
        """Read configuration on demand, retaining password masks and rename origins."""
        if not isinstance(include_sensitive, bool):
            raise PyMCRepeaterApiError("include_sensitive must be boolean")
        data = await self._async_management_payload("GET", "/api/sensors_config")
        # Validate before redaction so a redacted response is never used as a write.
        config = self.validate_sensor_configuration(data)
        return self._management_config_response(config, include_sensitive=include_sensitive, sensor_masks=True)

    async def async_update_sensor_configuration(self, *, config: dict[str, Any]) -> dict[str, Any]:
        """Save a complete replacement; application requires an operator restart."""
        config = self.validate_sensor_configuration(config)
        data = await self._async_management_payload("POST", "/api/sensors_config_update", json_body=config)
        if data.get("saved") is not True or not isinstance(data.get("restart_required"), bool):
            raise PyMCRepeaterApiError("Sensor save unconfirmed; reconcile before retrying")
        return {"saved": True, "restart_required": data["restart_required"]}

    @staticmethod
    def validate_json_object(value: Any, *, allow_redacted: bool = False) -> dict[str, Any]:
        """Require real finite JSON, bounded depth/nodes and 256 KiB encoding."""
        import json
        import math
        if not isinstance(value, dict):
            raise PyMCRepeaterApiError("Configuration must be a JSON object")
        nodes = 0
        def visit(item: Any, depth: int) -> None:
            nonlocal nodes
            nodes += 1
            if depth > 32 or nodes > 10000:
                raise PyMCRepeaterApiError("Configuration exceeds depth or item limit")
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise PyMCRepeaterApiError("JSON object keys must be strings")
                for child in item.values():
                    visit(child, depth + 1)
            elif isinstance(item, list):
                for child in item:
                    visit(child, depth + 1)
            elif isinstance(item, str):
                if not allow_redacted and item == "[REDACTED]":
                    raise PyMCRepeaterApiError("Replace redacted values or explicitly request sensitive configuration before writing")
            elif item is None or isinstance(item, bool) or isinstance(item, int):
                pass
            elif isinstance(item, float) and math.isfinite(item):
                pass
            else:
                raise PyMCRepeaterApiError("Configuration must contain only finite JSON values")
        visit(value, 0)
        try:
            encoded = json.dumps(value, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError) as err:
            raise PyMCRepeaterApiError("Invalid JSON configuration") from err
        if len(encoded) > 256 * 1024:
            raise PyMCRepeaterApiError("Configuration exceeds 256 KiB")
        return value

    @staticmethod
    def _management_config_response(value: Any, *, include_sensitive: bool, sensor_masks: bool = False) -> Any:
        """Redact common credential keys, preserving backend sensor password masks."""
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                normalized = key.lower().replace("-", "_")
                secret = any(part in normalized for part in ("password", "secret", "token", "private_key", "api_key", "transport_key"))
                if secret and not include_sensitive and not (sensor_masks and normalized == "password" and item == "*****"):
                    result[key] = "[REDACTED]" if item else item
                else:
                    result[key] = PyMCRepeaterApiClient._management_config_response(
                        item, include_sensitive=include_sensitive, sensor_masks=sensor_masks)
            return result
        if isinstance(value, list):
            return [PyMCRepeaterApiClient._management_config_response(
                item, include_sensitive=include_sensitive, sensor_masks=sensor_masks) for item in value]
        return value

    async def async_get_plugin_settings(
        self, *, plugin_id: str, include_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Read explicit settings only; full sensitive configuration is opt-in."""
        plugin_id = self.validate_plugin_text(plugin_id)
        if not isinstance(include_sensitive, bool):
            raise PyMCRepeaterApiError("include_sensitive must be boolean")
        data = await self._async_plugin_payload("GET", "/api/plugins/settings", params={"id": plugin_id}, max_response_bytes=1024 * 1024)
        if data.get("success") is False or data.get("id") != plugin_id:
            raise PyMCRepeaterApiError("Plugin settings unavailable")
        config = self.validate_json_object(data.get("config"), allow_redacted=True)
        return {"id": plugin_id, "config": self._management_config_response(
            config, include_sensitive=include_sensitive)}

    async def async_update_plugin_settings(
        self, *, plugin_id: str, config: dict[str, Any], restart: bool = False,
    ) -> dict[str, Any]:
        """Replace plugin config, optionally restarting; return only metadata."""
        plugin_id = self.validate_plugin_text(plugin_id)
        config = self.validate_json_object(config)
        if not isinstance(restart, bool):
            raise PyMCRepeaterApiError("restart must be boolean")
        return await self._async_plugin_write("settings", plugin_id,
            {"id": plugin_id, "config": config, "restart": restart})

    async def async_get_plugin_catalogue(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """List bounded catalogue metadata, without paths, URLs or backend errors."""
        if not isinstance(force_refresh, bool):
            raise PyMCRepeaterApiError("force_refresh must be boolean")
        data = await self._async_plugin_payload(
            "GET", "/api/plugins/catalogue", params={"refresh": str(force_refresh).lower()}, max_response_bytes=1024 * 1024,
        )
        rows = data.get("plugins")
        if data.get("success") is False or not isinstance(rows, list) or len(rows) > PLUGIN_MAX_BATCH:
            raise PyMCRepeaterApiError("Plugin catalogue unavailable or exceeds 100 entries")
        result, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                raise PyMCRepeaterApiError("Invalid catalogue response")
            plugin_id = self.validate_plugin_text(row.get("id"))
            if plugin_id in seen:
                raise PyMCRepeaterApiError("Duplicate catalogue identity")
            seen.add(plugin_id)
            item = {"id": plugin_id}
            for key in ("name", "description"):
                if isinstance(row.get(key), str):
                    item[key] = row[key][:1024]
            for key in ("installed", "updateAvailable"):
                if isinstance(row.get(key), bool):
                    item[key] = row[key]
            for key in ("version", "installedVersion", "latestVersion"):
                if row.get(key) is not None:
                    item[key] = self.validate_plugin_text(row[key])
            result.append(item)
        return {"plugins": result}

    async def async_install_catalogue_plugin(
        self, *, plugin_id: str, version: str | None = None, force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Install an approved catalogue wheel using the shared write guard."""
        plugin_id = self.validate_plugin_text(plugin_id)
        if not isinstance(force_refresh, bool):
            raise PyMCRepeaterApiError("force_refresh must be boolean")
        body: dict[str, Any] = {"id": plugin_id, "force_refresh": force_refresh}
        if version is not None:
            body["version"] = self.validate_plugin_text(version)
        return await self._async_plugin_write("catalogue_install", plugin_id, body)

    async def async_plugin_lifecycle(
        self, *, plugin_id: str, operation: str, delete_data: bool = False,
    ) -> dict[str, Any]:
        """Perform an explicit lifecycle write with shared fail-fast admission."""
        plugin_id = self.validate_plugin_text(plugin_id)
        if operation not in {"enable", "disable", "start", "stop", "restart", "uninstall"}:
            raise PyMCRepeaterApiError("Invalid plugin lifecycle operation")
        if not isinstance(delete_data, bool):
            raise PyMCRepeaterApiError("delete_data must be boolean")
        body: dict[str, Any] = {"id": plugin_id}
        if operation == "uninstall":
            body["delete_data"] = delete_data
        return await self._async_plugin_write(operation, plugin_id, body)

    async def _async_plugin_write(
        self, operation: str, plugin_id: str, body: dict[str, Any],
    ) -> dict[str, Any]:
        """Never queue/retry remote writes; quarantine ambiguous completion."""
        if getattr(self, "_plugin_upgrade_active", False):
            raise PyMCRepeaterApiError("Plugin write already in progress")
        if getattr(self, "_plugin_upgrade_uncertain", False):
            raise PyMCRepeaterApiError("Previous plugin write outcome uncertain; reconcile on Repeater before reloading entry")
        self._plugin_upgrade_active = True
        try:
            data = await self._async_plugin_payload(
                "POST", "/api/plugins/" + operation, json_body=body, max_response_bytes=1024 * 1024,
            )
            if data.get("success") is False:
                result = {"id": plugin_id, "outcome": data.get("outcome", "failure"),
                          "reason": data.get("reason", "backend_error")}
            else:
                plugin = data.get("plugin", data)
                confirmed = isinstance(plugin, dict) and plugin.get("id") == plugin_id
                if confirmed:
                    if operation == "enable":
                        confirmed = plugin.get("enabled") is True
                    elif operation == "disable":
                        confirmed = plugin.get("enabled") is False
                    elif operation in {"start", "stop", "restart"}:
                        confirmed = isinstance(plugin.get("state"), str) and plugin["state"] in {"RUNNING", "STOPPED", "DISABLED", "FAILED", "STARTING", "STOPPING"}
                    elif operation == "uninstall":
                        confirmed = plugin.get("uninstalled") is True and plugin.get("data_deleted") is body["delete_data"]
                    elif operation == "settings":
                        confirmed = isinstance(plugin.get("config"), dict) and isinstance(plugin.get("restarted"), bool)
                    elif operation == "catalogue_install":
                        try:
                            actual = self.validate_plugin_text(plugin.get("version"))
                            confirmed = "version" not in body or actual.removeprefix("v") == body["version"].removeprefix("v")
                        except PyMCRepeaterApiError:
                            confirmed = False
                if not confirmed:
                    result = {"id": plugin_id, "outcome": "unknown", "reason": "invalid_write_response"}
                else:
                    result = {"id": plugin_id, "outcome": "success"}
                    for key in ("enabled", "uninstalled", "data_deleted", "restarted", "exists"):
                        if isinstance(plugin.get(key), bool):
                            result[key] = plugin[key]
                    if isinstance(plugin.get("state"), str) and plugin["state"] in {"RUNNING", "STOPPED", "DISABLED", "FAILED", "STARTING", "STOPPING"}:
                        result["state"] = plugin["state"]
                    if isinstance(plugin.get("version"), str):
                        try:
                            result["version"] = self.validate_plugin_text(plugin["version"])
                        except PyMCRepeaterApiError:
                            pass
            if result["outcome"] == "unknown":
                self._plugin_upgrade_uncertain = True
            return result
        except asyncio.CancelledError:
            self._plugin_upgrade_uncertain = True
            raise
        finally:
            self._plugin_upgrade_active = False

    async def async_update_plugin(
        self, *, plugin_id: str, version: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Upgrade one installed catalogue plugin, optionally targeting a version."""
        return await self._async_plugin_upgrade_batch(
            plugin_id=plugin_id, version=version, force_refresh=force_refresh,
        )

    async def async_update_all_plugins(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Sequentially upgrade eligible installed plugins; scheduling is operator-owned."""
        return await self._async_plugin_upgrade_batch(force_refresh=force_refresh)

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

    async def async_get_packet_stats(
        self, *, hours: int = DEFAULT_PACKET_WINDOW_HOURS
    ) -> dict[str, Any]:
        """Return packet stats."""
        return await self._async_request_wrapped(
            "GET",
            "/api/packet_stats",
            params={"hours": hours},
        )

    async def async_get_packet_type_stats(
        self, *, hours: int = DEFAULT_PACKET_WINDOW_HOURS
    ) -> dict[str, Any]:
        """Return packet type stats."""
        return await self._async_request_wrapped(
            "GET",
            "/api/packet_type_stats",
            params={"hours": hours},
        )

    @staticmethod
    def validate_query_integer(value: Any, minimum: int, maximum: int) -> int:
        """Reject nonfinite, fractional and out-of-bounds query values."""
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not minimum <= value <= maximum
            or value != int(value)
        ):
            raise PyMCRepeaterApiError(
                f"Query value must be an integer between {minimum} and {maximum}"
            )
        return int(value)

    @staticmethod
    def validate_radio_id(value: Any) -> str:
        """Require an exact nonempty string; never coerce or trim identities."""
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise PyMCRepeaterApiError("Radio ID must be an exact nonempty string")
        return value

    async def async_get_lbt_diagnostics(
        self, *, hours: int = DEFAULT_PACKET_WINDOW_HOURS,
        bucket_seconds: int | None = None,
        severe_attempt_threshold: int | None = None,
    ) -> dict[str, Any]:
        """Return bounded LBT diagnostics (the backend has no radio filter)."""
        params = {"hours": self.validate_query_integer(hours, 1, 168)}
        if bucket_seconds is not None:
            params["bucket_seconds"] = self.validate_query_integer(bucket_seconds, 60, 3600)
        if severe_attempt_threshold is not None:
            params["severe_attempt_threshold"] = self.validate_query_integer(severe_attempt_threshold, 2, 16)
        return await self._async_request_wrapped("GET", "/api/lbt_diagnostics", params=params)

    async def async_get_radio_packet_rates(
        self, *, hours: int = DEFAULT_PACKET_WINDOW_HOURS,
        bucket_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Return on-demand per-radio rate buckets, retaining backend defaults."""
        params = {"hours": self.validate_query_integer(hours, 1, 168)}
        if bucket_seconds is not None:
            params["bucket_seconds"] = self.validate_query_integer(bucket_seconds, 60, 86400)
        return await self._async_request_wrapped("GET", "/api/radio_packet_rates", params=params)

    async def async_get_companion_stats(
        self, *, type: str = "packets", companion_name: str | None = None,
    ) -> Any:
        """Return local companion diagnostics without requesting remote RF data."""
        if type not in ("core", "radio", "packets"):
            raise PyMCRepeaterApiError("Companion stats type must be core, radio or packets")
        params = {"type": type}
        if companion_name is not None:
            if not isinstance(companion_name, str) or not companion_name.strip():
                raise PyMCRepeaterApiError("Companion name must be a nonempty string")
            params["companion_name"] = companion_name
        return await self._async_request_wrapped("GET", "/api/companion/stats", params=params)

    async def async_get_route_stats(self) -> dict[str, Any]:
        """Return route stats."""
        return await self._async_request_wrapped(
            "GET",
            "/api/route_stats",
            params={"hours": DEFAULT_PACKET_WINDOW_HOURS},
        )

    async def async_get_neighbor_links(
        self, *, active_within_seconds: int = 90, limit: int = 500
    ) -> dict[str, Any]:
        """Return observed upstream neighbor link snapshots."""
        return await self._async_request_wrapped(
            "GET",
            "/api/neighbor_links",
            params={
                "active_within_seconds": active_within_seconds,
                "limit": limit,
            },
        )

    async def async_get_plugin_summary(self) -> dict[str, Any]:
        """Return counts and allowlisted plugin health, never paths or configuration."""
        # Unlike most endpoints, this API returns a top-level plugins list.
        payload = await self._async_request_wrapped("GET", "/api/plugins/")
        plugins = payload.get("plugins") if isinstance(payload, dict) else None
        if not isinstance(plugins, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("enabled"), bool)
            or not isinstance(item.get("state"), str)
            for item in plugins
        ):
            raise PyMCRepeaterApiError("Invalid plugin inventory response")
        return {
            "plugins": [
                {key: item[key] for key in ("id", "name", "version", "enabled", "state", "has_runtime")
                 if key in item and isinstance(item[key], (str, bool))}
                for item in plugins if isinstance(item.get("id"), str) and item["id"]
            ],
            "installed": len(plugins),
            "enabled": sum(item["enabled"] for item in plugins),
            "running": sum(item["state"] == "RUNNING" for item in plugins),
            "failed": sum(item["state"] == "FAILED" for item in plugins),
        }

    async def async_get_neighbor_link_history(
        self,
        *,
        peer_hash: str,
        path_hash_size: int,
        hours: int = DEFAULT_PACKET_WINDOW_HOURS,
        limit: int = 1000,
        bucket_seconds: int | None = None,
        radio_id: str | None = None,
        by_radio: bool | None = None,
    ) -> dict[str, Any]:
        """Return raw observations or optional time buckets for one neighbor."""
        params: dict[str, Any] = {
            "peer_hash": peer_hash,
            "path_hash_size": self.validate_query_integer(path_hash_size, 1, 3),
            "hours": self.validate_query_integer(hours, 1, 168),
            "limit": self.validate_query_integer(limit, 1, 5000),
        }
        if bucket_seconds is not None:
            params["bucket_seconds"] = self.validate_query_integer(bucket_seconds, 60, 86400)
        if radio_id is not None:
            params["radio_id"] = self.validate_radio_id(radio_id)
        if by_radio is not None:
            if not isinstance(by_radio, bool):
                raise PyMCRepeaterApiError("by_radio must be a boolean")
            if by_radio and bucket_seconds is None:
                raise PyMCRepeaterApiError("by_radio requires bucket_seconds")
            params["by_radio"] = str(by_radio).lower()
        return await self._async_request_wrapped(
            "GET", "/api/neighbor_link_history", params=params
        )

    async def async_get_noise_floor_stats(
        self, *, hours: int = DEFAULT_PACKET_WINDOW_HOURS, radio_id: str | None = None,
    ) -> dict[str, Any]:
        """Return noise stats; a zero-sample mean is absent, not measured 0 dBm."""
        params: dict[str, Any] = {"hours": self.validate_query_integer(hours, 1, 168)}
        if radio_id is not None:
            params["radio_id"] = self.validate_radio_id(radio_id)
        payload = await self._async_request_wrapped("GET", "/api/noise_floor_stats", params=params)
        stats = payload.get("stats", payload)
        if isinstance(stats, dict) and stats.get("measurement_count") == 0:
            stats = dict(stats, avg_noise_floor=None)
        return stats

    async def async_get_crc_error_count(
        self, *, hours: int = DEFAULT_PACKET_WINDOW_HOURS, radio_id: str | None = None,
    ) -> dict[str, Any]:
        """Return aggregate or explicitly targeted CRC error count."""
        params: dict[str, Any] = {"hours": self.validate_query_integer(hours, 1, 168)}
        if radio_id is not None:
            params["radio_id"] = self.validate_radio_id(radio_id)
        return await self._async_request_wrapped("GET", "/api/crc_error_count", params=params)

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
        """Return identity stats without private configuration fields."""
        payload = await self._async_request_wrapped("GET", "/api/identities")
        if not isinstance(payload, dict):
            raise PyMCRepeaterApiError("Invalid identities response")
        return _drop_sensitive_fields(payload)

    async def async_get_db_stats(self) -> dict[str, Any]:
        """Return database stats."""
        return await self._async_request_wrapped("GET", "/api/db_stats")

    async def async_get_transport_keys(self) -> list[dict[str, Any]]:
        """Return transport-key metadata without retaining key material."""
        items = await self._async_request_wrapped("GET", "/api/transport_keys")
        if not isinstance(items, list):
            raise PyMCRepeaterApiError("Invalid transport keys response")

        safe_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            safe_item = dict(item)
            safe_item.pop("transport_key", None)
            safe_items.append(safe_item)
        return safe_items

    async def async_get_default_region(self) -> dict[str, Any]:
        """Return mesh default region configuration."""
        return await self._async_request_wrapped("GET", "/api/default_region")

    async def async_set_default_region(self, default_region: str | None) -> dict[str, Any]:
        """Set or clear the mesh default region."""
        return await self._async_request_wrapped(
            "POST",
            "/api/default_region",
            json_body={"default_region": default_region},
        )

    async def async_get_room_stats(self) -> dict[str, Any]:
        """Return room server stats."""
        return await self._async_request_wrapped("GET", "/api/room_stats")

    async def async_get_update_status(self) -> dict[str, Any]:
        """Return repeater update status."""
        return await self._async_request_wrapped("GET", "/api/update/status")

    async def async_get_update_channels(self) -> dict[str, Any]:
        """Return available repeater update channels on explicit request only."""
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

    async def async_get_broker_presets(self) -> dict[str, Any]:
        """Return bundled MC2MQTT broker presets."""
        presets = await self._async_request_wrapped("GET", "/api/broker_presets")
        return {
            "presets": presets,
            "count": len(presets) if isinstance(presets, list) else 0,
        }

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

    async def async_get_adverts_by_contact_type(
        self,
        *,
        contact_type: str,
        limit: int = 100,
        offset: int = 0,
        hours: int | None = None,
    ) -> dict[str, Any]:
        """Return adverts for one contact type."""
        params: dict[str, Any] = {
            "contact_type": contact_type,
            "limit": limit,
            "offset": offset,
        }
        if hours is not None:
            params["hours"] = hours

        payload = await self._async_request_json(
            "GET",
            "/api/adverts_by_contact_type",
            params=params,
            auth="api_token",
        )
        if payload.get("success") is False:
            raise PyMCRepeaterApiError(
                payload.get("error", "Failed to fetch adverts by contact type")
            )
        adverts = payload.get("data", [])
        return {
            "adverts": adverts,
            "count": payload.get("count", len(adverts)),
            "filters": payload.get("filters"),
        }

    async def async_get_adverts_count_by_contact_type(
        self,
        *,
        contact_type: str,
        hours: int | None = None,
    ) -> dict[str, Any]:
        """Return the total advert count for one contact type."""
        params: dict[str, Any] = {"contact_type": contact_type}
        if hours is not None:
            params["hours"] = hours
        return await self._async_request_wrapped(
            "GET",
            "/api/adverts_count_by_contact_type",
            params=params,
        )

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

    @staticmethod
    def validate_acl_permissions(value: Any) -> int:
        """Firmware role is the low two bits; retain the whole permissions byte."""
        value = PyMCRepeaterApiClient.validate_query_integer(value, 1, 255)
        if value & 3 == 0:
            raise PyMCRepeaterApiError("Guest role is not assignable; remove the ACL entry instead")
        return value

    @staticmethod
    def validate_acl_public_key(value: Any) -> str:
        """Require an exact full public key without normalization."""
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise PyMCRepeaterApiError("client_pubkey must be exactly 64 hexadecimal characters")
        return value

    async def async_set_acl_permissions(
        self, *, identity_name: str, client_pubkey: str, permissions: int,
    ) -> dict[str, Any]:
        """Add/change an ACL role; room non-admin roles may be nonpersistent."""
        body = {"identity_name": self.validate_management_name(identity_name),
                "client_pubkey": self.validate_acl_public_key(client_pubkey),
                "permissions": self.validate_acl_permissions(permissions)}
        data = await self._async_management_payload("POST", "/api/acl_set_permissions", json_body=body)
        return {key: data[key] for key in ("identity_name", "identity_type", "client_pubkey", "permissions", "permissions_value", "persisted") if key in data}

    async def async_remove_acl_client(
        self,
        *,
        public_key: str,
        identity_hash: str | None = None,
        identity_name: str | None = None,
    ) -> dict[str, Any]:
        """Remove an authenticated client from one or more ACLs."""
        payload: dict[str, Any] = {"public_key": public_key}
        if identity_name is not None:
            payload["identity_name"] = self.validate_management_name(identity_name)
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

    async def async_get_neighbor_scopes(self) -> dict[str, Any]:
        """Return stored neighbor scopes plus this Repeater's served scopes."""
        payload = await self._async_request_json(
            "GET", "/api/neighbor_scopes", auth="api_token"
        )
        if payload.get("success") is False:
            raise PyMCRepeaterApiError(
                payload.get("error", "Failed to fetch neighbor scopes")
            )
        scopes = payload.get("data") or {}
        return {
            "scopes": scopes,
            "count": payload.get("count", len(scopes) if isinstance(scopes, dict) else 0),
            "served": payload.get("served"),
        }

    async def async_query_neighbor_scopes(self, pubkey: str) -> dict[str, Any]:
        """Query one zero-hop neighbor for its served region scopes."""
        return await self._async_request_wrapped(
            "POST",
            "/api/query_neighbor_scopes",
            json_body={"pubkey": pubkey},
            timeout_seconds=NEIGHBOR_SCOPE_QUERY_TIMEOUT,
        )

    async def async_publish_neighbors(self) -> Any:
        """Schedule a neighbor discovery and MQTT publication cycle."""
        return await self._async_request_wrapped(
            "POST", "/api/publish_neighbors", json_body={}
        )

    async def async_send_advert(self, mode: str = "flood") -> Any:
        """Trigger a flood or direct repeater advert send."""
        return await self._async_request_wrapped(
            "POST", "/api/send_advert", json_body={"mode": mode},
            # Backend waits up to 10 seconds; allow 5 seconds for HTTP.
            timeout_seconds=15,
        )

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
        if not 1 <= timeout <= 60:
            raise PyMCRepeaterApiError("Ping timeout must be between 1 and 60 seconds")
        return await self._async_request_wrapped(
            "POST",
            "/api/ping_neighbor",
            json_body={"target_id": target_id, "timeout": timeout},
            # Backend waits timeout + 1; allow another 5 seconds for HTTP.
            timeout_seconds=timeout + 6,
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

    async def async_cad_calibration_start(
        self,
        samples: int = 8,
        delay: int = 100,
        known_signal_present: bool = False,
        cad_symbol_num: int = 2,
        cad_timeout_ms: int = 500,
    ) -> Any:
        """Start CAD calibration."""
        return await self._async_request_wrapped(
            "POST",
            "/api/cad_calibration_start",
            json_body={
                "samples": samples,
                "delay": delay,
                "known_signal_present": known_signal_present,
                "cad_symbol_num": cad_symbol_num,
                "cad_timeout_ms": cad_timeout_ms,
            },
        )

    async def async_cad_calibration_stop(self) -> Any:
        """Stop CAD calibration."""
        return await self._async_request_wrapped(
            "POST", "/api/cad_calibration_stop", json_body={}
        )

    async def async_cad_manual_check(
        self,
        *,
        samples: int = 1,
        det_peak: int | None = None,
        det_min: int | None = None,
        cad_symbol_num: int | None = None,
        cad_timeout_ms: int = 500,
        apply_live: bool = False,
    ) -> dict[str, Any]:
        """Run one or more immediate CAD checks."""
        payload: dict[str, Any] = {
            "samples": samples,
            "cad_timeout_ms": cad_timeout_ms,
            "apply_live": apply_live,
        }
        if det_peak is not None:
            payload["det_peak"] = det_peak
        if det_min is not None:
            payload["det_min"] = det_min
        if cad_symbol_num is not None:
            payload["cad_symbol_num"] = cad_symbol_num
        return await self._async_request_wrapped(
            "POST", "/api/cad_manual_check", json_body=payload,
            # Mirror backend-clamped sample/time bounds and its 2-second margin,
            # then allow 5 seconds for HTTP. Calibration start is asynchronous.
            timeout_seconds=max(
                REQUEST_TIMEOUT,
                min(32, max(1, samples)) * min(5000, max(50, cad_timeout_ms)) / 1000 + 7,
            ),
        )

    async def async_save_cad_settings(
        self,
        *,
        peak: int,
        min_val: int,
        cad_symbol_num: int = 2,
        detection_rate: int = 0,
    ) -> Any:
        """Save CAD settings."""
        return await self._async_request_wrapped(
            "POST",
            "/api/save_cad_settings",
            json_body={
                "peak": peak,
                "min_val": min_val,
                "cad_symbol_num": cad_symbol_num,
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
        result = await self._async_request_wrapped(
            "POST", "/api/companion/send_text", json_body=payload,
            # Companion _run_async defaults to 30 seconds, plus HTTP margin.
            timeout_seconds=35,
        )
        if isinstance(result, dict) and result.get("sent") is False:
            raise PyMCRepeaterApiError("Companion did not send the message")
        return result

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
        result = await self._async_request_wrapped(
            "POST", "/api/companion/send_channel_message", json_body=payload,
            # Companion _run_async defaults to 30 seconds, plus HTTP margin.
            timeout_seconds=35,
        )
        if isinstance(result, dict) and result.get("sent") is False:
            raise PyMCRepeaterApiError("Companion did not send the message")
        return result

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
            "POST", "/api/companion/login", json_body=payload,
            # Backend login waits up to 15 seconds.
            timeout_seconds=20,
        )

    async def async_companion_request_status(
        self,
        *,
        pub_key: str,
        timeout: float = 15.0,
        companion_name: str | None = None,
    ) -> Any:
        """Request status from a companion target."""
        if not 1 <= timeout <= 120:
            raise PyMCRepeaterApiError("Companion timeout must be between 1 and 120 seconds")
        payload: dict[str, Any] = {"pub_key": pub_key, "timeout": timeout}
        if companion_name:
            payload["companion_name"] = companion_name
        return await self._async_request_wrapped(
            "POST", "/api/companion/request_status", json_body=payload,
            # Backend waits timeout + 5; add 5 seconds for HTTP.
            timeout_seconds=timeout + 10,
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
        if not 1 <= timeout <= 120:
            raise PyMCRepeaterApiError("Companion timeout must be between 1 and 120 seconds")
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
            "POST", "/api/companion/request_telemetry", json_body=payload,
            # Backend waits timeout + 5; add 5 seconds for HTTP.
            timeout_seconds=timeout + 10,
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
            "POST", "/api/companion/send_command", json_body=payload,
            # Backend command waits up to 20 seconds.
            timeout_seconds=25,
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
        timeout_seconds: float = REQUEST_TIMEOUT,
    ) -> Any:
        payload = await self._async_request_json(
            method,
            path,
            params=params,
            json_body=json_body,
            auth="api_token",
            timeout_seconds=timeout_seconds,
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

    @staticmethod
    async def _async_read_bounded_json(response: ClientResponse, maximum: int) -> Any:
        """Bound decoded HTTP bytes before parsing, including error responses."""
        import json
        body = bytearray()
        while True:
            chunk = await response.content.read(min(65536, maximum + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > maximum:
                raise PyMCRepeaterApiError("Management response exceeds byte limit")
        return json.loads(body)

    async def _async_request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: str = "api_token",
        bearer_token: str | None = None,
        max_response_bytes: int | None = None,
        plugin_request: bool = False,
        timeout_seconds: float = REQUEST_TIMEOUT,
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

        # Override the shared session's shorter default only for slow plugin IPC.
        request_options: dict[str, Any] = {"timeout": ClientTimeout(total=timeout_seconds)} if plugin_request else {}
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    **request_options,
                ) as response:
                    if response.status in (401, 403):
                        raise PyMCRepeaterAuthenticationError(
                            f"Authentication failed for {path}"
                        )
                    if response.status >= 400:
                        if plugin_request:
                            # IPC 504 and conflict 409 must retain ambiguity, not
                            # become generic failures or expose installation logs.
                            try:
                                error_payload = (await self._async_read_bounded_json(response, max_response_bytes)
                                                 if max_response_bytes is not None else await response.json(content_type=None))
                            except ValueError:
                                error_payload = {}
                            return {"success": False, "http_status": response.status,
                                    "outcome": error_payload.get("outcome") if isinstance(error_payload, dict) else None}
                        detail = await response.text()
                        raise PyMCRepeaterApiError(
                            f"HTTP {response.status} from {path}: {detail[:200]}"
                        )
                    payload = (await self._async_read_bounded_json(response, max_response_bytes)
                               if max_response_bytes is not None else await response.json(content_type=None))
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
        except (ValueError, RecursionError) as err:
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
