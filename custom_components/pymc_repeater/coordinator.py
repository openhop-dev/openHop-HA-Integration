"""Data coordinator for openHop Repeater."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    PyMCRepeaterApiClient,
    PyMCRepeaterAuthenticationError,
    PyMCRepeaterCannotConnect,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)
GPS_STREAM_RETRY_SECONDS = 15


class PyMCRepeaterDataUpdateCoordinator(DataUpdateCoordinator[dict]):
    """Coordinate openHop Repeater polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: PyMCRepeaterApiClient,
    ) -> None:
        configured_scan_interval = int(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)
        )
        configured_scan_interval = max(
            MIN_SCAN_INTERVAL_SECONDS,
            min(MAX_SCAN_INTERVAL_SECONDS, configured_scan_interval),
        )
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=configured_scan_interval),
        )
        self.config_entry = entry
        self.api = api
        self.last_successful_poll: datetime | None = None
        self._gps_stream_task: asyncio.Task | None = None
        self._unsub_update_check: Callable[[], None] | None = None
        self._update_check_running = False
        entry.async_on_unload(self._async_cancel_update_check)

    async def async_start_runtime(self) -> None:
        """Start background runtime tasks."""
        if self._unsub_update_check is None:
            # HA's local-time helper owns timezone/DST handling; omitted hour
            # matches every hour. Registration does not check immediately.
            self._unsub_update_check = async_track_time_change(
                self.hass, self._async_hourly_update_check, minute=1, second=0
            )
        if self._gps_stream_task is None:
            self._gps_stream_task = self.config_entry.async_create_background_task(
                self.hass,
                self._async_gps_stream_loop(),
                "pymc_repeater_gps_stream",
            )

    async def async_stop_runtime(self) -> None:
        """Stop background runtime tasks."""
        self._async_cancel_update_check()
        if self._gps_stream_task is not None:
            self._gps_stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._gps_stream_task
            self._gps_stream_task = None

    @callback
    def _async_cancel_update_check(self) -> None:
        """Remove the hourly listener on stop, unload, or setup failure."""
        if self._unsub_update_check is not None:
            self._unsub_update_check()
            self._unsub_update_check = None

    async def _async_hourly_update_check(self, now: datetime) -> None:
        """Request a cache-respecting version check, not branch discovery."""
        if self._unsub_update_check is None or self._update_check_running:
            return
        status = (self.data or {}).get("update_status")
        if isinstance(status, dict) and status.get("state") in ("installing", "checking"):
            return

        self._update_check_running = True
        try:
            try:
                # The backend's 10-minute cache expires between hourly checks;
                # force=False also preserves its GitHub rate-limit backoff.
                await self.api.async_update_check(force=False)
            except Exception as err:
                _LOGGER.warning("Hourly update check failed: %s", err)
            if self._unsub_update_check is not None:
                try:
                    # Read cached status once; normal polling observes completion.
                    await self.async_request_refresh()
                except Exception as err:
                    _LOGGER.warning("Refresh after hourly update check failed: %s", err)
        finally:
            self._update_check_running = False

    async def _async_update_data(self) -> dict:
        try:
            data = await self.api.async_fetch_all()
            self.last_successful_poll = datetime.now(timezone.utc)
            return data
        except PyMCRepeaterAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PyMCRepeaterCannotConnect as err:
            raise UpdateFailed(str(err)) from err

    async def _async_gps_stream_loop(self) -> None:
        """Listen for GPS stream snapshots and update GPS entities faster than polling."""
        while True:
            try:
                response = await self.api.async_open_gps_stream()
                try:
                    _LOGGER.debug(
                        "Connected GPS stream for %s", self.config_entry.entry_id
                    )
                    async for raw_line in response.content:
                        event = self.api.decode_sse_payload(raw_line)
                        if not event:
                            continue
                        if event.get("type") != "snapshot":
                            continue
                        snapshot = event.get("data")
                        if not isinstance(snapshot, dict):
                            continue
                        self._async_apply_gps_snapshot(snapshot)
                finally:
                    response.close()
            except asyncio.CancelledError:
                raise
            except PyMCRepeaterAuthenticationError as err:
                _LOGGER.warning(
                    "GPS stream auth failed for %s: %s",
                    self.config_entry.entry_id,
                    err,
                )
                return
            except (PyMCRepeaterCannotConnect, UpdateFailed) as err:
                _LOGGER.debug(
                    "GPS stream temporarily unavailable for %s: %s",
                    self.config_entry.entry_id,
                    err,
                )
            except Exception as err:
                _LOGGER.debug(
                    "GPS stream error for %s: %s",
                    self.config_entry.entry_id,
                    err,
                )

            await asyncio.sleep(GPS_STREAM_RETRY_SECONDS)

    def _async_apply_gps_snapshot(self, snapshot: dict) -> None:
        """Apply a GPS snapshot from the SSE stream."""
        current = dict(self.data or {})
        old_snapshot = current.get("gps")
        if self._same_snapshot(old_snapshot, snapshot):
            return
        current["gps"] = snapshot
        self._async_publish_partial_data(current)

    def _async_publish_partial_data(self, data: dict) -> None:
        """Notify entities without postponing the coordinator's full refresh."""
        self.data = data
        self.async_update_listeners()

    @staticmethod
    def _same_snapshot(old_snapshot: object, new_snapshot: dict) -> bool:
        """Compare two coordinator snapshots."""
        if not isinstance(old_snapshot, dict):
            return False
        return json.dumps(old_snapshot, sort_keys=True, default=str) == json.dumps(
            new_snapshot, sort_keys=True, default=str
        )
