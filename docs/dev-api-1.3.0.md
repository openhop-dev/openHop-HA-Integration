# Repeater dev compatibility for 1.3.0

## Source authority

This release was compared against freshly fetched Repeater `origin/dev` at
`9c958e3111604aca5ab664c9feead8c8bc5e4240`, using an isolated source archive.
The implementation and storage helpers, not endpoint names alone, determine the
response contracts. This replaces neither the historical
[installed-source audit](installed-api-alignment.md) nor verification of a
particular appliance's installed version.

The review inventoried 154 documented paths and 169 method entries in that
snapshot's bundled OpenAPI, including duplicated authentication aliases. This is
scope triage, not a claim of exhaustive runtime testing or complete HA API parity.

The management expansion additionally traced selected endpoint, IPC, manager,
storage, runtime and ACL helper files at immutable Repeater `origin/dev`
`3c4bf3a9586d1e0b3871091649bc3fd09da3b662` via `git show`. The checkout's older
`feat/sensor-manager` working files were not authority. The earlier OpenAPI counts
above remain the original snapshot inventory, not a new whole-tree audit.

## Monitoring contract

- `stats.radios` and `radio_profiles` describe configuration; they do not prove
  applied RF settings, modem connectivity, or successful transmission
- `stats.airtime_radios` contains named channel budgets. Radios sharing a channel
  report the same ledger; do not sum child budgets to obtain node totals. The
  existing parent utilization is the maximum channel utilization on newer builds
- `stats.noise_floor_radios` supplies cached, explicitly attributed noise readings
- `packet_stats.radios` supplies per-radio window counts and RSSI/SNR averages;
  the existing one-hour and 24-hour polls already retrieve these summaries
- Physical `transmissions` count successful fan-out egress operations, unlike
  legacy parent packet-row totals. Sliding-window values are not lifetime counters
- `lbt_diagnostics.radios` supplies explicitly attributed summary statistics;
  timelines and raw buckets do not become entity attributes
- Missing newer fields on older builds remain unavailable. Missing or malformed
  inventory, duplicate IDs, alias collisions, null averages and nonfinite values
  must not become healthy zeroes or copied parent metrics
- Neighbor history supports optional `radio_id` and bucket grouping `by_radio`.
  Raw rows remain the default; historical IDs in returned actions stay backend IDs,
  not Home Assistant aliases

## Existing capabilities retained

The integration already supports aggregate radio status/problems, RRD fallback,
MQTT neighbor-publication phase and broker reconnecting attributes, direct advert
schedules, targeted raw radio configuration, companion reply budgets and optional
status/telemetry responses. These are not new 1.3.0 capabilities.

The duty-cycle switch already uses the persistent `update_duty_cycle_config`
endpoint. The separate client wrapper for `set_duty_cycle` is live-only; it is not
used by that switch. Raw configuration results may require a Repeater restart;
the integration does not silently restart it or promise atomic backend validation.

## Sensor cadence limitation

The inspected upstream sensor manager schedules individual plugin intervals but
does not attach its resolved interval to each reading envelope. The integration
prefers `poll_interval_seconds` when supplied and retains a legacy global-summary
fallback only when it is absent. That fallback cannot prove a plugin's effective
cadence: for example, a modem plugin can sample less frequently than the global
manager interval. Updating HA alone cannot fix this backend metadata limitation.
No interval is guessed from sensor type, and no backend changes were made here.

## Explicit plugin upgrade actions

[Plugin upgrades](plugin-upgrades.md) add check, single optional-version upgrade,
and sequential update-all actions using the local backend plugin endpoint/IPC/
manager/runtime/catalogue source authority. They return minimized structured
outcomes, guard overlapping writes, stop on uncertain outcomes without retries,
and leave daily scheduling to an optional operator-owned 03:00 automation.
Plugin inventory/check/install results are not added to coordinator polling;
existing aggregate plugin health polling is unchanged.

## Deliberately excluded

[Explicit management actions](management-actions.md) add plugin catalogue installation,
lifecycle and settings, complete sensor configuration replacement, and ACL role
assignment/named removal. These remain explicit and bounded, not automatic polls.

No blanket generated API or new automatic history polling is added. Authentication
and token administration, first-run setup, forced sensor hardware reads,
policy/group editing, identity/key exports and mutations, arbitrary-path wheel
installation, plugin logs/progress/runtime documents, bulk packet and graph datasets,
and additional continuous streams remain outside this release. Existing explicit
destructive actions are retained, not exercised for testing.

## Dependency ownership

The manifest deliberately has no third-party requirements. Home Assistant owns
`aiohttp`, `yarl`, schema validation and its own APIs. At audit time, stable HA
2026.9.4 requires Python >=3.14.2 and pins aiohttp 3.14.3 and yarl 1.24.5; PyPI's
newer yarl is not a reason to override that pin. Current HA supplies the
`voluptuous` import through its `probatio` compatibility alias. HA 2024.1 supplies
the original library and remains the integration's advertised minimum; the
Sections dashboard requires a newer frontend.

CI source checks cover Python 3.11–3.14; this is not testing four HA installations.
Checkout/setup-python v7 are already current. HACS/Hassfest retain upstream moving
refs. Dependabot version updates target dev once that configuration reaches the
default branch; default-branch security update policy is separate.

First-party references:

- [HA stable dependencies](https://github.com/home-assistant/core/blob/2026.9.4/pyproject.toml)
- [HA schema compatibility setup](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/__init__.py)
- [HA minimum release dependencies](https://github.com/home-assistant/core/blob/2024.1.0/pyproject.toml)
- [Checkout releases](https://github.com/actions/checkout/releases)
- [Setup Python releases](https://github.com/actions/setup-python/releases)

## Verification boundary

Tests execute actual checked-in client, schema/registration and entity logic with
fake HTTP/HA boundaries, supplemented by source-contract assertions, compilation,
JSON/YAML checks and workflow linting. Sanitized synthetic fixtures follow the
inspected backend response structure. They do not prove live HA registration,
probatio compatibility, authenticated Repeater HTTP, RF delivery, dashboard
rendering or hosted HACS/Hassfest checks. No deployment or release was performed.
