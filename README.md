# openHop Repeater for Home Assistant

Custom Home Assistant integration for [openHop Repeater](https://github.com/openhop-dev/openhop_repeater).

This integration connects directly to the repeater's local HTTP API, signs in once with the admin password, creates a dedicated API token for Home Assistant, and then uses that token for ongoing polling and history-friendly logging inside HA.

The Home Assistant integration domain and folder remain `pymc_repeater` for compatibility with existing installations while the user-facing brand is openHop Repeater.

## Features

- UI config flow inside Home Assistant
- Prompts for repeater IP or hostname, port, and admin password
- Automatically creates a dedicated API token for Home Assistant
- Stores the API token instead of the admin password after setup
- Polls repeater telemetry, packet stats, radio metrics, hardware stats, database stats, MQTT status, ACL stats, identity totals, and configured Repeater sensor-manager readings
- Exposes Home Assistant sensors and binary sensors for easy dashboards, history graphs, and automations

## Requirements

- A running [openHop Repeater](https://github.com/openhop-dev/openhop_repeater) instance
- The repeater web/API port reachable from Home Assistant
- The repeater admin password
- A trusted local network, VPN, or other secure path between Home Assistant and the repeater

## Installation

### Install with HACS

This integration is intended to be installed in HACS as a custom repository.

1. Open Home Assistant.
2. Go to `HACS` -> `Integrations`.
3. Open the top-right menu and select `Custom repositories`.
4. Paste:

   ```text
   https://github.com/openhop-dev/openHop-HA-Integration
   ```

5. Choose `Integration` as the category.
6. Add the repository.
7. Find `openHop Repeater` in HACS and install it.
8. Restart Home Assistant.

### Manual installation

1. Copy the `custom_components/pymc_repeater` folder into your Home Assistant config directory:

   ```text
   /config/custom_components/pymc_repeater
   ```

2. Your final layout should look like this:

   ```text
   /config/custom_components/pymc_repeater/__init__.py
   /config/custom_components/pymc_repeater/manifest.json
   /config/custom_components/pymc_repeater/config_flow.py
   ...
   ```

3. Restart Home Assistant.

## Setup inside Home Assistant

After installation and restart:

1. Open `Settings` -> `Devices & Services`.
2. Click `Add Integration`.
3. Search for `openHop Repeater`.
4. Enter:
   - Repeater IP address or hostname
   - Repeater HTTP API port
   - Repeater admin password
5. Click `Submit`.

During setup the integration will:

1. Connect to the repeater API
2. Sign in as `admin`
3. Create a dedicated API token for Home Assistant
4. Save that token in the config entry
5. Discard the admin password after the setup flow finishes
6. Start polling repeater data automatically

## What gets added to Home Assistant

Version `1.1.4` includes entities for:

- repeater version and build info
- total, transmitted, and dropped packets
- average RSSI, SNR, and TX delay
- average noise floor
- MQTT broker connection state
- ACL client totals
- registered identity totals
- database size
- CPU, memory, disk usage, and uptime
- configured Repeater sensor plug-ins, including numeric/string readings and boolean flags from the latest sensor-manager payload

## Dashboard template

A native Lovelace dashboard template is included at:

- `dashboards/pymc_repeater_dashboard.yaml`

To use it:

1. Open the YAML file from this repo.
2. Replace `REPEATER_SLUG` with your actual entity prefix.
   Example: `repeater_name_here`
3. In Home Assistant, create a new dashboard or open an existing one in raw YAML mode.
4. Paste the template YAML.
5. Update the example MQTT broker and companion entity rows in the `Network` view so they match the dynamic entities created in your installation.

The template only uses built-in Home Assistant cards, so it does not require extra frontend dependencies.

## Security notes

- The repeater API is currently accessed over `http://`
- Use this integration only on a trusted network, or place both systems behind a VPN or another secure transport boundary
- If the API token is revoked on the repeater, Home Assistant should trigger reauthentication

## Repository structure

```text
custom_components/pymc_repeater/
  __init__.py
  api.py
  binary_sensor.py
  config_flow.py
  const.py
  coordinator.py
  diagnostics.py
  manifest.json
  sensor.py
  translations/en.json
  brand/icon.png
  brand/icon@2x.png
dashboards/
  pymc_repeater_dashboard.yaml
hacs.json
README.md
```

## Development notes

- The config flow follows current Home Assistant custom integration patterns with `manifest.json`, `config_flow.py`, and `translations/en.json`
- The integration uses coordinated polling rather than per-entity API calls
- The client implementation matches the current [openHop Repeater](https://github.com/openhop-dev/openhop_repeater) auth flow:
  - `POST /auth/login`
  - `POST /api/auth/tokens`
  - ongoing reads with `X-API-Key`

## Releases

- The integration version is defined in `custom_components/pymc_repeater/manifest.json`
- GitHub Actions validate HACS compatibility, Hassfest, and a Python smoke test on every push and pull request
- Dependabot monitors the workflow dependencies automatically
- For the first stable release, create a Git tag and GitHub release for `v1.0.0`
