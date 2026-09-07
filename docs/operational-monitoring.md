# Operational monitoring

## Radio support and limitations

Radio child devices use the exact stable backend radio ID, linked to the parent
Repeater device. Inventory is discovered on each shared poll and disappears as
unavailable when removed. The installed API's `stats.radios` is **configuration**,
not live per-radio counters. Therefore the inventory sensor reports a configured
type when supplied, otherwise `configured`. `radio_stack.radio_ids` also works
when `radios` is empty. No aggregate packet, noise, CRC, RSSI or connectivity value
is attributed to a child radio. Read-only configuration sensors expose frequency
(Hz), bandwidth (Hz), TX power (dBm), spreading factor, coding rate and preamble
length only when supplied in that radio's `radio` configuration. In explicit
single mode, global `config.radio` may fill missing fields for the sole named
default radio, never for multiple radios. Settings are configuration, not proof
of measured RF behavior or successful hardware application.
Genuine per-radio traffic/health sensors remain
unsupported until a verified per-radio telemetry contract exists. Quiet RF is
not a failure signal.

## Freshness and component health

One full polling schedule remains in use, alongside the existing independent GPS
SSE stream. `Component api connected` reflects coordinator refresh success;
`Component api last success` records a successful full refresh, not an SSE event.
Optional endpoint errors do not erase unrelated data. Component problem sensors
report explicit endpoint errors for stats, MQTT, hardware, GPS, plugins and update
status. These indicate API payload health, not a claim that every component's
physical subsystem works.

Each sensor-manager reading gains age (seconds) and stale diagnostics. Stale means
source age exceeds three backend `poll_interval_seconds`, with a 60-second minimum.
Missing, invalid, naive or future timestamps, or missing/invalid source cadence,
are unknown, not fresh. Missing sources become unavailable. Source measurements
are unavailable when the read failed, stale, or freshness cannot be established.
Freshness is evaluated on existing coordinator notifications, with shared-poll
resolution; no high-frequency timer or per-sensor polling task is added.

## Plugins

Existing aggregate counts are preserved. Stable plugin IDs additionally identify
version, runtime state, enabled, running and problem entities. Only ID, name,
version, enabled, state and has_runtime are retained from inventory. Paths,
settings, descriptions, process IDs, logs and repository metadata are excluded.
Disabled and UI-only plugins do not require a running process. Enabled runtime
plugins in FAILED or STOPPED indicate a problem; STARTING and unrecognized states
remain unknown. Missing inventory cannot become a healthy zero. These are all
read-only; no plugin lifecycle, install or settings controls are introduced.

## Battery and electrical readings

Battery percentages have battery device class; measured volts/millivolts,
current, power and temperatures have their appropriate classes when units are
known. Generic `voltage_v` and `voltage_mv` retain their supplied units. Numeric
strings are accepted; booleans, NaN and infinity are not numeric measurements.
The signed `solar_charge_rate_percent_per_hour` stays **%/h**, including negative
rates. It is not electric current or power. A separate charge-state trend sensor
uses this signed rate only with a successful, fresh, finite-timestamp reading:
positive means `charging`, negative `discharging`, zero `neutral`. Missing or
nonfinite rates and failed/stale/unknown-age readings yield unknown. This is a
battery trend inference, not a charger-status measurement; zero never means full.
No amps, watts or energy is synthesized.
Existing external-sensor IDs, including the modem compatibility alias, remain.

## Native update entity

`Repeater software` uses the already-polled cached `/api/update/status` data.
It never automatically checks external release services, switches channel, or
installs anything. Explicit Home Assistant `update.install` requests call the
existing install API with `force=false`. Version selection and backup requests
are rejected; only a confirmed available update without a status error is
installable. No progress percentage is invented. The existing update actions,
button, channel selector and diagnostic entities remain available. Installation
can restart the Repeater; subsequent ordinary polls confirm the reported version.

## Alerts and compact view

Copy the YAML files from `blueprints/automation/openhop/` into Home Assistant's
`config/blueprints/automation/openhop/`, then create automations from them. Choose
the actual entity, sustained duration, thresholds where applicable, and **your own
actions**. No notification destination or corrective action is assumed.

- `unavailable.yaml`: select a sensor that becomes unavailable with the Repeater.
- `broker_disconnected.yaml`: select the individual broker connectivity entity,
  not the aggregate any-broker entity. Disabled brokers may be off too; only
  select one you intend to keep connected.
- `low_battery.yaml` / `high_temperature.yaml`: thresholds use the entity's unit.
- `stale_sensor.yaml`: select the new source stale problem sensor.
- `plugin_failure.yaml`: select the per-ID plugin problem sensor.
- `update_available.yaml`: select the native Repeater software update entity.

State/threshold triggers fire after sustained transitions, not repeatedly for an
existing condition. Home Assistant restart or automation reload resets `for`
timers. Unknown/unavailable values do not satisfy numeric thresholds.

The separate [compact operations view](../dashboards/openhop_operations.yaml)
uses built-in cards and does not replace the comprehensive dashboard. Paste into
a single view YAML editor, replace `REPEATER_SLUG`, then select exact dynamic
entities for your installation. Radio and plugin names, external sensor slugs and
entity registry suffixes cannot be predicted by replacing the parent prefix.

## Verification boundary

Stdlib tests execute normalization and extracted entity/client methods with fake
HA/HTTP boundaries and synthetic schemas. They are not Home Assistant integration
tests. A real HA instance is still required to verify entity registration, update
UI/action execution, blueprint selectors/triggers and rendered Lovelace cards.
No live installation, API write, restart or RF test was performed for this batch.
