# NSW Fire Watch status

Updated: 2026-08-29

## Current state

The release candidate is live on a Home Assistant 2026.8.1 installation. Its
configuration entry, official feed refresh, entities, same-origin sidebar panel,
bundled frontend, and mobile-width authenticated view have been verified after a
valid Home Assistant configuration check and restart.

The public repository is available at
<https://github.com/HallyAus/nsw-fire-watch> and can be added to HACS as a custom
repository. It remains a pre-release pilot until the first tagged `v0.1.1`
release is cut from a green CI run. GitHub currently refuses to start workflow
jobs because of an account billing lock; this external gate is not a reported
test failure.

## Implemented

- HACS integration packaging and UI config-flow structure.
- Direct official NSW RFS CAP-AU plus Current Incidents GeoJSON architecture
  with stable identity, proximity calculation, cross-check/fallback behaviour,
  explicit freshness, and retained last-good data.
- Primary NSW RFS fire-danger/Total Fire Ban data, with optional Bureau
  four-day Fire Behaviour Index and NSW land-warning context. No additional
  account, signup, API key, relay, or paid service is required.
- Separate ordering for separate jobs: the hero/alert priority stays
  warning-first, while active and planned-burn display lists are nearest-first;
  warning, control status, incident type, and distance remain distinct facts.
- Mobile-first frontend with a consolidated command brief, sticky Home exit,
  compact Home card and map, source timestamps, official links, AFDRS/Total Fire
  Ban presentation, progressively disclosed incident/forecast/readiness/source
  detail, and accessible touch targets.
- Locally bundled MapLibre GL JS 5.24.0 CSP assets with OpenFreeMap Liberty
  vector tiles: no key or signup, initial zoom 11, minimum zoom 9, persistent
  attribution, and a graceful official-source fallback that cannot alter status
  or incident lists.
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
- Recorder-safe summary payload trimming (10 nearest incidents and 4 nearest
  planned burns) while retaining a separate severity-first priority incident,
  full publisher totals, and map entities.
- HACS, hassfest, Python, JSON, packaging, and unit-test workflow.
- Migration, mobile/Nabu Casa behaviour, safety, rollback, privacy, and source
  attribution documentation.

## Verified deployment evidence

- On 2026-08-29, all 35 repository tests passed after the final mobile, map, and
  timestamp-normalisation changes. Ruff, Python compilation, JavaScript syntax,
  packaging, JSON/YAML parsing, and diff checks also passed. The suite guards
  every bundled MapLibre asset, licence/notice, provider reference, and zoom
  floor.
- Production configuration check completed successfully before restart.
- Integration loaded from the production custom-components directory and the
  imported config entry created its summary, danger, priority, count, health,
  warning, Total Fire Ban, and feed-problem entities.
- Live refresh received matching current-incident totals from RFS CAP and
  GeoJSON and established the initial lifecycle baseline without sending a burst
  of notifications for pre-existing incidents.
- `/nsw-fire-watch` and its same-origin JavaScript bundle loaded inside an
  authenticated Home Assistant session and were inspected at a mobile viewport.
- The keyless map was exercised locally and through Home Assistant Cloud/Nabu
  Casa: both the compact Home card and command centre rendered at initial zoom
  11/minimum zoom 9, contacted OpenFreeMap, made no API-key request, and retained
  the official-source fallback independently of incident status.
- The sticky Home control returned from `/nsw-fire-watch` to
  `/lovelace/default_view`; the Home dashboard retained all unrelated cards and
  now enables the compact Fire Watch map.
- Live RFS wall-clock `UPDATED` values were verified as Australia/Sydney before
  UTC conversion, fixing future-looking ages while preserving the publisher's
  timezone-aware CAP timestamps.
- The dashboard keeps today/tomorrow danger, Total Fire Ban state, the
  severity-first priority incident, and nearest incidents in its first mobile
  brief, with the local map next and lower-priority planned-burn, readiness, and
  source detail behind disclosure controls.

## Remaining release gates

- Restore GitHub Actions execution by clearing the account billing lock, then
  require a green HACS, hassfest, Python, JSON/YAML, packaging, and frontend
  syntax run before tagging `v0.1.1`.
- Confirmed the clearly labelled Advice test service completed through the
  assigned Companion App path at normal priority. The authenticated dashboard
  was also verified through both local Wi-Fi and configured remote access.
- Observe incident/danger lifecycle behaviour through further healthy refreshes,
  including escalation bypassing snooze and cautious resolution wording.
- Publish the first SemVer release only after that green CI run. Until then,
  custom-repository installs track the pre-release default branch.

## Known limitations

- Third-party custom integrations are not reviewed or supported by NSW RFS, the
  Bureau of Meteorology, Home Assistant, or HACS.
- Source feed availability and update timing are outside this project's control.
- The incident basemap depends on the public OpenFreeMap service and WebGL. It
  has no API-key/signup dependency or service-level guarantee; its failure is
  isolated from the warning brief/list and produces an official-source fallback.
- The bundled renderer is an interim compatibility layer. Reassess and remove
  it after Home Assistant's merged Shortbread vector-map change ships in a
  supported release and passes local plus remote Companion App verification.
- RFS point/polygon location time can differ from incident-detail update time;
  unmapped incidents may be placed at an approximate area location.
- Mobile push, actionable responses, and remote panel access depend on the user's
  Home Assistant, network, Companion App, phone permissions, and remote-access
  configuration.
- Repository-root blueprints are not copied by a HACS Integration install and
  must be imported from the documented raw URL.
- A Community strategy or compact card can be evaluated before the frontend
  module is ready on the first cold load after install/update and can require
  one dashboard reload. The integration-owned sidebar panel is the reliable
  cold-start path.
- Local Home Assistant brand icons are bundled at 256 px and 512 px. Home
  Assistant releases before 2026.3 do not use local custom-integration brand
  assets, but this does not affect integration functionality.

## Rollback posture

Production migration is intentionally reversible: keep legacy alert automations
disabled rather than deleted during the observation period. Disable the new
blueprint automation first, restore the legacy automation if needed, then remove
or roll back the HACS release and restart Home Assistant.
