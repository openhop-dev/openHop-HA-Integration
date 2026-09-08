# Changelog

## Unreleased

## 1.2.0

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
