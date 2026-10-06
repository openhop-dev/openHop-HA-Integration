# Explicit management actions (1.3.0)

These actions were traced through Repeater endpoints, IPC, manager, storage and
runtime helpers at immutable `origin/dev`
`3c4bf3a9586d1e0b3871091649bc3fd09da3b662`. Older installations may not implement
these contracts. Unsupported endpoints produce errors, not invented support.
The backend checkout's older working branch was not used as authority.

All actions use the existing `pymc_repeater` domain and accept `config_entry_id`.
Select it when more than one Repeater is configured. Nothing here adds polling,
background progress listeners, schedules, forced hardware reads or automatic
Repeater restarts. Calls execute only when requested. Use a trusted LAN/VPN:
the integration's HTTP connection is not encrypted.

## Plugin lifecycle

| Action | Fields besides `config_entry_id` | Behavior |
| --- | --- | --- |
| `get_plugin_catalogue` | `force_refresh: false` | Public catalogue metadata, at most 100 entries; can initiate external catalogue/release network requests |
| `install_catalogue_plugin` | required `plugin_id`; optional `version`; `force_refresh: false` | Downloads and installs a backend-approved wheel; can replace existing plugin code |
| `enable_plugin` | required `plugin_id` | Persists enabled state and starts a service plugin |
| `disable_plugin` | required `plugin_id` | Stops and persists disabled state |
| `start_plugin` | required `plugin_id` | Starts an enabled plugin; does not enable a disabled plugin |
| `stop_plugin` | required `plugin_id` | Stops without disabling; enabled plugins may start after a manager restart |
| `restart_plugin` | required `plugin_id` | Restarts an enabled service plugin |
| `uninstall_plugin` | required `plugin_id`; `delete_data: false` | Removes release code, preserving plugin data by default; explicit true permanently deletes data |
| `get_plugin_settings` | required `plugin_id`; `include_sensitive: false` | Reads effective saved/default configuration on demand, without filesystem paths |
| `update_plugin_settings` | required `plugin_id`, complete `config` object; `restart: false` | Replaces the entire configuration, optionally restarting an enabled service plugin |

All plugin actions require a response (`response_variable` in automations).
Writes return bounded identity/version/state/boolean metadata and fixed
`outcome`/`reason` codes, never settings, filesystem paths or backend logs.
UI-only plugins need not have a running process. A reported backend failure may
still have side effects: for example, enable can persist before start fails,
and settings can save before restart fails. Inspect the Repeater before retrying.

Lifecycle, catalogue install, settings writes and the existing single/bulk upgrades
share one **per-client fail-fast write admission**. They do not queue. Unknown
completion, conflict (HTTP 409), HTTP 502/504, lost responses or cancellation during
a write quarantine further plugin writes. Requests are never automatically retried.
Inspect/reconcile actual Repeater state, then reload the HA entry to clear this
local quarantine; reloading alone does not reconcile or stop the remote operation.
Other clients can still change the Repeater; this is not a global transaction lock.

Plugin requests allow a finite 930-second HTTP budget (900-second IPC completion
plus margin), overriding both the outer asyncio deadline and aiohttp session
budget. Cancellation/timeout does not cancel an accepted remote IPC operation.
New management responses are capped at 1 MiB decoded HTTP bytes before JSON
parsing. Catalogue descriptions are limited to 1024 characters. Writes and explicit
settings/config documents accept finite JSON objects up to 256 KiB, 32 nested
levels and 10,000 visited values. Plugin ID/version tokens are exact ASCII tokens
of 1–128 characters, start alphanumeric, and otherwise allow letters/digits,
`.`, `_`, `+` and `-`; they are never trimmed or repaired.

No immediate coordinator refresh is triggered by plugin writes. Existing plugin
health polling eventually reflects the manager's reported state, without retaining
these action results in coordinator data or normal entity attributes.

### Settings safety

`config` is a mapping, not a JSON-encoded string. It replaces the complete saved
plugin configuration, not a patch. Preserve unrelated fields. By default reads
replace common credential-key values with `[REDACTED]` (case-insensitive key
matching for password, secret, token, private/API/transport keys). This is a
heuristic, not a guarantee for arbitrary plugin-defined credentials or secret
values under innocent field names. Treat all explicit configuration responses as
potentially sensitive. The updater rejects `[REDACTED]` anywhere rather than
silently replacing a real credential with a placeholder.

For a necessary full edit, explicitly use `include_sensitive: true` or supply the
real credential fields yourself. Plugin settings have **no backend mask-preservation
protocol**; do not submit sensor `*****` masks to a plugin. Only effective `config`
is returned, not duplicate `saved`/`defaults` copies. Write responses never echo
settings. HA action/automation traces can retain both inputs and response variables;
limit access and do not copy sensitive responses into notifications or logs.

```yaml
service: pymc_repeater.get_plugin_catalogue
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
response_variable: catalogue
```

```yaml
service: pymc_repeater.install_catalogue_plugin
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  plugin_id: openhop.example  # replace with a real catalogue ID
response_variable: installation
```

```yaml
service: pymc_repeater.uninstall_plugin
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  plugin_id: openhop.example
  delete_data: false  # preserve plugin-owned data
response_variable: removal
```

### Wheel upload and diagnostics limits

The audited backend accepts **multipart field `wheel`** at
`POST /api/plugins/install`, or a JSON `wheel_path` on the **Repeater's filesystem**.
A HA `/config/...` path is not a Repeater path. No arbitrary-path wheel action is
exposed here: the integration has no confined upload-directory/attachment contract
or bounded, symlink-safe HA file reader. Use the Repeater UI for manual wheel upload
and the catalogue action for HA installation. Multipart staging cleanup is backend
owned; unacknowledged uploads may intentionally be retained after uncertain IPC.

Plugin logs, progress SSE and runtime JSON are not exposed by these actions.
The backend can return arbitrary plugin-written secrets and raw installation logs;
there is no universal safe schema for those documents. This omission does not
remove existing Repeater log actions or plugin health monitoring. Use the Repeater
UI for detailed diagnosis. No logs/runtime/settings are added to normal outcomes.

## Sensor configuration

| Action | Fields | Behavior |
| --- | --- | --- |
| `get_sensor_types` | `config_entry_id` | Available types and settings schemas; no read of hardware |
| `get_sensor_configuration` | `config_entry_id`; `include_sensitive: false` | Reads current configuration, preserving backend password masks and rename origins |
| `update_sensor_configuration` | `config_entry_id`; required complete `config` object | Persists the entire sensor section; returns `saved` and `restart_required` |

These actions require response variables and never trigger a refresh. Actual API
routes are `/api/sensors_types`, `/api/sensors_config`, and
`/api/sensors_config_update`; nested `/api/sensors/config` comments in the backend
are not the dispatcher contract. Non-plugin management calls have a finite
30-second outer/aiohttp request budget and the same response cap. A timeout does
not prove that persistence failed; inspect before retrying.

**Full replacement:** include `enabled`, finite positive `poll_interval_seconds`,
`auto_install_packages`, and **all** `definitions` (including unchanged definitions,
maximum 100). Omitted definitions are removed; an empty list intentionally clears
them. Partial top-level patches are rejected rather than resetting omitted values
to backend defaults. Sensor names must be unique. `settings` must be a JSON object.
Names/origin/type strings are bounded to 256 characters without control characters;
boolean flags must be actual booleans. Package-install choices and hardware settings
remain usable; review their effects before applying/restarting.

Preserve lowercase `settings.password: "*****"` and `_original_name` from the
backend read when renaming a sensor. The backend resolves masks by name/type and
origin, **not list position**, and rejects ambiguous matches. Never substitute
`[REDACTED]` for a sensor password: that placeholder has no backend preservation
meaning. Common other credentials are redacted by default; request sensitive data
explicitly only when needed for an edit. `include_sensitive: true` cannot recover
passwords already masked by the backend. Responses and write inputs may enter HA
traces, so keep them private.

```yaml
service: pymc_repeater.get_sensor_configuration
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
response_variable: sensors
```

Example complete replacement (adapt the entire section to your installation):

```yaml
service: pymc_repeater.update_sensor_configuration
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  config:
    enabled: true
    poll_interval_seconds: 30
    auto_install_packages: false
    definitions:
      - name: Example temperature
        type: bme280
        enabled: true
        auto_install_packages: false
        settings:
          i2c_address: "0x76"
          bus_number: 1
response_variable: sensor_save
```

Saving does not apply a new live sensor manager: the audited backend returns
`restart_required: true`. Restart the Repeater separately when ready. Sensor
configuration writes are not changes to HA's integration-wide polling interval.
There is no forced-read action: the backend creates a new manager and calls all
configured hardware plugins synchronously, with potentially package/network/hardware
side effects and no universal completion bound. Existing cached readings remain
available through normal monitoring.

## ACL permissions

`set_acl_permissions` accepts required `identity_name`, `client_pubkey` (exact full
64-character hexadecimal public key), and integer `permissions` in 1–255. Role is
`permissions & 3`: **1 read-only, 2 read-write, 3 admin**. Higher bits are retained;
2 is not admin. Multiples of four/guest role 0 are rejected; use removal instead.
The backend validates the public key and ACL capacity, and determines persistence.
A Repeater's non-guest grants are stored for passwordless future login. Room servers
persist **only admins**; other roles can be accepted until restart. Request and
inspect `persisted`, not just HTTP success. Permissions do not administer identity
private keys, policy groups or token ownership.

```yaml
service: pymc_repeater.set_acl_permissions
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  identity_name: repeater
  client_pubkey: "REPLACE_WITH_EXACT_64_HEX_PUBLIC_KEY"
  permissions: 1
response_variable: permission_result
```

`set_acl_permissions` supports optional responses and refreshes cached telemetry
once after success. Existing `remove_acl_client` retains its legacy `public_key`
field and optional `identity_hash`, adding optional exact `identity_name`. Name
wins over hash; omission of both retains the legacy **every ACL** removal scope.
Removal also supports optional responses and one refresh. Both actions change
real access permissions; fake tests below did not exercise live writes.

## Verification boundary

Stdlib tests execute the actual checked-in API/client transport and HA registration
bodies with fake HTTP/HA/schema boundaries: paths, JSON objects, mask preservation,
validation, shared guards, cancellation, byte/request budgets, response behavior and
refresh policy. These are not live Home Assistant/Voluptuous tests, authenticated
Repeater API tests, installer tests, hardware reads, or proof of RF/access outcomes.
No commit, push, release, deployment or live management write was performed.
