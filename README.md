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
- Named radio airtime budgets, cached noise, packet-window and LBT summaries when the backend supplies per-radio telemetry
- MQTT broker, handler, and neighbor-publication status
- Hardware, process, network, database, and metrics diagnostics
- GPS position, fix, satellite, time-sync, and location-update data
- External sensor-manager entities, including supported modem and UPS readings
- Application-plugin health counts (installed, enabled, running, and failed)
- [Explicit plugin update checks, single upgrades and sequential update-all](docs/plugin-upgrades.md), with an opt-in [daily 03:00 automation example](examples/daily-plugin-upgrades.yaml); no plugin schedule is enabled automatically
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

### Install management companion scripts

The 1.3.0 view also includes read-only catalogue/update checks, an explicitly
confirmed bulk upgrade, sensor-type inspection, five on-demand diagnostic buttons,
and short plugin/settings, sensor and ACL editor workflows.

Merge [`examples/openhop_dashboard_scripts.yaml`](examples/openhop_dashboard_scripts.yaml)
into your existing `scripts.yaml` without overwriting existing scripts. Replace
**every `EXAMPLE_CONFIG_ENTRY_ID`** with the actual integration entry ID selected
in Developer tools → Actions (`config_entry_id` in its YAML) or shown in the
integration entry URL. **`REPEATER_SLUG` is an entity prefix, not an entry ID.**
Rename the `openhop_example_...` script IDs and matching dashboard targets for
each additional Repeater, check configuration, and reload scripts. These script
mappings belong inside the file included by `script: !include scripts.yaml`,
not under a second `script:` key. Remove script buttons if not installing them.

Response-only actions use sibling `response_variable` in companion scripts, not
direct Lovelace calls. Notifications show only public outcome summaries, never
configuration, keys or logs. Required lifecycle/configuration/ACL fields are
entered through **Developer tools → Actions**, not a one-click placeholder write.
All write wrappers require explicit review confirmation; uninstall preserves data.
Read the [dashboard workflow guide](docs/dashboard-management.md) and
[management action contracts](docs/management-actions.md) before changing settings
or access permissions. Configuration reads and sensitive edit inputs remain
editor-only and may appear in private HA traces; never store them as sensor attrs.
No automation schedule or automatic Repeater restart is installed.

### Layout and compatibility

- Uses built-in Home Assistant cards; no custom card installation is required
- Groups the view into **Live overview**, **Recent trends**, **Operations**, **Diagnostics**, and **Reference notes**
- Uses three responsive desktop columns and natural-height detail cards, with dense placement disabled to keep the overview first
- Keeps key metrics and optional battery/temperature in the overview; detailed controls, GPS, and secondary readings stay below
- Shows named badges, compact metric tiles, and explicit API, statistics, and radio problem banners; disabled GPS does not trigger an alarm

The template uses the current **Sections** frontend, which requires a newer Home
Assistant frontend than the integration's minimum supported version. An earlier
layout was saved and read back on HA 2026.9; the new management extension has only
local structural/YAML verification, not live schema or rendered-layout verification.
Numeric precision remains controlled by Home Assistant, without global entity-registry changes.

### Match entities to your installation

- Use exact entity IDs from the same Repeater config entry, including its radio child devices
- Radio child prefixes are independent of `REPEATER_SLUG`; replacing the parent prefix alone does not resolve every row
- Replace every complete `sensor.EXAMPLE_RADIO_...` telemetry ID with the exact active entity from that radio child; repeat the card for other radios or remove unsupported rows
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

Ping reply waits are bounded to 1–60 seconds, with 6 additional HTTP seconds.
Companion status and telemetry waits accept 1–120 seconds, with 10 additional
HTTP seconds; text/channel sends, login and commands have finite budgets matching
backend waits. `companion_request_status` and `companion_request_telemetry` support
optional `response_variable` results while retaining calls without responses.
Explicit `sent: false` raises an action error; older responses without `sent`
remain compatible. Results are never automatically polled or stored in entities.

The raw radio-config action accepts the Repeater dev `radio_id` field for multi-radio targeting and `direct_advert_interval_hours` for the additional advert schedule. The raw MQTT-config action accepts custom `base_topic` values and neighbor-publisher settings supported by current Repeater dev builds.

### Radio diagnostics and rate-history actions

These five actions return data through `response_variable` and never trigger a
coordinator refresh or add background requests:

| Action | Fields |
| --- | --- |
| `pymc_repeater.get_radio_packet_rates` | `hours` 1–168; optional `bucket_seconds` 60–86400 |
| `pymc_repeater.get_noise_floor_stats` | `hours` 1–168; optional exact `radio_id`; zero-sample mean is unknown |
| `pymc_repeater.get_crc_error_count` | `hours` 1–168; optional exact `radio_id` |
| `pymc_repeater.get_companion_stats` | `type`: `core`, `radio`, or `packets`; optional `companion_name`; local diagnostics, not remote RF telemetry |
| `pymc_repeater.get_lbt_diagnostics` | `hours` 1–168; optional `bucket_seconds` 60–3600 and `severe_attempt_threshold` 2–16; no `radio_id` filter |

All default to 24 hours where applicable. Omitted bucket sizes retain backend
defaults. Supply `config_entry_id` when multiple Repeaters are configured. For example:

```yaml
action: pymc_repeater.get_radio_packet_rates
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  hours: 6
  bucket_seconds: 300
response_variable: radio_rates
```

New endpoints require a supporting Repeater build. Unsupported endpoints return
an action error rather than invented data. Noise statistics retain the established
unwrapped `stats` dictionary. Other dictionaries are returned without reshaping;
non-dictionary results use `result`. Rate buckets can include unattributed counts;
physical TX counts can exceed parent packet totals because of fan-out.
Advert sends now allow a 15-second HTTP budget around the backend's 10-second wait.

### Plugin lifecycle, sensor configuration and ACL permissions

[Explicit management actions](docs/management-actions.md) cover catalogue list/install,
plugin enable/disable/start/stop/restart/uninstall, effective settings read and full
settings replacement; sensor type/configuration read and complete configuration
replacement; and ACL role assignment plus named-identity client removal.

Plugin and sensor actions require response variables, stay out of coordinator
polling, and do not trigger immediate refreshes. Plugin writes share fail-fast
admission with upgrades; uncertain completion requires Repeater reconciliation
before entry reload, never blind retries. Uninstall preserves data unless
`delete_data: true` is explicit. Configuration reads redact common credential keys
by default; `include_sensitive: true` is opt-in and can expose credentials to HA
traces. Writes require actual complete JSON objects, not partial patches or encoded
strings. Sensor `*****` password masks and `_original_name` rename hints are
preserved; saving requires a separate Repeater restart to apply.

`set_acl_permissions` accepts a full client public key, exact identity name and
permissions byte 1–255 whose low two bits are 1 read-only, 2 read-write or 3 admin.
Room servers persist only admins; inspect the optional `persisted` response.
`remove_acl_client` adds `identity_name` while preserving `public_key` and hash-only
legacy calls. These ACL writes refresh telemetry once after success.

Manual wheel upload remains in the Repeater UI: backend multipart `wheel` upload
is not a HA filesystem path, and no confined bounded HA file-upload contract is
provided. Plugin logs/progress/runtime documents and forced sensor hardware reads
are intentionally not added. See the management guide for budgets, bounds,
replacement semantics, side effects, examples and verification limitations.

### Plugin health and bucketed neighbor history

Application-plugin counts use the installed plugin manager's lightweight `/api/plugins/` list on the shared polling schedule. These are separate from external sensor-manager readings. Counts and an allowlist of plugin ID, name, version, enabled, state, and has_runtime enter coordinator data. Paths, settings, logs, PID, descriptions and repository URLs are not retained. An empty inventory reports zero; unsupported/unavailable manager endpoints or malformed inventory leave the counts unknown rather than falsely reporting a healthy empty installation. Authentication and connection failures still fail the regular refresh.

`Enabled plugins` is not the same as `Running plugins`: UI-only plugins can be enabled without a running process. `Failed plugins` counts only the manager's explicit `FAILED` state, not stopped/disabled plugins.

The existing `pymc_repeater.get_neighbor_link_history` response-returning action accepts optional `bucket_seconds` (integer, 60–86400). Omit it to preserve the raw `rows` response. Supply it to receive `buckets`, `bucket_seconds`, and a bucket `count`; `limit` caps returned buckets rather than raw observations. Optional `radio_id` filters by exact backend ID; `by_radio: true` splits buckets by receiving radio and requires `bucket_seconds`. Omit these new fields for older builds; historical result IDs are backend IDs, not HA aliases. This action is never polled automatically. For example:

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

Parent `radio_status` and `radio_problem` describe aggregate runtime health,
not API connectivity or the health of each configured radio. Raw radio exceptions
are not exposed in those entities. Child configuration and explicitly attributed
telemetry remain separate; aggregate RF counters are never assigned to children.

Freshness prefers each reading's `poll_interval_seconds`. The audited Repeater dev
still omits effective per-reading cadence, so the legacy global-summary fallback
cannot establish every plugin's real interval. HA 1.3.0 does not fix that backend
limitation. See [1.3.0 API and dependency notes](docs/dev-api-1.3.0.md) for exact
source provenance, supported contracts and deliberately excluded administration.

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
