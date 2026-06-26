"""Number entities for openHop Repeater."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import PyMCBaseEntity, _nested


@dataclass(frozen=True, kw_only=True)
class PyMCNumberDescription:
    """Description for an openHop number."""

    key: str
    name: str
    icon: str
    min_value: float
    max_value: float
    step: float
    unit: str | None
    mode: NumberMode
    value_fn: Callable[[dict[str, Any]], float | int | None]
    set_fn: Callable[[object, float], Awaitable[object]]


NUMBERS: tuple[PyMCNumberDescription, ...] = (
    PyMCNumberDescription(
        key="max_airtime_percent",
        name="Max airtime percent",
        icon="mdi:percent-circle-outline",
        min_value=0.1,
        max_value=100.0,
        step=0.1,
        unit=PERCENTAGE,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(data, "stats", "config", "duty_cycle", "max_airtime_percent"),
        set_fn=lambda api, value: api.async_update_duty_cycle_config(max_airtime_percent=value),
    ),
    PyMCNumberDescription(
        key="advert_bucket_capacity",
        name="Advert bucket capacity",
        icon="mdi:bucket-outline",
        min_value=1,
        max_value=100,
        step=1,
        unit=None,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_rate_limit", "bucket_capacity"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            bucket_capacity=int(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_refill_tokens",
        name="Advert refill tokens",
        icon="mdi:water-plus-outline",
        min_value=1,
        max_value=100,
        step=1,
        unit=None,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_rate_limit", "refill_tokens"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            refill_tokens=int(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_refill_interval",
        name="Advert refill interval",
        icon="mdi:timer-refresh-outline",
        min_value=60,
        max_value=86400,
        step=60,
        unit=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data,
            "stats",
            "config",
            "repeater",
            "advert_rate_limit",
            "refill_interval_seconds",
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            refill_interval_seconds=int(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_min_interval",
        name="Advert minimum interval",
        icon="mdi:timer-lock-outline",
        min_value=0,
        max_value=86400,
        step=60,
        unit=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_rate_limit", "min_interval_seconds"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            min_interval_seconds=int(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_violation_threshold",
        name="Advert violation threshold",
        icon="mdi:counter",
        min_value=1,
        max_value=100,
        step=1,
        unit=None,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_penalty_box", "violation_threshold"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            violation_threshold=int(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_violation_decay",
        name="Advert violation decay",
        icon="mdi:timer-sand",
        min_value=60,
        max_value=604800,
        step=60,
        unit=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_penalty_box", "violation_decay_seconds"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            violation_decay_seconds=int(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_base_penalty",
        name="Advert base penalty",
        icon="mdi:alert-circle-outline",
        min_value=60,
        max_value=604800,
        step=60,
        unit=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_penalty_box", "base_penalty_seconds"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            base_penalty_seconds=int(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_penalty_multiplier",
        name="Advert penalty multiplier",
        icon="mdi:multiplication",
        min_value=1.0,
        max_value=10.0,
        step=0.1,
        unit=None,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_penalty_box", "penalty_multiplier"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            penalty_multiplier=float(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_max_penalty",
        name="Advert max penalty",
        icon="mdi:alert-octagon",
        min_value=60,
        max_value=604800,
        step=60,
        unit=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_penalty_box", "max_penalty_seconds"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            max_penalty_seconds=int(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_ewma_alpha",
        name="Advert EWMA alpha",
        icon="mdi:sigma",
        min_value=0.01,
        max_value=1.0,
        step=0.01,
        unit=None,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_adaptive", "ewma_alpha"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            ewma_alpha=float(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_hysteresis",
        name="Advert hysteresis",
        icon="mdi:waves-arrow-right",
        min_value=0,
        max_value=86400,
        step=1,
        unit=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_adaptive", "hysteresis_seconds"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            hysteresis_seconds=int(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_quiet_max",
        name="Advert quiet max",
        icon="mdi:volume-low",
        min_value=0.0,
        max_value=1.0,
        step=0.01,
        unit=None,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_adaptive", "thresholds", "quiet_max"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            quiet_max=float(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_normal_max",
        name="Advert normal max",
        icon="mdi:volume-medium",
        min_value=0.0,
        max_value=1.0,
        step=0.01,
        unit=None,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_adaptive", "thresholds", "normal_max"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            normal_max=float(value)
        ),
    ),
    PyMCNumberDescription(
        key="advert_busy_max",
        name="Advert busy max",
        icon="mdi:volume-high",
        min_value=0.0,
        max_value=1.0,
        step=0.01,
        unit=None,
        mode=NumberMode.BOX,
        value_fn=lambda data: _nested(
            data, "stats", "config", "repeater", "advert_adaptive", "thresholds", "busy_max"
        ),
        set_fn=lambda api, value: api.async_update_advert_rate_limit_config(
            busy_max=float(value)
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up openHop Repeater numbers."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    async_add_entities(PyMCNumberEntity(entry, coordinator, api, desc) for desc in NUMBERS)


class PyMCNumberEntity(PyMCBaseEntity, NumberEntity):
    """An openHop number entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, coordinator, api, description: PyMCNumberDescription) -> None:
        super().__init__(entry, coordinator)
        self._api = api
        self.description = description
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_native_min_value = description.min_value
        self._attr_native_max_value = description.max_value
        self._attr_native_step = description.step
        self._attr_native_unit_of_measurement = description.unit
        self._attr_mode = description.mode
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        value = self.description.value_fn(self.coordinator.data)
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        await self.description.set_fn(self._api, value)
        await self.coordinator.async_request_refresh()

