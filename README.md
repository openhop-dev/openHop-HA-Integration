<p align="center">
  <img src="custom_components/pymc_repeater/brand/icon.png" alt="openHop Repeater" width="150">
</p>

<h1 align="center">openHop Repeater for Home Assistant</h1>

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

> [!NOTE]
> The integration domain and folder remain `pymc_repeater` so existing installations and entity registry entries continue to work. The user-facing name is **openHop Repeater**.

## Highlights

- UI-based setup and options flows
- Configurable integration-wide polling interval
- Repeater, radio, packet, routing, and signal-quality telemetry
- MQTT broker and handler status
- Hardware, process, network, database, and metrics diagnostics
- GPS position, fix, satellite, time-sync, and location-update data
- External sensor-manager entities, including supported modem and UPS readings
- Neighbor-link counts and on-demand neighbor history
- Default-region, duty-cycle, advert-rate, and Repeater-mode controls
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

The template covers radio health, packet flow, LBT diagnostics, routing, neighbor links, controls, advert tuning, MQTT, companions, GPS, external modem readings, updates, and database metrics.

To use it:

1. Find one Repeater entity in Home Assistant, such as `sensor.my_repeater_repeater_version`.
2. Copy the entity prefix—in this example, `my_repeater`.
3. Replace every `REPEATER_SLUG` in the template with that prefix.
4. Create or edit a dashboard view and paste the template into the view's YAML editor.
5. Optionally change the view `title` and `path`.
6. Replace the marked example MQTT broker and companion rows with entities from your installation.
7. If your external sensor is not named `modem`, replace `_sensor_modem_` with its actual sensor slug.

The dashboard uses only built-in Home Assistant cards.

## Actions

The integration exposes Home Assistant actions for supported Repeater operations, including:

- Sending adverts and restarting the Repeater service
- Checking for and installing updates
- Reading broker presets and neighbor-link history
- Running manual CAD checks and CAD calibration
- Saving CAD settings
- Reading advert, companion, and contact diagnostics

Open **Developer tools → Actions** and search for `openHop Repeater` or `pymc_repeater` to see the actions and their current fields.

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

## Development

The repository includes HACS validation, Hassfest, Python compilation, and contract tests. To run the local checks:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components/pymc_repeater
```

Release versions are defined in `custom_components/pymc_repeater/manifest.json` and documented in [`CHANGELOG.md`](CHANGELOG.md).

Contributions and focused bug reports are welcome. Please include the Home Assistant version, integration version, Repeater version, and relevant redacted logs when reporting a problem.
