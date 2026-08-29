# NSW Fire Watch status

Updated: 2026-08-29

## Current state

The release candidate is live on a Home Assistant 2026.8.1 installation. Its
configuration entry, official feed refresh, entities, same-origin sidebar panel,
bundled frontend, and mobile-width authenticated view have been verified after a
valid Home Assistant configuration check and restart.

The project remains pre-release for other users: the public GitHub repository
and first SemVer release have not yet been created, so it cannot yet be added to
HACS as a custom repository.

## Implemented

- HACS integration packaging and UI config-flow structure.
- Direct official NSW RFS CAP-AU plus Current Incidents GeoJSON architecture
  with stable identity, proximity calculation, cross-check/fallback behaviour,
  explicit freshness, and retained last-good data.
- Primary NSW RFS fire-danger/Total Fire Ban data, with optional Bureau
  four-day Fire Behaviour Index and NSW land-warning context. No additional
  account, signup, API key, relay, or paid service is required.
- Warning-first ranking that keeps warning, control status, incident type,
  distance, and planned burns separate.
- Mobile-first frontend with a reliable sidebar panel, compact Home card, source
  timestamps, official links, AFDRS/Total Fire Ban presentation, incident
  detail, planned-burn separation, feed health, and accessible touch targets.
- Same-session access through the Home Assistant frontend/Companion App using
  its configured local or Home Assistant Cloud/Nabu Casa route. There is no
  Worker URL, separate snapshots login, shared secret, or second auth store.
- Incident and danger lifecycle event contract with nested payloads,
  `alert_kind`, `notification_allowed`, `delivery_priority`, and explicit
  `left_radius` versus two-snapshot `resolved` semantics.
- Acknowledgement, bounded snooze, and test services.
- Single-owner alert delivery: configured direct `notify.*` services own
  delivery, otherwise the optional assigned Companion App blueprint can own it;
  the supplied blueprint automatically stands down when direct delivery exists.
- Assigned Companion App blueprint with incident/danger thresholds, unique
  actionable responses, Emergency Warning no-snooze behaviour, and no critical
  Advice/test/clearing messages.
- Optional tappable readiness `input_boolean` helpers, with wording that never
  equates checklist completion with safety.
- Recorder-safe summary payload trimming (10 ranked incidents and 4 planned
  burns) while retaining full publisher totals and map entities.
- HACS, hassfest, Python, JSON, packaging, and unit-test workflow.
- Migration, mobile/Nabu Casa behaviour, safety, rollback, privacy, and source
  attribution documentation.

## Verified deployment evidence

- On 2026-08-29, all 8 packaging/document safety checks and all 31 repository
  unit tests passed after the documentation update.
- Production configuration check completed successfully before restart.
- Integration loaded from the production custom-components directory and the
  imported config entry created its summary, danger, priority, count, health,
  warning, Total Fire Ban, and feed-problem entities.
- Live refresh received matching current-incident totals from RFS CAP and
  GeoJSON and established the initial lifecycle baseline without sending a burst
  of notifications for pre-existing incidents.
- `/nsw-fire-watch` and its same-origin JavaScript bundle loaded inside an
  authenticated Home Assistant session and were inspected at a mobile viewport.
- The deployed dashboard showed today/tomorrow fire-danger data, priority
  incident information, planned burns, readiness items, source health, and the
  lower-priority map in the intended stress hierarchy.

## Remaining release gates

- Run the final full unit, packaging, Python, JSON/YAML, and frontend syntax
  checks after the release contents are frozen.
- Exercise `nsw_fire_watch.test_alert` on the assigned Companion App device over
  both local Wi-Fi and configured remote access and verify the clearly labelled
  test remains non-critical.
- Observe incident/danger lifecycle behaviour through further healthy refreshes,
  including escalation bypassing snooze and cautious resolution wording.
- Publish the GitHub repository and first SemVer release before asking other
  users to add it as a HACS custom repository.

## Known limitations

- Third-party custom integrations are not reviewed or supported by NSW RFS, the
  Bureau of Meteorology, Home Assistant, or HACS.
- Source feed availability and update timing are outside this project's control.
- RFS point/polygon location time can differ from incident-detail update time;
  unmapped incidents may be placed at an approximate area location.
- Mobile push, actionable responses, and remote panel access depend on the user's
  Home Assistant, network, Companion App, phone permissions, and remote-access
  configuration.
- Repository-root blueprints are not copied by a HACS Integration install and
  must be imported from the documented raw URL.
- A Community dashboard strategy may be evaluated before the frontend module is
  ready on a cold load and can require one dashboard reload. The sidebar panel
  and a normal Lovelace view using the compact card are the reliable primary
  paths.
- Home Assistant Brands registration is not yet complete; the HACS workflow
  ignores only that custom-repository check. It must be resolved before seeking
  inclusion as a default HACS repository.

## Rollback posture

Production migration is intentionally reversible: keep legacy alert automations
disabled rather than deleted during the observation period. Disable the new
blueprint automation first, restore the legacy automation if needed, then remove
or roll back the HACS release and restart Home Assistant.
