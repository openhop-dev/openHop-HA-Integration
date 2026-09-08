<p align="center">
  <img src="custom_components/pymc_repeater/brand/icon.png" alt="openHop Repeater" width="150">
</p>

<h1 align="center">openHop Repeater Integration for Home Assistant</h1>

<p align="center">
  Monitor and control an <a href="https://github.com/openhop-dev/openhop_repeater">openHop Repeater</a> from Home Assistant.
</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=white" alt="HACS Custom"></a>
  <a href="https://github.com/openhop-dev/openHop-HA-Integration/releases"><img src="https://img.shields.io/github/v/release/openhop-dev/openHop-HA-Integration?style=for-the-badge" alt="Latest release"></a>
  <a href="https://discord.gg/3s8MMaSTzq"><img src="https://img.shields.io/discord/1489331292309946508?style=for-the-badge&logo=discord&logoColor=white&label=Discord&color=5865F2" alt="openHop Discord"></a>
</p>

<p align="center">
  <a href="https://github.com/openhop-dev/openHop-HA-Integration/actions/workflows/hacs.yaml"><img src="https://img.shields.io/github/actions/workflow/status/openhop-dev/openHop-HA-Integration/hacs.yaml?branch=main&style=for-the-badge&label=HACS" alt="HACS validation"></a>
  <a href="https://github.com/openhop-dev/openHop-HA-Integration/actions/workflows/hassfest.yaml"><img src="https://img.shields.io/github/actions/workflow/status/openhop-dev/openHop-HA-Integration/hassfest.yaml?branch=main&style=for-the-badge&label=Hassfest" alt="Hassfest"></a>
  <a href="https://github.com/openhop-dev/openHop-HA-Integration/actions/workflows/python-smoke.yaml"><img src="https://img.shields.io/github/actions/workflow/status/openhop-dev/openHop-HA-Integration/python-smoke.yaml?branch=main&style=for-the-badge&label=Tests" alt="Tests"></a>
</p>

## About

This custom integration connects Home Assistant directly to the Repeater's local HTTP API. During setup it signs in once with the Repeater admin password, creates a dedicated API token, stores that token in the Home Assistant config entry, and discards the admin password.

The integration uses coordinated local polling instead of making a separate API request for every entity. The polling interval is configurable in the integration options and defaults to 15 seconds.

Normal polling reads the Repeater's cached update status without discovering GitHub branches. A separate scheduled check runs at one minute past each hour (`HH:01:00`) in Home Assistant's configured timezone, respecting the Repeater's cache and rate-limit hold. It does not check immediately on startup or install anything, and skips a check already in progress or an installation. The **Check for updates** button and explicit action still request a manual check. The channel selector uses `main`, `dev`, and the current channel without querying GitHub.

> [!NOTE]
> The integration domain and folder remain `pymc_repeater` so existing installations and entity registry entries continue to work. The user-facing name is **openHop Repeater**.

## Highlights

- UI-based setup and options flows
- Configurable integration-wide polling interval
- Repeater, single/multi-radio stack, packet, routing, and signal-quality telemetry
- MQTT broker, handler, and neighbor-publication status
- Hardware, process, network, database, and metrics diagnostics
- GPS position, fix, satellite, time-sync, and location-update data
- External sensor-manager entities, including supported modem and UPS readings
- Application-plugin health counts (installed, enabled, running, and failed)
- Neighbor-link counts, neighbor-scope queries, and on-demand neighbor history
- Default-region, duty-cycle, advert-rate, advert-schedule, and Repeater-mode controls
- Update status, update-channel selection, and update actions
- CAD calibration controls and manual CAD checks
- Native Home Assistant diagnostics and an extensive example dashboard

## Requirements

- Home Assistant 2024.1 or newer
- A running [openHop Repeater](https://github.com/openhop-dev/openhop_repeater)
- The Repeater HTTP API reachable from Home Assistant
- The Repeater admin password for initial setup or reauthentication
- A trusted local network, VPN, or another secure path between Home Assistant and the Repeater

## Installation

### HACS

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=openhop-dev&repository=openHop-HA-Integration&category=Integration)

This integration is currently installed as a HACS custom repository:

1. Open **HACS → Integrations**.
2. Open the top-right menu and select **Custom repositories**.
3. Add:

   ```text
   https://github.com/openhop-dev/openHop-HA-Integration
   ```

4. Select **Integration** as the category.
5. Install **openHop Repeater**.
6. Restart Home Assistant.

### Manual installation

1. Download the latest release.
2. Copy `custom_components/pymc_repeater` into your Home Assistant configuration directory:

   ```text
   /config/custom_components/pymc_repeater
   ```

3. Restart Home Assistant.

## Setup

After installation and restart:

1. Open **Settings → Devices & services**.
2. Select **Add integration**.
3. Search for **openHop Repeater**.
4. Enter the Repeater hostname or IP address, HTTP API port, and admin password.
5. Submit the form.

Home Assistant will create and retain a dedicated API token. The admin password is not stored after setup completes.

### Integration options

Open **Settings → Devices & services → openHop Repeater → Configure** to change:

- Integration polling interval, defaulting to 15 seconds
- Data-size display unit
- Uptime display unit

Changing an option reloads the integration automatically.

## Dashboard template

A comprehensive native Lovelace view is included at:

[`dashboards/openhop_repeater_dashboard.yaml`](dashboards/openhop_repeater_dashboard.yaml)

The template covers radio health and stack diagnostics, packet flow, LBT diagnostics, routing, neighbor links, plugin health, controls, advert tuning, MQTT, companions, GPS, external modem power readings, updates, and database metrics.

To use it:

1. Find one Repeater entity in Home Assistant, such as `sensor.my_repeater_repeater_version`.
2. Copy the entity prefix—in this example, `my_repeater`.
3. Replace every `REPEATER_SLUG` in the template with that prefix.
4. Create or edit a dashboard view and paste the template into the view's YAML editor.
5. Optionally change the view `title` and `path`.
6. Replace the marked example MQTT broker and companion rows with entities from your installation.
7. The modem percentage card automatically finds active battery and solar-rate entities even when Home Assistant adds an area prefix or numeric suffix.
8. For other dynamic rows, replace the complete example entity ID with the active entity ID shown in your instance. If the external sensor is not named `modem`, also update `_sensor_modem_` in the percentage card's two match strings.

### Layout and compatibility

- Uses built-in Home Assistant cards; no custom card installation is required
- Groups the view into **Live overview**, **Recent trends**, **Operations**, **Diagnostics**, and **Reference notes**
- Uses three responsive desktop columns and natural-height detail cards, with dense placement disabled to keep the overview first
- Keeps key metrics and optional battery/temperature in the overview; detailed controls, GPS, and secondary readings stay below
- Shows named badges, compact metric tiles, and explicit API, statistics, and radio problem banners; disabled GPS does not trigger an alarm

The template uses the current **Sections** frontend, which requires a newer Home
Assistant frontend than the integration's minimum supported version. Configuration
was saved and read back on HA 2026.9; that is not a rendered-layout verification.
Numeric precision remains controlled by Home Assistant, without global entity-registry changes.

### Match entities to your installation

- Use exact entity IDs from the same Repeater config entry, including its radio child devices
- Radio child prefixes are independent of `REPEATER_SLUG`; replacing the parent prefix alone does not resolve every row
- Repeat rows for multiple radios, plugins, or sensor sources, and remove unsupported rows or cards
- Keep the existing view's title, path, icon, and other metadata when replacing it, and back up the complete dashboard first

The diagnostics include endpoint problems, last successful poll, source age and
staleness, radio settings, and individual plugin status. Battery trend means
**charging**, **discharging**, or **neutral**, based on fresh signed charge-rate
readings in `%/h`; it does not infer a full battery. The native update tile opens
more-info and does not install updates automatically.

For a smaller starting point, use the [compact operations view](dashboards/openhop_operations.yaml).

## Alert blueprints

Blueprints are reusable automation templates. Import a template, select the entity
to monitor, and choose the actions to run. Installing the integration does not
create these automations or select a notification destination for you.

### Import and create an automation

1. Open **Settings → Automations & scenes → Blueprints** in Home Assistant
2. Select **Import Blueprint**
3. Copy the link address of one of the templates below and paste it into the import URL field
4. Preview and import the blueprint, then select **Create automation**
5. Choose the entity, sustained duration, and threshold where applicable
6. Under **Actions to run**, add your own notification or other action
7. Give the automation a descriptive name and save it

The links below use the stable `main` branch. To test development blueprints,
replace `/blob/main/` with `/blob/dev/` in the import URL.

| Blueprint | Entity to select |
| --- | --- |
| [Low battery](https://github.com/openhop-dev/openHop-HA-Integration/blob/main/blueprints/automation/openhop/low_battery.yaml) | Battery-percentage sensor; thresholds use the selected sensor unit |
| [High temperature](https://github.com/openhop-dev/openHop-HA-Integration/blob/main/blueprints/automation/openhop/high_temperature.yaml) | Temperature sensor; match the threshold to its unit |
| [Repeater unavailable](https://github.com/openhop-dev/openHop-HA-Integration/blob/main/blueprints/automation/openhop/unavailable.yaml) | A sensor that becomes unavailable when the Repeater disconnects |
| [MQTT disconnected](https://github.com/openhop-dev/openHop-HA-Integration/blob/main/blueprints/automation/openhop/broker_disconnected.yaml) | An individual broker connectivity entity you intend to keep connected, not the aggregate any-broker entity |
| [Stale sensor](https://github.com/openhop-dev/openHop-HA-Integration/blob/main/blueprints/automation/openhop/stale_sensor.yaml) | The source stale problem sensor |
| [Plugin failure](https://github.com/openhop-dev/openHop-HA-Integration/blob/main/blueprints/automation/openhop/plugin_failure.yaml) | The individual plugin problem sensor |
| [Update available](https://github.com/openhop-dev/openHop-HA-Integration/blob/main/blueprints/automation/openhop/update_available.yaml) | The update-available binary sensor |

### Example: low-battery notification

Create an automation from **Low battery** and set:

- **Entity to monitor:** your Repeater's battery-percentage sensor
- **Sustained duration:** 5 minutes
- **Threshold:** 20
- **Actions to run:** your phone's notification action, with a message such as “Repeater battery has been below 20% for five minutes”

Reuse the same blueprint to create separate automations for other Repeaters.
Threshold alerts fire when the value crosses the limit and stays there; they do
not repeatedly fire while the value remains beyond it. Waiting timers reset after
Home Assistant restarts or automations reload.

For manual YAML installation and further entity-selection guidance, see
[alerts and compact view](docs/operational-monitoring.md#alerts-and-compact-view).


## Actions

The integration exposes Home Assistant actions for supported Repeater operations, including:

- Sending flood or direct adverts and restarting the Repeater service
- Checking for and installing updates
- Reading broker presets, neighbor-link history, and stored neighbor scopes
- Querying one zero-hop neighbor's scopes or scheduling an MQTT neighbors publication cycle
- Running manual CAD checks and CAD calibration
- Saving CAD settings
- Reading advert, companion, and contact diagnostics

Open **Developer tools → Actions** and search for `openHop Repeater` or `pymc_repeater` to see the actions and their current fields.

- aligned advanced action http budgets with backend waits plus a finite margin for ping and manual cad checks and companion text sends and login and commands
- bounded ping reply waits to 1–60 seconds with 6 additional http seconds and companion status and telemetry waits to 1–120 seconds with 10 additional http seconds
- added optional `response_variable` support to `pymc_repeater.companion_request_status` and `pymc_repeater.companion_request_telemetry` with unwrapped backend dictionaries and non-dictionary results wrapped under `result` while preserving calls without responses and avoiding polling or entity attributes for these results
- surfaced explicit companion `sent: false` results as action errors without treating omitted `sent` fields on older backends as failures

The raw radio-config action accepts the Repeater dev `radio_id` field for multi-radio targeting and `direct_advert_interval_hours` for the additional advert schedule. The raw MQTT-config action accepts custom `base_topic` values and neighbor-publisher settings supported by current Repeater dev builds.

### Plugin health and bucketed neighbor history

Application-plugin counts use the installed plugin manager's lightweight `/api/plugins/` list on the shared polling schedule. These are separate from external sensor-manager readings. Counts and an allowlist of plugin ID, name, version, enabled, state, and has_runtime enter coordinator data. Paths, settings, logs, PID, descriptions and repository URLs are not retained. An empty inventory reports zero; unsupported/unavailable manager endpoints or malformed inventory leave the counts unknown rather than falsely reporting a healthy empty installation. Authentication and connection failures still fail the regular refresh.

`Enabled plugins` is not the same as `Running plugins`: UI-only plugins can be enabled without a running process. `Failed plugins` counts only the manager's explicit `FAILED` state, not stopped/disabled plugins.

The existing `pymc_repeater.get_neighbor_link_history` response-returning action accepts optional `bucket_seconds` (integer, minimum 60). Omit it to preserve the raw `rows` response. Supply it to receive `buckets`, `bucket_seconds`, and a bucket `count`; `limit` caps returned buckets rather than raw observations. This requires a Repeater build supporting bucketed history and is never polled automatically. For example:

```yaml
action: pymc_repeater.get_neighbor_link_history
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  peer_hash: AB
  path_hash_size: 1
  hours: 24
  limit: 1000
  bucket_seconds: 300
response_variable: neighbor_history
```

Replace the example entry ID and peer hash with your target. Omit `bucket_seconds` for older Repeater builds; there is no silent fallback from buckets to raw rows. See [installed API alignment notes](docs/installed-api-alignment.md) for the audited source contract and intentionally deferred capabilities.

## Authentication and persistent storage

The Home Assistant integration stores an API token, while the Repeater stores the matching token hash in its SQLite database. Both the Repeater JWT secret and SQLite database must persist across Repeater restarts.

For the openHop Home Assistant add-on, use the persistent openHop storage path:

```yaml
storage:
  storage_dir: /var/lib/openhop_repeater
```

Using the legacy, unmapped `/var/lib/pymc_repeater` path in the renamed add-on can cause the API-token database to disappear when the add-on restarts. The integration will then report `Authentication failed for /api/stats` and request reauthentication.

Do not publish your admin password, JWT secret, Home Assistant token, or Repeater API token in an issue or diagnostic upload.

## Security

- The Repeater API is currently accessed over plain `http://`.
- Keep Home Assistant and the Repeater on a trusted network, behind a VPN, or within another secure transport boundary.
- Revoke unused Home Assistant API tokens from the Repeater.
- If a token is revoked or no longer validates, Home Assistant starts its standard reauthentication flow.

## Community and related projects

- [Join the openHop Discord](https://discord.gg/3s8MMaSTzq)
- [openHop Repeater](https://github.com/openhop-dev/openhop_repeater)
- [openHop Repeater Home Assistant add-on](https://github.com/openhop-dev/openHop-HA-Add-on)
- [Release notes](CHANGELOG.md)
- [Issue tracker](https://github.com/openhop-dev/openHop-HA-Integration/issues)

## Operational monitoring

- added parent repeater `radio_status` and `radio_problem` entities from aggregate runtime health rather than api connectivity or configured child radios with `radio_error` exposed only as a boolean or unknown attribute and never raw exception text
- recognized `single_fabric` for single-radio lifecycle handling and guarded global settings fallback to the sole named default while preferring `radio_type` over legacy `type` for configured inventory
- preferred each reading envelope's `poll_interval_seconds` for freshness and retained the legacy global-summary fallback only when that field was absent
- documented that effective per-reading cadence required a companion backend scheduler metadata change not yet released or deployed and that updating this integration alone could not establish legacy plugin cadence

Aggregate flood/direct received, transmitted, and duplicate packet counters are
exposed on the parent Repeater device using existing stats polling. These are
process-lifetime totals, not per-radio counters or hourly rates; missing values
remain unknown.

See [operational monitoring](docs/operational-monitoring.md) for radio child devices, source freshness and component diagnostics, native update installation safety, plugin health, battery units, alert blueprints, and the separate compact operations view.

## Development

The repository includes HACS validation, Hassfest, Python compilation, and contract tests. To run the local checks:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components/pymc_repeater
```

Release versions are defined in `custom_components/pymc_repeater/manifest.json` and documented in [`CHANGELOG.md`](CHANGELOG.md).

Contributions and focused bug reports are welcome. Please include the Home Assistant version, integration version, Repeater version, and relevant redacted logs when reporting a problem.
