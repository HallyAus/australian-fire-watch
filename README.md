# NSW Fire Watch for Home Assistant

NSW Fire Watch is a mobile-first Home Assistant integration and dashboard for
bush-fire awareness in New South Wales. It puts the official warning and the
action to take first, keeps control status and distance as separate facts, moves
planned burns out of the urgent incident list, and turns feed changes into
deduplicated lifecycle events for assigned alerts.

> [!CAUTION]
> NSW Fire Watch is supplementary, unofficial software. It is not endorsed by
> NSW RFS, the Bureau of Meteorology, or Home Assistant. Do not rely on it as
> your only warning channel. Keep **Hazards Near Me NSW / Fires Near Me NSW**, a
> battery radio, and your bush-fire survival plan available. In an emergency,
> call **Triple Zero (000)**.

> [!NOTE]
> The current build has been deployed and verified on a live Home Assistant
> installation. The public repository is available now and can be added to HACS
> as a custom repository, but it is still a pre-release pilot: the first tagged
> `v0.1.1` release is waiting for a green CI run. GitHub currently refuses to
> start the repository's workflow because of an account billing lock; this is an
> infrastructure gate, not a reported test failure. See [STATUS.md](STATUS.md).

## Why this is different

- A severity-first hero shows Emergency Warning, Watch and Act, or Advice before
  maps and secondary detail.
- The incident list is nearest-first for fast local scanning, while the hero's
  priority incident remains warning/severity-first so a more distant Emergency
  Warning cannot be hidden by a nearby lower-level incident.
- Official warning level, incident type, control status, proximity, and fire
  danger rating remain distinct. A nearby uncontrolled incident does not get
  mislabelled as an official Emergency Warning.
- Today and tomorrow use the Australian Fire Danger Rating System (AFDRS), with
  Total Fire Ban state and source timestamps.
- Stale, missing, or malformed data is visibly unavailable; it is never shown as
  green, "safe", or an all-clear.
- Lifecycle tracking emits only meaningful transitions such as new, escalated,
  de-escalated, `left_radius`, and resolved. Moving into a closer proximity band
  is an escalation and clears acknowledgement/snooze state.
- A bundled, responsive panel works inside the authenticated Home Assistant UI
  and Companion App. No separate web login, worker URL, shared secret, or cloud
  account is required.
- A compact command brief answers what matters now, keeps a sticky **Home** exit
  visible on mobile, and progressively discloses forecast, readiness, planned
  burn, and source detail.
- A locally bundled MapLibre renderer uses OpenFreeMap's Liberty vector style,
  starts near home at zoom 11, will not zoom farther out than zoom 9, and needs
  no map API key or additional signup.
- An optional automation blueprint assigns alerts to a Companion App device with
  bounded acknowledgement and snooze controls.

## Install with HACS

This project is distributed as a HACS **Integration** custom repository. Until
the first tagged release is published, HACS installs the current default branch;
treat that build as a pilot and keep a Home Assistant backup for rollback.

1. In HACS, open **Integrations**, then the menu and **Custom repositories**.
2. Add `https://github.com/HallyAus/nsw-fire-watch` with category
   **Integration**.
3. Search for **NSW Fire Watch**, download it, and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration**, search for
   **NSW Fire Watch**, and complete the setup flow.
5. Open **NSW Fire Watch** from the sidebar after the first successful refresh.

For a manual install, copy `custom_components/nsw_fire_watch` into the same path
under your Home Assistant configuration directory, then restart Home Assistant.
HACS is preferred because it provides update tracking and rollback to a previous
release.

### Configure a monitored location

Create a config entry for each location that needs its own radius and alert
assignment. Use a Home Assistant zone rather than entering coordinates into
automations or dashboards. A typical first entry is the `zone.home` location.

Start with conservative radii, review the resulting list, and tune them for local
roads, terrain, family plans, and official guidance. Distance is a screening
tool—not a prediction of fire travel, time to impact, or property safety.

The integration creates a summary sensor consumed by the bundled panel/card and
tracks its previous incident snapshot in Home Assistant storage. Initial setup
establishes a baseline; it does not notify for every incident already in the
feed.

## Dashboard and mobile access

The integration registers the `/nsw-fire-watch` panel on the same origin as Home
Assistant. This sidebar panel is the primary and most reliable dashboard. It
inherits the current Home Assistant session:

- at home, the Companion App may use the local Home Assistant URL;
- away from home, it uses the remote URL configured for that Home Assistant
  server, including Home Assistant Cloud/Nabu Casa when enabled;
- the integration does not store or proxy the external URL, credentials, access
  tokens, or a second shared secret; and
- relative links in notifications open the correct server selected by the app.

There is no Cloudflare Worker or separate snapshots login. The panel never asks
for a worker URL or shared secret and does not store either value in
`localStorage`. If that connection form appears, the user has opened the legacy
Command Centre frontend rather than the NSW Fire Watch sidebar panel.

Remote access and push delivery still depend on the Companion App and Home
Assistant remote access being healthy. Test both while on home Wi-Fi and while
using mobile data before fire season.

The frontend is dependency-free and ships inside the integration. It provides:

- `nsw-fire-watch-panel` for the sidebar;
- `custom:nsw-fire-watch-card` for a Lovelace view; and
- `custom:nsw-fire-watch` for Home Assistant Community dashboards that support
  strategy registration.

The integration registers its frontend module automatically. For a compact
status card near the top of an existing Home dashboard, use:

```yaml
type: custom:nsw-fire-watch-card
entity: sensor.home_status
title: NSW Fire Watch
compact: true
show_map: true
show_readiness: false
```

Replace the example entity with the summary entity created for the monitored
location. The compact card keeps the current status, priority incident, fire
danger, feed health, a local incident map, and the link to the full panel in one
mobile-first container. The command brief stays ahead of the map so urgent
information does not require searching or panning.

### Incident map

The card and panel bundle MapLibre GL JS 5.24.0's CSP-compatible browser assets
inside the integration and render the keyless
[OpenFreeMap Liberty](https://openfreemap.org/quick_start/) vector style. The map
centres on the configured Home Assistant zone at zoom 11 and enforces a minimum
zoom of 9 instead of auto-fitting every incident across NSW. This keeps the
first view local while still allowing the user to zoom in and inspect markers.

Map attribution remains visible. If WebGL or the public vector-tile service is
unavailable, the current warning, command brief, and nearest-first incident list
continue to work and the map area offers an official-source fallback; a map
failure never changes the fire status. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the bundled software and
map-data terms.

This renderer is an interim compatibility layer for Home Assistant versions
whose native map still uses the affected CARTO raster path. Home Assistant has
already [merged a move to Shortbread vector tiles](https://github.com/home-assistant/frontend/commit/337e8856);
the bundled renderer can be reassessed and removed after that change ships in a
supported Home Assistant release and is verified locally and remotely.

The dedicated sidebar panel remains the recommended mobile experience. Home
Assistant does not await third-party frontend modules before evaluating every
dashboard path, so the Community strategy—and, on the first frontend load after
an install or update, the compact card—can briefly be evaluated before the
module is ready. Reload the dashboard once if Home Assistant reports an unknown
strategy or custom element. The integration-owned sidebar panel is the reliable
cold-start path.

### Household readiness helpers

The integration options can include `input_boolean` helpers as tappable
household-readiness checks. A starter package is provided in
[`examples/readiness-package.yaml`](examples/readiness-package.yaml). Configure
only concrete preparation tasks, such as reviewing the survival plan, checking
the go-bag, confirming contacts, and preparing pet transport. A checked helper
records that task only; it never means the household, property, or route is
safe.

### Summary payload and totals

Home Assistant limits the size of state attributes stored by the recorder. The
summary sensor therefore includes the 10 nearest active incidents and the 4
nearest planned burns in its `incidents` and `planned_burns` attributes. The
severity-first `highest_priority_incident` is calculated separately and is not
changed by this display order. Complete publisher totals remain available as
`incident_count` and `planned_burn_count`, and the dashboard labels any rows
omitted from its compact payload. All generated `geo_location` entities remain
available to Home Assistant. This trimming protects recorder health; it does
not reinterpret a missing row as a resolved incident or an all-clear.

## Assigned mobile alerts

HACS installs the custom integration directory but does not copy repository-root
blueprints. Import the blueprint separately from:

`https://raw.githubusercontent.com/HallyAus/nsw-fire-watch/main/blueprints/automation/hallyaus/nsw_fire_watch_assigned_alerts.yaml`

In Home Assistant, open **Settings → Automations & scenes → Blueprints → Import
blueprint**, paste that URL, then create an automation from **NSW Fire Watch -
assigned mobile alerts**.

Create one blueprint automation per assigned Companion App device. Each instance
can filter to a configured location, select a minimum warning level, include
fire-danger/Total Fire Ban changes, and choose which lifecycle changes are
delivered.

Delivery has a single owner. When one or more `notify.*` services are assigned in
the integration options, direct integration delivery owns those recipients and
every event carries `direct_delivery_configured: true`; the supplied blueprint
automatically stands down. To make the blueprint the delivery owner, leave the
integration notification-service list empty. Do not create a second user
automation for the same recipient unless duplicate notifications are
intentional.

Both delivery paths observe intentionally bounded safety rules:

- Advice is a normal notification and may be snoozed for up to two hours.
- Watch and Act is time-sensitive and may be snoozed for only 15–30 minutes.
- Emergency Warning can be acknowledged but never snoozed.
- Escalation overrides the lifecycle filter and any active snooze.
- Critical delivery applies to an incident Emergency Warning and to today's
  Catastrophic rating or Total Fire Ban. It never applies to Advice, tests,
  de-escalation, resolution, `left_radius`, or "no incidents" messages.
- Resolution means the incident is no longer present in the current feed. The
  message explicitly does **not** call that an all-clear.

The phone operating system controls whether critical alerts may bypass Focus,
Do Not Disturb, or mute. Verify those permissions and the **NSW Fire Watch**
notification channel on each assigned device. Do not assume an alert was seen;
use a household check-in plan as well.

The blueprint exposes an optional **Additional delivery actions** input for a
notify group, wall panel, TTS, or another user-owned action. Those actions may use
the variables `alert_title`, `alert_message`, `alert_data`, `incident_id`,
`location_name`, `lifecycle`, `level`, and `official_url`.

### Lifecycle event contract

The integration fires `nsw_fire_watch_alert` for both incident and fire-danger
lifecycle changes. Consumers must branch on `alert_kind` before reading the
nested object:

| Field | Meaning |
| --- | --- |
| `alert_kind` | `incident` or `danger`; selects the nested payload shape |
| `entry_id`, `location_name` | Monitored Home Assistant config entry/location |
| `lifecycle` | `new`, `updated`, `escalated`, `deescalated`, `resolved`, `left_radius`, or `test` |
| `incident_id`, `incident` | For `alert_kind: incident`, stable publisher identity and the current nested warning/type/control/distance/timestamp/URL mapping; `incident` is `null` on resolution |
| `danger_id`, `danger` | For `alert_kind: danger`, calendar-date identity and the nested district, period, rating, rating rank, Total Fire Ban, issue time, and source mapping |
| `previous` | Minimal previous nested snapshot used to explain a transition or resolution |
| `qualifies_for_alert` | Whether the incident radius or published fire-danger/ban threshold qualifies for assigned delivery |
| `notification_allowed` | Acknowledgement/snooze gate for routine incident delivery; escalation and safety-relevant lifecycle changes remain allowed |
| `delivery_priority` | Integration classification: `normal`, `time_sensitive`, or `critical`; tests and clearing/de-escalation events are normal |
| `direct_delivery_configured` | `true` when integration-owned `notify.*` targets exist, instructing the supplied blueprint to stand down |
| `test` | Explicit test marker; test events never become critical |
| `summary`, `recommended_action`, `notification_tag` | Optional notification-ready convenience fields |
| `official_url` | Official publisher destination for the incident or danger product |

`left_radius` is not a resolution: the incident is still present in the current
official data but has moved outside the configured monitoring radius. Incident
`resolved` is emitted only after absence is confirmed across two healthy
authoritative snapshots. A danger `resolved` event means a qualifying published
rating or Total Fire Ban declaration changed or ended; it is not an all-clear.

The public actions are:

- `nsw_fire_watch.acknowledge` — record acknowledgement for one incident;
- `nsw_fire_watch.snooze` — suppress bounded reminders for one incident using
  `duration_minutes`; and
- `nsw_fire_watch.test_alert` — emit a clearly labelled test event without
  impersonating a live warning.

Use the test action after changing notification recipients, remote access,
critical-alert permissions, or dashboard routes.

## Better API choice

NSW Fire Watch talks directly to documented NSW RFS and Bureau publisher
products. It does not scrape the Fires Near Me webpage, depend on five generated
template sensors, or call the undocumented per-incident endpoint exposed inside
feed identifiers.

The official-source stack is deliberately layered:

| Publisher product | Integration role |
| --- | --- |
| NSW RFS [`majorIncidentsCAP.xml`](https://www.rfs.nsw.gov.au/feeds/majorIncidentsCAP.xml) (CAP-AU) | Structured alert identity, official warning text and instructions, expiry, and geometry |
| NSW RFS [`majorIncidents.json`](https://www.rfs.nsw.gov.au/feeds/majorIncidents.json) (Current Incidents GeoJSON) | Complete incident set, stable identifiers, point/perimeter geometry, operational detail, and incident fallback/cross-check |
| NSW RFS [`IncidentAlerts.xml`](https://www.rfs.nsw.gov.au/feeds/IncidentAlerts.xml) | Supplemental published alert/warning polygons |
| NSW RFS [`fdrToban.xml`](https://www.rfs.nsw.gov.au/feeds/fdrToban.xml) | Primary today/tomorrow AFDRS rating and Total Fire Ban declarations |
| Bureau [`IDN10016.xml`](https://www.bom.gov.au/fwo/IDN10016.xml) | Optional published four-day NSW Fire Behaviour Index/rating outlook |
| Bureau [`IDZ00061.warnings_land_nsw.xml`](https://www.bom.gov.au/fwo/IDZ00061.warnings_land_nsw.xml) | Optional official NSW land/fire-weather warning context |

Compared with consuming only Home Assistant's derived `geo_location` entities,
the source stack retains publisher identifiers and geometry, exposes coherent
feed health, and detects material changes before Home Assistant entity names are
generated. CAP and GeoJSON are merged conservatively: a higher official warning
may win, but control status is never promoted into a warning.

The documented products are preferred over an attractive but unsupported
private endpoint because publisher intent and change visibility matter more than
an extra field in an emergency-adjacent system. Requests use conditional HTTP
validators where available, retain a clearly marked last-known-good response,
cap response size, and back off after failures. No API key, paid tier, account,
or additional signup is required.

Existing Home Assistant weather entities may be shown as supplementary local
context, but weather values are never used to invent a fire-spread direction or
evacuation recommendation.

## Migration from a legacy RFS dashboard

Migrate side by side so there is always a recoverable warning path:

1. Create a full Home Assistant backup and export the existing fire automations
   before changing them.
2. Install NSW Fire Watch and configure the same home zone. Leave the old RFS
   feed, template sensors, map card, and notifications in place initially.
3. Compare incident counts, warning labels, distance, feed age, and official
   links over several refreshes. Use `nsw_fire_watch.test_alert` to verify the
   new mobile path without waiting for a real event.
4. Import the assigned-alert blueprint. Keep the resulting automation disabled
   until the test reaches the intended phone locally and remotely.
5. Enable the new alert automation, then disable—not delete—the old manual and
   real-time RFS alert automations. This prevents duplicate notifications while
   preserving a one-click fallback.
6. After a stable observation period, remove the five hand-written nearest-
   incident template sensors, distance-only list, legacy emergency helper, and
   oversized map-first card only after confirming nothing else references them.
7. Keep the official Hazards Near Me NSW app and other official channels in
   service throughout the migration.

Do not migrate unrelated weather, grocery, camera, or household automations into
this project. A dedicated fire dashboard should remain focused during stress.

## Recovery and rollback

If the integration or a release behaves unexpectedly:

1. Disable every automation created from the NSW Fire Watch alert blueprint.
2. Re-enable the previous fire alert automation if it was retained during the
   migration.
3. In **Settings → Devices & services**, disable or remove the NSW Fire Watch
   config entry. Removing an entry removes its entities and stored alert state;
   it does not change official services or the Companion App.
4. In HACS, redownload the previously known-good release, or remove the
   integration and restart Home Assistant.
5. Restore the pre-migration Home Assistant backup only if configuration files
   were also removed or changed and the targeted rollback is insufficient.

If the panel says data is stale, do not repeatedly restart Home Assistant as a
substitute for checking the official source. Open Hazards Near Me NSW / Fires
Near Me NSW, NSW RFS, radio, or other official channels first, then inspect Home
Assistant logs for `custom_components.nsw_fire_watch`.

## Safety

This software deliberately does not:

- declare a property, road, route, or person safe;
- predict rate or direction of spread from wind or map geometry;
- calculate evacuation routes or a time-to-impact;
- promise that official warning levels will always precede a fast-moving fire;
- treat a missing incident, stale feed, or failed request as an all-clear;
- use camera/AI detections as an official warning source; or
- automatically open gates, start sprinklers, control HVAC, or trigger other
  physical safety equipment.

Incident points and polygons can be approximate, and their spatial update time
may differ from the incident-detail update time. Follow official warning text
and your bush-fire survival plan. If you see an unattended fire, call 000.

## Data sources and attribution

- [NSW RFS public feeds](https://www.rfs.nsw.gov.au/news-and-media/stay-up-to-date/feeds)
- [NSW RFS Fires Near Me](https://www.rfs.nsw.gov.au/fire-information/fires-near-me)
- [NSW RFS alert levels](https://www.rfs.nsw.gov.au/plan-and-prepare/alert-levels)
- [NSW RFS fire danger ratings and Total Fire Bans](https://www.rfs.nsw.gov.au/fire-information/fdr-and-tobans)
- [Bureau of Meteorology NSW warnings](https://www.bom.gov.au/nsw/warnings/)
- [Bureau RSS and XML feeds](https://www.bom.gov.au/rss/)
- [Bureau brand, trademark, and display policy](https://www.bom.gov.au/data-access/brand-trademark-display-policy.shtml)
- [Bureau copyright and terms](https://www.bom.gov.au/copyright)
- [Bureau disclaimer](https://www.bom.gov.au/disclaimer)

Required publisher attribution:

> © State of New South Wales (NSW Rural Fire Service). For current information
> go to www.rfs.nsw.gov.au.

NSW RFS feed material remains subject to the licence, notices, limitations, and
disclaimers published with those feeds. The MIT licence in this repository
covers the NSW Fire Watch software only; it does not relicense NSW RFS, Bureau of
Meteorology, Home Assistant, map-tile, or third-party data and marks. Official
marks are not used as project branding. Any Bureau attribution image is the
official, unmodified attribution asset used only for source acknowledgement; no
endorsement is implied.

The direct Bureau products are intended here for personal/internal Home
Assistant use and are fetched by the user's own instance; this project does not
operate a central weather-data redistribution service. Users republishing data
or using it for a non-personal or commercial purpose must review the current
Bureau terms and obtain the appropriate permission or registered data service.
Keep the functional source links, issue/validity times, notices, and the Bureau's
official unmodified attribution treatment shown by the integration.

## Privacy and network behaviour

Processing, radius calculations, lifecycle state, acknowledgements, and snoozes
remain in Home Assistant. The integration makes read-only HTTPS requests to the
official data publishers and does not run a relay, analytics service, or project-
owned cloud backend. Location coordinates come from the selected Home Assistant
zone and are not embedded in this repository or notification blueprint.

When a dashboard map is enabled, the browser also requests its style and visible
map tiles directly from the public OpenFreeMap service. Those tile coordinates
approximate the area being viewed (initially the monitored zone), and the service
receives normal request metadata such as the client IP address. Set
`show_map: false` on the card or dashboard strategy to opt out; incident status,
distance, warnings, and official links continue to work without the map.

The Home Assistant Companion App's own push and remote-access services operate
under their normal configuration. Review those services separately if the
household has stricter privacy or availability requirements.

## Development and validation

```bash
python -m pip install pyyaml
python -m compileall -q custom_components tests
python -m unittest discover -s tests -v
```

Pull requests run the HACS repository action, Home Assistant hassfest, Python
compilation, unit tests, packaging checks, JSON validation, and blueprint checks.
A production install still needs a Home Assistant configuration check before
restart and a real Companion App test after restart.

## Licence

NSW Fire Watch software is released under the [MIT licence](LICENSE).
