# Installed Repeater API alignment

This focused compatibility update was checked against installed **openHop Repeater 1.1.2.dev325** Python source and its bundled OpenAPI, not inferred from a newer Git branch. It does not claim complete endpoint parity or live Home Assistant validation.

## Verified contracts

| Contract | Installed implementation | Integration behavior |
| --- | --- | --- |
| `GET /api/plugins/` | `web/plugin_endpoints.py:index`, `_ok`; top-level `success` and `plugins`, not a `data`-wrapped list | One request on the shared refresh; reduce the list to installed/enabled/running/failed counts and allowlisted per-ID health metadata before retaining it |
| Plugin states | `plugins/manager.py:list_plugins` delegates to `plugins/runtime.py:status_dict`; boolean `enabled`, uppercase states | Count exact `RUNNING` and `FAILED`; do not infer failure from enabled-but-stopped UI-only plugins |
| Plugin authentication | `web/http_server.py` protects `/api`; `web/auth/cherrypy_tool.py` accepts `X-API-Key` | Existing API-token authentication, no additional credentials |
| Missing manager | Plugin API returns HTTP 503; older versions may return 404 | Optional endpoint error leaves plugin counts unknown; unrelated telemetry remains usable. Authentication/connection errors still fail refresh |
| `GET /api/neighbor_link_history` | `web/api_endpoints.py` adds optional `bucket_seconds`, minimum 60 | Existing action gains optional field without changing its name or legacy defaults |
| History response | `rows` without buckets; `buckets` plus `bucket_seconds` when supplied; `count` is returned rows/buckets | Preserve the response unchanged; do not silently substitute raw data for requested buckets |
| History aggregation | `data_acquisition/sqlite_handler.py` groups stored observations in SQL; newest capped results returned chronologically | No history polling or entity attributes; explicit action only, existing 1–5000 result limit retained |

Application plugins are distinct from sensor-manager plug-ins exposed under `stats.sensors`. Only ID, name, version, enabled, state and has_runtime are retained with counts. Filesystem paths, repository URLs, logs, settings and runtime documents are not stored in the coordinator summary. Malformed inventory is an error, not a zero count. There are no new write actions.

## Source fingerprints

SHA-256 of the selected installed files (paths relative to the installed `repeater` package):

```text
web/api_endpoints.py
f8cd9b2029239d4896d449141b2af81309dda9572a8854ef79bab9db91c9eee9
web/plugin_endpoints.py
96766f7d762b9a3180ce877735c23c3399cfb1700fd2cc98a25defc814f8fbe0
web/openapi.yaml
cc8982b6194f4748fcaf5dc392055e89fda6dfb2a20d34ef4e79ec1c7499184f
plugins/runtime.py
424f410448918413e60be596e4827ac134c5ee345387c4bf815bfe9ac66ab77e
data_acquisition/sqlite_handler.py
98612f1677c9ccdec6d53c6a5cd3654347f79cf99de16bb64b9e30d1606940c4
```

Package version is provenance, not proof of equivalence to an upstream Git SHA. No live configuration, token database, keys, packets, locations, or plugin runtime data were used as fixtures.

## Deliberately not covered

- Plugin install/update/uninstall, lifecycle controls, catalogue/update checks, settings, logs, runtime documents and installation-progress SSE. These are not needed for read-only health and may be disruptive, sensitive or expensive.
- Packet-order summaries from newer development work: the inspected installed `get_packet_stats` implementation does not provide them. No guessed sensors or fields are added.
- Bulk packet datasets, additional filtered histories, and other endpoints outside this focused audit. Existing raw radio/MQTT action payloads are not a fully validated generated API client.
- Older builds without bucket support must omit `bucket_seconds`. No version negotiation or automatic retry to raw rows is implemented.
- The existing per-endpoint timeout and fatal transport/auth behavior are unchanged. Plugin 404/503 is isolated, but a transport timeout still fails the refresh.

## Validation boundaries

Run `python3 -m unittest discover -s tests -v`. The existing suite checks source contracts; `test_installed_api_behavior.py` also executes the real client methods and sensor value lambdas extracted from trusted checked-in source with a fake HTTP boundary. It exercises top-level plugin responses, empty/malformed inventories, exact counts, privacy minimization, optional/fatal polling failures, and raw/bucketed history contracts without Home Assistant dependencies or a network connection.

Compilation and JSON/YAML parsing complement these tests; they do not validate real HA entity registration, Voluptuous execution, recorder behavior, authenticated HTTP responses, or coordinator timing in a running HA instance. HACS/Hassfest remain CI checks, not locally reproduced gates.
