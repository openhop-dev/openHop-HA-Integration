# Repository Guide for Coding Agents

## Scope and purpose

This repository is a HACS-compatible Home Assistant custom integration for monitoring and controlling an [openHop Repeater](https://github.com/openhop-dev/openhop_repeater) through its local HTTP API.

Important compatibility names:

- User-facing name: **openHop Repeater**.
- Home Assistant domain and component directory: **`pymc_repeater`**.
- Do not rename the domain, `custom_components/pymc_repeater`, existing config-entry keys, service domain, or established entity unique-ID suffixes without an explicit migration. The retained pyMC identifiers preserve existing installations.

## Repository map

- `custom_components/pymc_repeater/`: installable integration.
  - `manifest.json`: Home Assistant/HACS metadata and release version.
  - `config_flow.py`: initial setup, token bootstrap, reauthentication, and options flow.
  - `api.py`: asynchronous Repeater HTTP client and endpoint normalization.
  - `coordinator.py`: integration-wide polling and the GPS SSE listener.
  - `__init__.py`: config-entry lifecycle, platform forwarding, and advanced Home Assistant action registration.
  - `sensor.py`, `binary_sensor.py`, `button.py`, `select.py`, `switch.py`, `number.py`: entity platforms.
  - `services.yaml`: user-visible action descriptions and selectors.
  - `translations/en.json`: config/options strings and translated entity names.
  - `diagnostics.py`: downloadable diagnostics and redaction.
  - `brand/`: checked-in 1x/2x PNG icons.
- `tests/test_dev_api_alignment.py`: source/AST contract tests that run without installing Home Assistant.
- `dashboards/openhop_repeater_dashboard.yaml`: anonymized Lovelace view template; users replace `REPEATER_SLUG`.
- `.github/workflows/`: HACS, Hassfest, and Python smoke checks.
- `hacs.json`: HACS display name, README rendering, and minimum Home Assistant version.
- `CHANGELOG.md`: release history; keep the current release section complete.
- `RELEASING.md`: stable release checklist.
- `.github/release.yml`: GitHub-generated release-note categories.

There is no standalone Python/JavaScript package manifest, requirements file, Makefile, Dockerfile, deployment definition, formatter configuration, linter configuration, type-checker configuration, or pytest configuration in this repository.

## Runtime and dependencies

- Language: Python plus JSON, YAML, Markdown, and PNG assets.
- Runtime target verified from CI: **Python 3.12**.
- Minimum Home Assistant version: **2024.1.0**, from `hacs.json`.
- Integration model: Home Assistant config-entry integration with `iot_class: local_polling` and six forwarded platforms: sensor, binary sensor, button, select, switch, and number.
- `manifest.json` declares no third-party requirements. Home Assistant supplies its own APIs and the imported runtime libraries (`aiohttp`, `yarl`, and `voluptuous`).
- No repository-supported standalone virtual-environment or dependency-install command exists. The source-only contract suite uses the Python standard library.

Do not invent a pip/npm setup step. For live runtime testing, install the component in a compatible Home Assistant development or test instance; this repository does not provide that harness.

## Verified commands

Run commands from the repository root.

Full source-contract suite:

```bash
python3 -m unittest discover -s tests -v
```

Focused contract test:

```bash
python3 -m unittest tests.test_dev_api_alignment.DevApiAlignmentTests.test_integration_polling_is_configurable_and_defaults_to_15_seconds -v
```

Replace the final method name with another method from `DevApiAlignmentTests` when focusing on a different contract.

Compile all integration modules:

```bash
python3 -m compileall -q custom_components/pymc_repeater
```

Validate checked-in JSON:

```bash
python3 -m json.tool custom_components/pymc_repeater/manifest.json >/dev/null
python3 -m json.tool custom_components/pymc_repeater/translations/en.json >/dev/null
python3 -m json.tool hacs.json >/dev/null
```

Check patch whitespace:

```bash
git diff --check
```

Optional YAML parse check, only when PyYAML is already available (PyYAML is not declared by this repository):

```bash
python3 - <<'PY'
import yaml

for path in (
    "custom_components/pymc_repeater/services.yaml",
    "dashboards/openhop_repeater_dashboard.yaml",
    ".github/workflows/python-smoke.yaml",
    ".github/workflows/hacs.yaml",
    ".github/workflows/hassfest.yaml",
):
    with open(path, encoding="utf-8") as stream:
        assert yaml.safe_load(stream) is not None, path
PY
```

No local build, formatter, lint, or type-check command is defined. Do not claim Ruff, Black, mypy, pytest, or a packaging build passed unless the repository later adds and configures it.

## Architecture and control flow

1. `config_flow.py` normalizes the host field, combines it with the separately entered port for the unique ID, logs in once with the admin password, creates a dedicated API token, and stores the token metadata—not the admin password—in the config entry.
2. `async_setup_entry` in `__init__.py` creates one `PyMCRepeaterApiClient` using Home Assistant's shared aiohttp session, creates the coordinator, performs the first refresh, starts runtime tasks, then forwards all entity platforms.
3. `PyMCRepeaterDataUpdateCoordinator` runs one configurable full-API refresh. The default is 15 seconds and the enforced range is 5–300 seconds.
4. `api.async_fetch_all()` starts the normal endpoint requests concurrently. Authentication and connection failures fail the coordinator refresh; other endpoint failures are retained as `{ "error": ... }` for that payload key so unrelated telemetry can remain available.
5. GPS uses `/api/gps_stream` as a separate SSE task. Partial GPS snapshots update listeners with `async_update_listeners()` and must not call `async_set_updated_data()`, because that would postpone the next scheduled full refresh.
6. Static entities are built from description tuples. Dynamic entities use API-provided MQTT brokers, rooms, companions, database tables, temperatures, and external sensor readings. External sensor entities may be added later through coordinator listeners.
7. Config/control entities call the API and normally request a coordinator refresh afterward. Restart/install operations intentionally skip immediate refresh where the remote service may be unavailable.
8. Advanced actions are registered once for the `pymc_repeater` domain in `__init__.py`. When multiple entries exist, callers must supply `config_entry_id`. Response-returning actions use Home Assistant's `SupportsResponse` behavior.

Keep large or filtered payloads such as neighbor-link history on demand through actions instead of adding them to every coordinator update or entity state.

## Coding conventions

Follow patterns already present in the component:

- Start Python modules with a short module docstring and `from __future__ import annotations`.
- Use async Home Assistant APIs; reuse `async_get_clientsession(hass)` rather than creating sessions.
- Add type hints to public helpers, methods, and payload shapes. Existing description records use frozen, keyword-only dataclasses; `BootstrapResult` uses `slots=True`.
- Use `_LOGGER = logging.getLogger(__name__)`; never use `print` in integration code.
- Entity names are sentence case. Entities set `_attr_has_entity_name = True` and attach to the shared Repeater `DeviceInfo`.
- Stable unique IDs use `entry.unique_id or entry.entry_id` plus a durable key. Dynamic names are normalized with Home Assistant's `slugify`.
- Prefer description tables (`SENSORS`, `BINARY_SENSORS`, `BUTTONS`, `SWITCHES`, `NUMBERS`) over repetitive entity classes when behavior is uniform.
- Read nested coordinator fields defensively with `_nested(...)`, tolerate absent optional API data, and expose configuration/diagnostic categories consistently.
- Preserve API payload field names exactly when they are part of the Repeater contract.

No formatter is configured. Preserve the surrounding style and make `compileall`, tests, and `git diff --check` pass.

## Change rules

### API or telemetry additions

- Add or update the async wrapper in `api.py`.
- Add steady, lightweight telemetry to `async_fetch_all()` only when it belongs in every poll. Keep histories and large query results action-only.
- Map coordinator keys to entities in the appropriate platform file.
- Preserve partial-endpoint failure behavior and the special authentication/connection handling.
- Add source-contract coverage in `tests/test_dev_api_alignment.py`; tests must remain importable without Home Assistant unless a real Home Assistant test harness is intentionally introduced.

### Entities and controls

- Do not change an existing description key or unique-ID format casually; that can create replacement entities in Home Assistant.
- Add user-facing translated names to `translations/en.json` when using `translation_key`.
- For write entities, update the Repeater through `api.py` and request a coordinator refresh unless the operation disrupts connectivity.
- For dynamic entities, deduplicate by stable unique ID and mark entities unavailable when their source object disappears.

### Actions

Keep these three surfaces synchronized:

1. API client method in `api.py`.
2. Registration, Voluptuous schema, refresh behavior, and response support in `__init__.py`.
3. Name, description, required fields, bounds, and selectors in `services.yaml`.

Add or update contract tests whenever endpoint paths, fields, limits, or response behavior changes.

### Options, authentication, and diagnostics

- Option changes reload the config entry. Keep defaults and bounds synchronized among `const.py`, `config_flow.py`, `coordinator.py`, translations, tests, and README.
- Never store or log the admin password. Treat API tokens, JWTs, Home Assistant tokens, room/message data, identities, GPS data, and client addresses as sensitive.
- `diagnostics.py` currently redacts `api_token` from config-entry data but returns coordinator data as-is. If a new coordinator payload can contain credentials or other secrets, expand diagnostics redaction before exposing it.
- The API base URL is plain HTTP. Do not claim transport security; documentation requires a trusted local network, VPN, or equivalent boundary.

### Documentation and dashboard

- Keep `README.md`, `CHANGELOG.md`, action documentation, and the dashboard aligned with user-visible additions.
- Keep the dashboard anonymized. Do not commit real node names, broker names, companion names, locations, entity prefixes, or coordinates. Preserve `REPEATER_SLUG` and its setup comments.
- Update dashboard contract assertions if the template path or required v1.1.6 entities change.

## CI and release expectations

GitHub Actions provides:

- `Python Smoke`: Python 3.12 JSON validation, `compileall`, and unittest discovery.
- `HACS`: `hacs/action@main` for integration validation.
- `Hassfest`: `home-assistant/actions/hassfest@master`.

Workflow path filters mean README-, changelog-, or dashboard-only edits may not trigger every workflow. Run applicable local checks even when GitHub does not schedule them. HACS and Hassfest are not reproduced by a checked-in local command; verify their GitHub runs for integration metadata/platform changes.

Observed branch/release convention:

- Development changes accumulate on `dev`.
- Stable work is merged into `main`; release tags are on the stable line.
- Before release, ensure `main` CI is green, set the intended version in `custom_components/pymc_repeater/manifest.json`, update `CHANGELOG.md`, create a matching `vX.Y.Z` tag, and create a GitHub release from that tag.
- `.github/release.yml` groups PRs by labels; `skip-changelog` excludes a PR from generated notes.
- Dependabot only updates GitHub Actions, weekly on Monday.

There is no generated-code or vendored-code directory identified. Do not commit ignored `__pycache__/`, `*.pyc`, `.pytest_cache/`, or `.ruff_cache/` files. Treat `brand/*.png` as intentional binary assets and update both resolutions when changing branding.

## Repository-specific pitfalls

- The public name is openHop, but compatibility identifiers still say pyMC. A broad rename is a breaking migration, not cleanup.
- The contract tests inspect source and AST; they verify important wiring but do not prove Home Assistant runtime behavior or compatibility with a live Repeater.
- Keep one integration-wide polling schedule plus GPS SSE. The tests intentionally reject a separate external-sensor polling loop.
- Do not let GPS stream updates reset the coordinator's next full refresh.
- `async_fetch_all()` intentionally tolerates optional endpoint failures but not authentication or connection failure; preserve that distinction.
- Repeater API changes should be checked against the corresponding Repeater runtime/OpenAPI contract rather than inferred from UI behavior.
- Multiple configured Repeaters make an omitted action `config_entry_id` ambiguous.
- The Repeater's persistent token database is outside this repository. Documentation for the Home Assistant add-on uses `/var/lib/openhop_repeater`; do not reintroduce the old unmapped `/var/lib/pymc_repeater` path.

## Completion checklist

- [ ] Scope is narrow and compatibility identifiers/unique IDs are preserved.
- [ ] API, coordinator, entities, actions, services YAML, translations, and docs are synchronized where applicable.
- [ ] New behavior has a focused contract test; bug fixes include a regression assertion.
- [ ] `python3 -m unittest discover -s tests -v` passes.
- [ ] `python3 -m compileall -q custom_components/pymc_repeater` passes.
- [ ] Manifest, translations, and `hacs.json` parse as JSON.
- [ ] Changed YAML parses when a YAML parser is available.
- [ ] `git diff --check` passes and no cache/generated artifacts are staged.
- [ ] No credentials, private node data, GPS coordinates, or identifying dashboard values are present.
- [ ] `manifest.json` and `CHANGELOG.md` agree for release work.
- [ ] Relevant GitHub HACS, Hassfest, and Python Smoke checks are green before declaring release-ready.
