# Repeater dev review for 1.3.1

## Source and scope

Reviewed freshly fetched Repeater `origin/dev` at immutable commit
`98444069ee49d21aff1e2a4d67a53ae7c53fecaa`. Source was read with `git show` /
`git diff`, not taken from the backend checkout's potentially different working
branch. The prior 1.3.0 management audit used
`3c4bf3a9586d1e0b3871091649bc3fd09da3b662`.

The comparison covers HTTP handlers and bundled OpenAPI, with relevant runtime
helpers traced for selected additions. This is source compatibility research,
not authenticated appliance testing or an exhaustive HA runtime certification.

## Newly available API capabilities

| Capability | Repeater contract | HA scope |
| --- | --- | --- |
| Network and MQTT rolling usage | `GET /api/network_usage`, bounded hours/days queries, persisted interface and publication history | Candidate for an explicit response action; do not poll the full history at the normal coordinator interval |
| Radio front-end controls | `GET/POST /api/radio_frontend`, default-radio capabilities, AGC reset interval 0–3600 seconds, FEM RX/TX gain and boosted RX gain | Future capability-aware controls; do not infer per-radio attribution or change live RF settings automatically |
| Explicit path tracing | `/api/trace` and `/api/trace_info` | Future explicit action; tracing transmits and is not a harmless monitoring probe |
| Companion message history | `GET /api/companion/messages`, ascending IDs, `since` cursor and limit capped at 500; 404 when history is disabled | Future opt-in response action, never ordinary polling or entity attributes containing private message content |
| Direct message retry metadata | Companion `send_text` accepts attempt 0–255, timestamp 0–4294967295, and `wait_for_ack` | Future backward-compatible optional action fields; omitted values must preserve existing semantics |
| Scoped channel messages | Companion `send_channel_message` accepts timestamp and a per-message flood-scope key | Future explicit action fields; never change the companion's persistent scope as a substitute |
| Send correlation | Direct/channel send results can include a packet hash | Future optional action responses can correlate packet-log records; hash presence alone does not prove recipient delivery |

For direct messages, timestamp zero means use a fresh timestamp; CLI message
types also use a fresh timestamp. Channel timestamp zero is passed through.
With `wait_for_ack: false`, `sent` indicates packet handoff rather than a received
ACK. These distinctions must remain visible when extending the existing actions.
The frontend setter applies supported settings first and persists confirmed
values; partial failure is not an all-or-nothing transaction.

## Release boundaries

### Implemented in 1.3.1

The existing `/api/mqtt_status` poll now reduces per-broker `sent.messages` and
`sent.payload_bytes` into two diagnostic sensors. No new requests are added.
Only complete nonnegative integer counter inventories produce totals; legacy,
malformed, inactive, oversized or overflowing inventories remain unknown.
Per-broker sent objects are removed before coordinator storage, retaining only
the two allowlisted aggregate scalars alongside existing status metadata.
These measure local publication handoff, not broker acknowledgment or network
overhead. Session recreation and broker membership changes can reduce totals,
so both are measurements rather than lifetime increasing counters.

Existing config entries, `pymc_repeater` service/entity identities, radio aliases,
full-poll scheduling and GPS background handling are retained. No automatic
history retrieval, radio writes, message sends, trace transmissions, deployment,
or integration reload is performed by this review.

See [dependency ownership and CI audit](dependencies-1.3.1.md) for dependency
versions, maintained automation, and runtime compatibility boundaries.
