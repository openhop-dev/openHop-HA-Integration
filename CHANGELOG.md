# Changelog

## 1.1.2

- fixed the `Packets received per hour` and `Packets forwarded per hour` sensors to use `/api/packet_stats?hours=1` instead of the repeater status counters backed by the capped `recent_packets` buffer
- added newer GPS diagnostics fields from recent repeater API updates, including position source metadata and GPS time sync state
- added Home Assistant actions for `adverts_by_contact_type` and `adverts_count_by_contact_type`

## 1.1.1

- stopped polling GitHub branch data every 60 seconds by removing `update_channels` from the normal integration refresh loop
- kept update status polling local to the repeater while making the update channel UI use a local fallback list instead of live GitHub branch fetches
- reduces unnecessary GitHub API traffic and avoids rate limiting caused by routine Home Assistant polling

## 1.1.0

- moved the `dev` branch forward onto the `1.1.x` release line for continued development

## 1.0.2

- added GPS stream support using `/api/gps_stream` for faster live GPS updates
- kept normal polling for non-GPS entities while allowing GPS entities to refresh immediately from the repeater stream

## 1.0.1

- expanded GPS diagnostics from newer repeater API data
- added additional GPS state, motion, accuracy, time, and NMEA-related entities and attributes

## 1.0.0

Initial stable release of the pyMC Repeater Home Assistant integration.

- config flow setup using repeater host, port, and admin password
- dedicated API token bootstrap and token-based polling
- repeater, radio, hardware, database, MQTT, ACL, room, companion, update, and GPS telemetry
- Home Assistant sensors, binary sensors, switches, buttons, selects, and numbers for repeater monitoring and control
- dashboard template for Lovelace
- HACS validation, Hassfest validation, and Python smoke-test workflows
