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
length only when supplied in that radio's `radio` configuration. Settings are
configuration, not proof of measured RF behavior or successful hardware application.
Genuine per-radio traffic/health sensors remain
unsupported until a verified per-radio telemetry contract exists. Quiet RF is
not a failure signal.

- added parent repeater `radio_status` with recognized aggregate states `ok` and `degraded` and `disabled` from existing stats polling and unknown for missing or unrecognized states
- added parent repeater `radio_problem` for degraded or disabled status or an explicit aggregate radio error and reported clear only for `ok` with no error
- exposed `radio_error` on `radio_status` as true for nonempty error text or false for a known state without an error and otherwise unknown without publishing raw exception text in these entities or dashboard cards
- kept aggregate radio health separate from api connectivity and per-radio configuration without inferring rf delivery from a healthy api or quiet traffic
- preferred configured `radio_type` over legacy `type` without treating either as live telemetry
- allowed global `config.radio` to fill missing settings only for a validated sole named default in explicit `single` or `single_fabric` mode and never across multiple radios or ambiguous inventories
- recognized `single_fabric` in the existing reversible radio lifecycle with exactly one authoritative radio id and unchanged alias and two-full-poll absence safeguards
- added aggregate radio status and problem rows with a radio badge and an explicit problem banner to the comprehensive dashboard

## Preserving radio names after a backend ID change

Renaming a radio device in Home Assistant does not change its identity. If the
Repeater configuration changes the radio ID itself, use **Radio ID aliases (JSON)**
in the integration options to associate the new runtime ID with the existing HA
identity. For example, `{"local": "radio0"}` feeds runtime radio `local` into the
existing `radio0` device and entities, preserving their custom names and IDs.
Other radios remain separate. The same mapping also permits the original
`radio0` ID when `local` is absent, so returning to single-radio mode preserves
that device too. Use `{}` to clear aliases. Only map radios whose physical
identity you have confirmed; mappings are not inferred from frequency, list
position, or display names. Duplicate targets, chains, cycles, and simultaneous
source/target ID collisions are rejected.

After two distinct successful full polls confirm a radio is absent, its device is
disabled by the integration rather than deleted. HA disables its associated
entities while retaining custom names, device/entity IDs, and history. When the
canonical radio returns, integration-disabled devices are restored; user-disabled
devices and entities are left alone. Removed radios can still be found by showing
disabled devices. Explicit permanent removal is allowed only for confirmed absent
radio children, never active radios or the parent Repeater. Permanent removal does
not preserve registry identity for later re-addition.

Failed or malformed radio inventories, ambiguous aliases, and empty inventories
never retire devices. Unrelated optional endpoint errors, such as a GitHub
rate-limit error, do not invalidate a healthy radio inventory. GPS notifications
do not count as additional full polls.

## Aggregate traffic counters

Six traffic sensors belong to the parent Repeater device: flood/direct packets
received, flood/direct packets transmitted, and flood/direct duplicates. They
read existing `/api/stats` counters without additional requests. These are
aggregate counters since the Repeater process started, not per-radio readings
or hourly rates. They use `total_increasing` state class so Home Assistant can
account for resets after a Repeater restart. Missing counters remain unknown,
not zero. The comprehensive dashboard includes them in its traffic diagnostics.

## Freshness and component health

One full polling schedule remains in use, alongside the existing independent GPS
SSE stream. `Component api connected` reflects coordinator refresh success;
`Component api last success` records a successful full refresh, not an SSE event.
Optional endpoint errors do not erase unrelated data. Component problem sensors
report explicit endpoint errors for stats, MQTT, hardware, GPS, plugins and update
status. These indicate API payload health, not a claim that every component's
physical subsystem works.

Each sensor-manager reading gains age (seconds) and stale diagnostics.
Missing, invalid, naive or future timestamps, or missing/invalid source cadence,
are unknown, not fresh. Missing sources become unavailable. Source measurements
are unavailable when the read failed, stale, or freshness cannot be established.
Freshness is evaluated on existing coordinator notifications, with shared-poll
resolution; no high-frequency timer or per-sensor polling task is added.

- preferred the reading envelope's effective `poll_interval_seconds` and marked readings stale after three source intervals with a 60-second minimum
- retained the legacy global-summary interval only when per-reading metadata was absent and left present but invalid metadata unknown rather than substituting the global interval
- documented that the required backend scheduler metadata change had not yet been released or deployed and that the integration alone could not supply effective per-reading cadence or prove a legacy plugin's cadence from the global fallback

- aligned advanced action http budgets to cover backend waits with ping timeout plus 6 seconds and companion status or telemetry timeout plus 10 seconds
- enforced reply wait bounds of 1–60 seconds for ping and 1–120 seconds for companion status and telemetry
- scaled manual cad http budgets with backend-clamped sample and timeout bounds plus 7 seconds with a 10-second minimum and 167-second maximum while leaving asynchronous calibration start separate
- allowed 35 seconds for companion text and channel sends and 20 seconds for login and 25 seconds for commands
- added optional `response_variable` support to `pymc_repeater.companion_request_status` and `pymc_repeater.companion_request_telemetry` returning unwrapped backend dictionaries or wrapping other results under `result` without a coordinator refresh or automatic polling or entity-state storage
- preserved calls without requested responses and converted expected client failures to action errors including explicit companion `sent: false` while accepting older results without `sent`

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
Before a successful check, including after a channel change, the latest version
remains unknown rather than claiming the installed version is up to date. A
confirmed result requires a completed check state, a valid check timestamp and
version data, and no reported error. An unconfirmed result cannot enable native
update installation.
The entity itself never switches channel or installs automatically. The coordinator
requests a non-forced update check at `HH:01:00` in HA's configured timezone,
respecting backend rate-limit holds and skipping active checks/installations.
There is no immediate startup check or automatic branch-list discovery.
Explicit Home Assistant `update.install` requests call the
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
