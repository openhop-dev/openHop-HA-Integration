# Changelog

## 1.3.0

- fixed advanced action dispatch by registering native async handlers so home assistant awaits operations and receives actual responses

- added explicit catalogue install and plugin enable, disable, start, stop, restart, data-preserving uninstall, and settings management actions with shared fail-fast write admission and bounded responses
- added sensor type and configuration actions with complete replacement validation, preserved password masks and rename origins, and explicit restart-required save results
- added acl permission management with firmware role-byte bounds and optional responses and extended client removal with named identities while preserving legacy public_key calls
- redacted common credentials from explicit configuration reads by default and documented sensitive opt-in edits, action traces, hardware side effects, and wheel-upload and raw-log limitations
- added bounded response-returning plugin update checks, optional-version single upgrades, and sequential catalogue-only update-all actions without changing polling or enabling a schedule
- guarded overlapping plugin upgrades and stopped uncertain batches without retrying writes while excluding settings and raw installation logs from outcomes
- documented operator-owned daily 03:00 plugin upgrades with an anonymized single-mode automation and captured action responses
- added alias-safe radio child sensors for shared channel utilization and airtime budgets and cached noise without extra polling or assigning aggregate readings to children
- added per-radio one-hour and 24-hour received, duplicate, physical transmission, average rssi, and average snr measurements while keeping sliding windows distinct from lifetime totals
- added per-radio 24-hour lbt transmission, retry, attempt, failure, busy-channel, and severe-contention summaries without storing raw timelines in entity attributes
- added response-returning radio packet rate, noise-floor statistics, crc error count, local companion statistics, and lbt diagnostics actions with bounded queries and no coordinator refresh
- added optional exact radio filters and per-radio bucket grouping to neighbor-history actions while preserving raw rows and omitted-field defaults
- rejected fractional, boolean, and nonfinite neighbor-history query values before http instead of silently truncating or coercing them
- increased advert-send http timeout to 15 seconds to allow for the backend's 10-second response wait
- fixed zero-sample noise averages displaying as measured 0 dbm while preserving legacy replies without sample counts
- added radio telemetry dashboard examples and documented independent child entity ids, shared-channel budgets, fan-out transmission counts, and older-backend limitations
- extended bundled dashboards with response-aware management scripts, confirmed plugin upgrades, editor-only settings and acl workflows, data-preserving uninstall, and on-demand diagnostic buttons
- documented the latest repeater dev api review and unresolved backend per-reading cadence metadata limitation while preserving existing integration identifiers, radio aliases, and polling schedules
- expanded python source-contract ci coverage to 3.11–3.14 and directed dependabot version updates to dev
- checked runtime and ci dependencies while retaining home assistant-managed library versions and the existing minimum home assistant version
- expanded executable client, action, radio-discovery, availability, validation, translation, and dashboard regression coverage

## 1.2.1

- fixed the GPS stream listener blocking Home Assistant startup wrap-up by using a config-entry background task, as reported in [#16](https://github.com/openhop-dev/openHop-HA-Integration/issues/16)

## 1.2.0

- added aggregate parent radio status and problem entities with a boolean or unknown radio error attribute without exposing raw error text or inferring per-radio health from api connectivity
- added aggregate radio health dashboard rows and a badge and problem banner
- recognized `single_fabric` in reversible radio lifecycle handling and guarded single-radio global settings fallback while preferring configured `radio_type` over legacy `type`
- aligned advanced action http budgets with backend waits for ping and manual cad checks and companion sends and login and commands
- bounded ping reply waits to 1–60 seconds and companion status and telemetry waits to 1–120 seconds with finite http margins
- added optional status and telemetry action responses while preserving calls without responses and keeping results out of polling and entity attributes
- surfaced explicit companion send failures as action errors while retaining compatibility with older results without `sent`
- preferred per-reading `poll_interval_seconds` for source freshness with legacy global-summary fallback only when metadata was absent and unknown freshness for invalid metadata
- documented the required backend cadence metadata change as not yet released or deployed without claiming that an integration-only update established legacy plugin cadence

- added automatic retirement and restoration of removed radio devices while preserving custom names and registry IDs, with safe explicit removal of confirmed absent radios
- added explicit radio ID aliases to preserve existing Home Assistant radio devices, custom names, and entity IDs when a repeater's runtime radio ID changes
- added scheduled repeater update checks at one minute past each hour in Home Assistant's timezone, respecting active checks, installations, and GitHub rate-limit holds without fetching branch lists
- added repeater-wide flood/direct received, transmitted, and duplicate packet counters using existing stats polling, with restart-aware totals and dashboard rows
- added radio child devices with read-only frequency, bandwidth, TX power, spreading factor, coding rate, and preamble settings while preserving existing entity IDs and single-radio support
- added component-health diagnostics, last successful poll, source age, and stale-reading indicators; stale, failed, or invalid measurements become unavailable
- added a native Home Assistant update entity with explicit installation on the selected channel while preserving existing update sensors, buttons, and actions
- added aggregate plugin counts and individual version, state, enabled, running, and problem diagnostics without exposing settings, paths, or repository metadata
- added battery, voltage, current, power, and temperature device classes, numeric-string normalization, BME280 pressure, and a modem battery-percentage alias
- added charging, discharging, and neutral battery trends from fresh signed charge-rate readings in `%/h`, without inferring electrical current or a full-battery state
- added seven opt-in alert blueprints for availability, MQTT disconnection, low battery, high temperature, stale readings, plugin failure, and available updates
- added optional `bucket_seconds` to neighbor-history actions while preserving raw rows when omitted
- added MQTT neighbor-publication status and controls, stored neighbor-scope retrieval, and one-neighbor scope queries
- added independent flood/direct advert controls and schedules, radio-stack mode, and configured-radio-count diagnostics
- added readable dashboard update status, including GitHub Limited, Not checked, Up to date, Update available, Checking, Installing, and Check failed, while retaining check/install controls
- reorganized the comprehensive dashboard with overview and trends first, controls next, and grouped diagnostics last; responsive sections and natural-height stacks avoid stretched cards
- added a compact operations dashboard and documented dynamic entity-ID replacement for repeaters and radio child devices
- documented multi-radio `radio_id`, MQTT custom base topics, and neighbor-publisher fields on raw configuration actions
- expanded diagnostics redaction and removed raw transport-key and private identity configuration from coordinator polling
- expanded English translations and client, monitoring, update, and dashboard regression tests
- removed GitHub-backed update-channel discovery from automatic polling while retaining cached local update status and manual checks
- fixed the native update entity reporting up to date before a successful check; unchecked results remain unknown
- increased neighbor-scope query timeout to cover the repeater's 45-second response window instead of the normal 10 seconds
- aligned flood advert interval validation with the repeater's supported `0` or `3–168` hour values
- fixed modem battery/solar percentage displays with Home Assistant area prefixes and numeric entity-ID suffixes

## 1.1.6

- changed the integration-wide API refresh interval to a configurable option, defaulting to 15 seconds
- fixed GPS stream updates so they notify entities without continually postponing the coordinator's regular API refresh
- added support for Repeater dev neighbor-link snapshots and history, including aggregate Home Assistant diagnostics and response-returning actions
- added the Repeater dev manual CAD check action and aligned calibration options with known-signal, CAD symbol count, and timeout controls
- exposed the Repeater metrics storage source and RRD availability diagnostics introduced by the SQLite metrics fallback
- added contract tests for the new Repeater dev API coverage and run them in the Python smoke workflow
- renamed the example dashboard to `openhop_repeater_dashboard.yaml` and replaced it with an anonymized, single-placeholder view covering current telemetry, controls, external modem data, neighbor links, and metrics diagnostics
- reworked the README with relevant HACS, release, openHop Discord, validation, and test badges; streamlined installation and setup guidance; documented options, actions, dashboard use, persistent token storage, and community links
- updated the Python smoke workflow to `actions/setup-python@v7`

## 1.1.5

- fixed the Home Assistant options flow crash on newer Home Assistant versions by avoiding assignment to the read-only `OptionsFlow.config_entry` property
- aligned the CAD settings service validation with newer repeater API bounds for CAD thresholds
- added support for newer Repeater dev API data: packet type stats, LBT diagnostics, default region configuration, and dynamic update channels
- added Home Assistant sensors/binary sensors/selects for default region and LBT/packet-type diagnostics

## 1.1.4

- added Home Assistant entities for the Repeater dev sensor-manager summary and configured sensor plug-in readings, including UPS/power/environment values and boolean flags exposed under `stats.sensors.readings`
- made sensor-manager entities appear when readings arrive after integration setup instead of requiring the readings to be present during the first Home Assistant entity setup pass
- rebranded the Home Assistant integration, HACS name, dashboard title, diagnostics text, and bundled icons from pyMC Repeater to openHop Repeater while keeping the existing `pymc_repeater` integration domain for compatibility

## 1.1.3

- added a Home Assistant action for the new repeater `broker_presets` API endpoint so bundled MC2MQTT broker templates can be queried from HA
- reviewed repeater API changes from `e03174d` to `22adbd1`; the other changes in that range were setup-wizard behavior and update messaging rather than new ongoing telemetry/control surface

## 1.1.2

- fixed the `Packets received per hour` and `Packets forwarded per hour` sensors to use `/api/packet_stats?hours=1` instead of the repeater status counters backed by the capped `recent_packets` buffer
- added newer GPS diagnostics fields from recent repeater API updates, including position source metadata and GPS time sync state
- added Home Assistant actions for `adverts_by_contact_type` and `adverts_count_by_contact_type`

## 1.1.1

- stopped polling GitHub branch data every 60 seconds by removing `update_channels` from the normal integration refresh loop
- kept update status polling local to the repeater while making the update channel UI use a local fallback list instead of live GitHub branch fetches
- reduces unnecessary GitHub API traffic and avoids rate limiting caused by routine Home Assistant polling

## 1.1.0

- moved the `dev` branch forward onto the `1.1.x` release line for continued development

## 1.0.2

- added GPS stream support using `/api/gps_stream` for faster live GPS updates
- kept normal polling for non-GPS entities while allowing GPS entities to refresh immediately from the repeater stream

## 1.0.1

- expanded GPS diagnostics from newer repeater API data
- added additional GPS state, motion, accuracy, time, and NMEA-related entities and attributes

## 1.0.0

Initial stable release of the openHop Repeater Home Assistant integration.

- config flow setup using repeater host, port, and admin password
- dedicated API token bootstrap and token-based polling
- repeater, radio, hardware, database, MQTT, ACL, room, companion, update, and GPS telemetry
- Home Assistant sensors, binary sensors, switches, buttons, selects, and numbers for repeater monitoring and control
- dashboard template for Lovelace
- HACS validation, Hassfest validation, and Python smoke-test workflows
