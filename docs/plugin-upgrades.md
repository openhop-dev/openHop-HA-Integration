# Plugin upgrade actions (1.3.0)

These are explicit actions, not a plugin management API or a new background
scheduler. No automation is created or enabled by installing/updating the integration.
They use the configured API token over the existing trusted-local-network HTTP
connection. They do not install missing plugins, upload wheels, change settings,
or expose runtime documents, repository URLs, release notes, paths, or raw logs.

| HA action (`pymc_repeater.` prefix) | Fields besides `config_entry_id` | Behavior |
| --- | --- | --- |
| `check_plugin_updates` | optional `plugin_id`, `force_refresh` (default false) | Check one or all installed eligible plugins without writing |
| `update_plugin` | required `plugin_id`, optional `version`, `force_refresh` | Upgrade one installed catalogue plugin; omitted version uses checked latest |
| `update_all_plugins` | `force_refresh` | Check then upgrade each eligible installed plugin sequentially |

All three are response-only actions: include `response_variable` as a **sibling
of `data`**, not inside it, in a script/automation. Specify `config_entry_id` when
multiple Repeaters are loaded. Results are a dictionary with `results`, `counts`
(`success`, `skipped`, `failure`, `unknown`) and `stopped`. Rows contain bounded
identity/version tokens, outcomes, optional update availability/updated flags and
fixed reason codes, never backend exception text. Check `success` means the check
completed, not that an upgrade happened. Update `success` means the returned plugin
identity and installed target version were confirmed; it does not prove plugin
runtime health. A backend `updated: false` is skipped, not upgraded.

Eligibility requires an installed inventory row with `source: catalogue` and
repository metadata. Local wheels (even if an ID matches a catalogue entry),
missing repositories, absent plugins and no newer versions are skipped. Missing
catalogue entries/release lookup errors are per-plugin failures. Inventory is
validated before any writes and bounded to 100 unique plugins. Plugin IDs and
optional versions are exact 1–128-character ASCII tokens starting alphanumeric,
then letters/digits/`.`/`_`/`+`/`-`; no whitespace trimming or type coercion.
The backend remains the authority for catalogue approval/version selection:
schema 2 only accepts the approved version; legacy schema 1 resolves releases.
Explicit versions follow backend semantics and are not a general downgrade guarantee.

Each request has a finite **930-second** HTTP/aiohttp session budget, covering
the plugin IPC's 900-second completion budget plus a margin. A whole batch may
therefore run much longer; no progress stream or installation-log polling is used.
Ordinary reported plugin failures do not prevent subsequent upgrades. Lost
connections, timeouts, malformed/unconfirmed completion, backend HTTP 409 conflict,
502 or 504, or explicit unknown outcomes stop the batch; remaining rows are
`skipped` with `batch_stopped`. **No write is automatically retried.**

Single/bulk upgrades share a fail-fast per-client/entry admission guard, rather
than queueing. `finally` releases active admission, and cancellation propagates.
An unknown outcome (or cancellation while an operation could be submitted)
quarantines further upgrades on that client. Read-only checks still work.
First inspect/reconcile the installed version and active operation on the Repeater;
only after confirming completion should an operator reload this integration entry
(to clear the client guard) and decide whether to retry. Reloading alone is not
proof the remote operation stopped. The guard cannot arbitrate other HA instances
or external UI/API callers; backend serialization still applies.

## Optional daily 03:00 automation

[Complete anonymized YAML](../examples/daily-plugin-upgrades.yaml) can be copied
into `automations.yaml` and explicitly enabled after replacing the entry placeholder.
It uses HA's local timezone and `mode: single`, captures the response correctly,
and notifies on failures/unknowns. It makes fresh metadata checks by explicitly
setting `force_refresh: true` (catalogue/GitHub network access may occur). Scheduling
is owned by that automation, not the Repeater or this integration. It is separate
from existing Repeater firmware update checks. No daily plugin schedule is enabled
by default. A failed admission/preflight action raises an HA error and stops the
script; inspect its trace. Per-plugin failures are instead in the response.

## Backend trace and verification boundary

Authority for this addition is the local `openhop_repeater/repeater/web/plugin_endpoints.py`
and `repeater/plugins/{ipc,manager,runtime,catalogue}.py` checkout, not the old
`updates` endpoint comment alone:

- `GET /api/plugins/` returns top-level `plugins`, with runtime status/provenance
- `GET /api/plugins/updates?id=...&refresh=true|false` returns `id`,
  `installedVersion`, `latestVersion`, `updateAvailable`; manager schema-2
  catalogue checks use approved metadata, not arbitrary latest GitHub releases
- `POST /api/plugins/update` takes `id`, optional `version`, `force_refresh`;
  successful envelopes contain `plugin`. Enabled updates return `enable()` status
  without an `updated` flag; disabled updates include `updated: true`; no-op updates
  include `updated: false`
- IPC timeout is 900 seconds and is not cancellation of remote work. The endpoint
  reports IPC unknown as HTTP 504 with `outcome: unknown`; manager overlap is 409
- Nested plugins inherit `/api` authentication in `http_server.py`; the auth tool
  accepts the existing `X-API-Key` token. No new credentials/scope are invented

Tests execute extracted actual client/transport/service/schema bodies using fake
HTTP/HA boundaries. Compilation and JSON/YAML validation supplement them. These
are not live HA schema/registration, authenticated HTTP, catalogue network,
installation/runtime-health, clock/DST or HACS/Hassfest tests. No live plugin writes,
deployment, commit or release are part of this implementation.
