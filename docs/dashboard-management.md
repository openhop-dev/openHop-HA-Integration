# Dashboard management workflows (1.3.0)

The [single-view dashboard](../dashboards/openhop_repeater_dashboard.yaml) uses
built-in cards and [companion scripts](../examples/openhop_dashboard_scripts.yaml).
It does not create fictional control entities. The compact view adds only a
read-only update check and this guide. No schedule is enabled.

## Install and select the target

1. Merge the example's **top-level script mappings** into your existing
   `scripts.yaml`, normally loaded by `script: !include scripts.yaml`. Do not
   overwrite existing scripts or add another `script:` wrapper inside that file.
   With packages or split includes, adapt the surrounding include structure.
2. Replace **every `EXAMPLE_CONFIG_ENTRY_ID`** with the actual openHop integration
   entry ID. Find it in the integration's entry page URL (`config_entry=...`), or
   select the intended entry in Developer tools → Actions and inspect its YAML
   `config_entry_id`. `REPEATER_SLUG` is an **entity prefix, not the entry ID**.
3. For multiple Repeaters, duplicate scripts with distinct `openhop_example_...`
   IDs, entry IDs and aliases; rename **all matching dashboard script targets**.
   Keep radio-child and dynamic entity replacement separate from this mapping.
4. Check YAML configuration, reload scripts using Home Assistant's supported
   script reload, and confirm the expected `script.*` entities exist. Install the
   view through the view YAML editor, not as a `views:` dashboard. If you do not
   install scripts, remove the script buttons; monitoring remains usable.
5. Read-only buttons never change plugin code, but catalogue/update checks can
   contact external servers. The separately labeled bulk upgrade requires a
   Lovelace confirmation and passes `confirmed: true` to the wrapper.

Every integration call in these scripts captures a sibling `response_variable`.
Lovelace cannot directly consume response-only actions. Notifications deliberately
show only bounded public counts, fixed outcome codes, save/restart flags, or a
completion notice. Detailed responses are available in private script traces,
not sensor attributes. Action failures stop the script before its notification;
a completion notice is not proof of RF delivery or a persisted ACL grant.

## Plugins

Use **Developer tools → Actions** to select the installed wrapper by full script
ID. Supply fields there; ordinary Run buttons do not prompt for required fields.
All write wrappers require an explicit `confirmed: true` after reviewing the
actual target and consequences. This is an operator review gate, not security
access control. Use the real plugin ID from the catalogue or installed inventory.

| Wrapper suffix (`script.openhop_example_…`) | Review |
| --- | --- |
| `get_plugin_catalogue` | Public catalogue count; inspect response for approved IDs |
| `check_plugin_updates` | Counts and update-available total; failures/unknown are not up to date |
| `install_catalogue_plugin` | `plugin_id`; can replace installed code |
| `update_plugin` | `plugin_id`; upgrades only eligible installed catalogue plugins |
| `update_all_plugins` | Sequential eligible upgrades, can restart plugins; no schedule |
| `enable_plugin` / `disable_plugin` | `plugin_id`; persist enabled/disabled state |
| `start_plugin` / `stop_plugin` | `plugin_id`; start requires enabled; stop does not disable |
| `restart_plugin` | `plugin_id`; enabled service plugins only |
| `uninstall_plugin` | `plugin_id`; explicitly sends **`delete_data: false`** |
| `update_plugin_settings` | `plugin_id`, complete `config` object, `restart` (false by default) |

Version-pinned install/upgrade, individual update checks and force-refresh options
remain available through the native action editor. Omit `version` for backend
selection rather than supplying an empty token. The wrappers use cached metadata
(`force_refresh: false`). UI-only plugins need not run a process.

**Settings read stays editor-only:** call `pymc_repeater.get_plugin_settings` with
your `config_entry_id`, `plugin_id`, `include_sensitive: false`, and sibling
`response_variable: settings`. Inspect privately; credential redaction is a
heuristic. Request `include_sensitive: true` only for a necessary complete edit.
Pass the actual entire `settings.config` mapping (not the response envelope or a
JSON string) into the write wrapper. Preserve unrelated fields; `[REDACTED]`
placeholders are rejected. Plugin settings have no `*****` mask-preservation
protocol. No dashboard button reads or replaces settings.

Plugin writes share fail-fast admission across lifecycle/settings/upgrades.
Allow up to 930 seconds per request; a bulk operation can take much longer.
Timeout/cancellation does not cancel remote work. Inspect/reconcile actual Repeater
state after unknown completion or partial failure, then reload the integration
entry to clear quarantine. Do not blindly retry; reload alone is not reconciliation.
Manual wheel upload remains in the Repeater UI, not a HA filesystem action.

## Sensors

The `get_sensor_types` wrapper reads supported types/schema without forced hardware
reads. For configuration, call **`pymc_repeater.get_sensor_configuration` in the
native action editor**, supplying the actual entry ID, `include_sensitive: false`
and sibling `response_variable: sensors`. Keep responses private. Read with
sensitive opt-in only if required for an edit; backend password masks stay masked.

Use `script.openhop_example_update_sensor_configuration` with a complete `config`
object and `confirmed: true`. It has deliberately **no default/example payload**:
include `enabled`, positive finite `poll_interval_seconds`,
`auto_install_packages`, and **all `definitions`**, including unchanged ones.
An empty definitions list deletes all configured definitions. Preserve backend
`settings.password: "*****"` masks and `_original_name` rename hints by name/type,
not list position. Never replace credentials with `[REDACTED]`.

Saving reports `saved` and `restart_required`; it never restarts automatically.
Review package-install/hardware effects, then restart the Repeater separately
when ready. This does not change HA's integration polling interval.

## ACL

Select `script.openhop_example_set_acl_permissions` in the action editor and supply
an exact nonempty `identity_name`, actual **64-hex `client_pubkey`**, integer
`permissions`, and `confirmed: true`. No fake public key, identity or role default
is bundled. Role is the low two bits: **1 read-only, 2 read-write, 3 admin**; higher
flags remain. Values 1–255 must have nonzero low bits; multiples of four are invalid.
Room servers persist only admins. Inspect optional `persisted` in the private
response; a returned action does not prove persistence.

`script.openhop_example_remove_acl_client` requires an explicit identity name and
uses the preserved native **`public_key`** field (not `client_pubkey`). The wrapper
rejects an empty identity to avoid every-ACL removal. The native action retains
legacy hash-only/every-ACL scope; name wins over hash. No one-click grants or
removals are placed in the dashboard. Notifications never show public keys.

## On-demand diagnostics

Buttons capture 24-hour packet-rate buckets (300 seconds), noise statistics, CRC
count, and LBT (300-second buckets, severe-attempt threshold 3), plus local
companion packet diagnostics. They neither refresh the coordinator nor force
sensor hardware reads. Inspect the private trace for results, not notifications.
For named-radio noise/CRC or alternate hours, use native action editor fields;
LBT has **no `radio_id`**. Companion statistics are local, not remote RF telemetry.
Older backends may return unsupported-action errors.

All configuration/ACL inputs and responses can enter HA action/script traces;
restrict access. Never copy them into logs, notifications or sensor attributes.
See [management contracts](management-actions.md), [plugin upgrades](plugin-upgrades.md)
and [1.3.0 API notes](dev-api-1.3.0.md) for exact bounds and failure semantics.

Local parsed-YAML/source contracts verify wiring, fields and guards; they do not
prove HA schema validation, rendered layout, authenticated API or hardware behavior.
