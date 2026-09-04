# Australian Fire Watch for Home Assistant

☕ [Support Australian Fire Watch on Buy Me a Coffee](https://buymeacoffee.com/hallyaus)

Australian Fire Watch is a HACS-installable Home Assistant integration and
mobile-first dashboard for bushfire awareness across every Australian state and
territory. It normalises official incident feeds, ranks nearby warnings, creates
native geo-location entities, and can send lifecycle-aware notifications.

The Home Assistant integration domain is `australian_fire_watch`.

> **Safety**
>
> This is supplementary, unofficial software. It is not endorsed by any
> emergency service, the Bureau of Meteorology, or Home Assistant. Never treat
> missing, stale, or unavailable data as safe. Keep your jurisdiction's official
> emergency app and alerts enabled, listen to local radio, and follow emergency
> instructions. In a life-threatening emergency call Triple Zero (000).

## What is included

- One config flow for ACT, NSW, NT, Queensland, South Australia, Tasmania,
  Victoria, and Western Australia.
- Official-warning, control-status, incident-type, planned-burn, distance, and
  feed-health fields kept separate.
- Radius-aware, deduplicated lifecycle events and optional direct notifications.
- Dynamic geo_location entities for every mapped incident.
- A bundled sidebar command centre and a reusable Lovelace card.
- A bundled Home Assistant dashboard strategy.
- Home Assistant's native map card, using the monitored zone as the focus and
  incident entities as non-focusing overlays.
- NSW fire-danger, Total Fire Ban, FBI, and BOM warning enrichment.

## Install with HACS

Until the repository is listed in HACS defaults:

1. Open **HACS → Integrations → Custom repositories**.
2. Add https://github.com/HallyAus/australian-fire-watch as an **Integration**.
3. Search for **Australian Fire Watch**, download it, and restart Home Assistant.
4. Open **Settings → Devices & services → Add integration**.
5. Select **Australian Fire Watch**, choose the state or territory containing
   the monitored zone, and complete the setup.
6. Open **Australian Fire Watch** from the sidebar after the first refresh.

The dashboard ships inside the integration. No manual resource, card download,
or dashboard YAML is required.

### Manual installation

Copy `custom_components/australian_fire_watch` to the same path under the Home
Assistant config directory, restart Home Assistant, then add the integration in
the UI.

## Dashboard and card

The integration registers `/australian-fire-watch` as its sidebar dashboard.
The same UI is available as a card:

    type: custom:australian-fire-watch-card
    show_map: true
    show_readiness: true

For a compact Home view:

    type: custom:australian-fire-watch-card
    compact: true
    show_map: false
    show_readiness: false

If more than one location is configured, set the summary sensor explicitly:

    type: custom:australian-fire-watch-card
    entity: sensor.australian_fire_watch_home_status

The map is Home Assistant's standard map card. It uses default_zoom: 11,
auto_fit: false, and fit_zones: false; this avoids a distant statewide incident
pulling the local view away from the monitored zone.

The bundled dashboard strategy is also available:

    strategy:
      type: custom:australian-fire-watch

## Jurisdictions and official data

Australian emergency data is published separately by each jurisdiction, so
there is no single national incident schema. Australian Fire Watch uses an
explicit adapter for each documented public product:

| Jurisdiction | Publisher and product |
| --- | --- |
| ACT | ACT Emergency Services Agency CAP incidents |
| NSW | NSW RFS CAP-AU, Current Incidents GeoJSON, IncidentAlerts, and fire-danger/Total Fire Ban products; optional BOM NSW context |
| NT | NT Police, Fire and Emergency Services incident-map JSON |
| Queensland | Queensland Fire Department ESCAD current-incidents GeoJSON |
| South Australia | SA Country Fire Service Alert SA fire CAP feed |
| Tasmania | Tasmania Fire Service bushfire and alert KML |
| Victoria | Emergency Management Victoria public events GeoJSON |
| Western Australia | Emergency WA's designated public incident and warning RSS feeds |

Every adapter filters for bush, grass, vegetation, or wildfire activity and
explicit planned burns. Structure, vehicle, and building fires are excluded.
The upstream record's warning and control fields are never conflated.

Emergency WA permits automated access only to its designated RSS, CAP-AU, and
SLIP feeds, with no more than one request per feed every five minutes. Australian
Fire Watch uses the official all-regions incident and warning RSS links exposed
on Emergency WA's About page, and its five-minute coordinator interval observes
that limit. It does not use undocumented Emergency WA API endpoints.

Tasmania uses the public TFS KML products. Australian Fire Watch does not scrape
TasALERT or use feeds for which the publisher requires prior permission.

## NSW fire-danger enrichment

The national release preserves the mature NSW pipeline:

- NSW RFS is the source of truth for current warning levels, fire-danger
  ratings, and Total Fire Bans.
- BOM products add optional fire-weather and Fire Behaviour Index context.
- CAP and GeoJSON snapshots are cross-checked before missing incidents can move
  toward resolved.

Fire-danger enrichment for other jurisdictions is intentionally shown as
**Unknown / unavailable** in this release. Users must consult the official state
or territory source. Unknown never becomes No Rating.

## Notifications

Enter one or more fully-qualified notify.* services in the integration options.
Direct notification delivery, mobile acknowledgement and snooze actions, and
safe test alerts are built into the integration; a separate automation is not
required.
Notifications are raised only for meaningful lifecycle changes such as newly
qualifying incidents, escalation, de-escalation, leaving the monitored radius,
or resolution after healthy snapshots.

Emergency Warning updates cannot be silenced by acknowledgement or snooze.
Android and iOS notification priorities are derived from the official warning
level. Test alerts are clearly labelled and never use the critical path.

An optional blueprint for users who want to own the alert automation is available
at `blueprints/automation/hallyaus/australian_fire_watch_assigned_alerts.yaml`.

Its event and mobile-action names use the `AUSTRALIAN_FIRE_WATCH_*` prefix.

## Configuration

UI setup is recommended. YAML import is also supported:

    australian_fire_watch:
      name: Home
      zone: zone.home
      jurisdiction: NSW
      fire_danger_district: Greater Sydney Region
      monitor_radius_km: 150
      emergency_radius_km: 100
      watch_radius_km: 50
      advice_radius_km: 20
      unclassified_fire_radius_km: 10
      stale_after_minutes: 45
      enable_bom_enrichment: true

For non-NSW entries, omit fire_danger_district; NSW-only enrichment is
automatically disabled regardless of the checkbox.

## Migration from a legacy RFS dashboard

1. Install Australian Fire Watch and configure the same zone.
2. Confirm the summary, feed-health, and mapped incident entities update.
3. Test the bundled dashboard and notification path.
4. Disable old real-time RFS alert automations to prevent duplicate notices.
5. Keep old entities for comparison until at least one healthy refresh cycle.
6. Remove legacy dashboards and integrations only after the new path is proven.

## Recovery and rollback

If a release fails:

1. Keep official emergency channels enabled and use them as the source of truth.
2. In HACS, redownload the previous release.
3. Restart Home Assistant.
4. If necessary, disable the config entry under **Settings → Devices & services**.

Removing the integration stops its entities, panel, services, and notifications;
it does not remove Home Assistant zones or readiness helpers.

## Development and validation

    python -m unittest discover -s tests -v
    python -m compileall custom_components tests

Before restarting a live instance, run Home Assistant's configuration check.
Tests cover feed parsing, lifecycle safety, native-map packaging, JSON/YAML
validity, and rejection of private Home Assistant state.

## Data sources and attribution

All feed content remains owned by its publisher and is fetched directly by each
Home Assistant instance. Official URLs and attribution are exposed on the
integration's feed-health data and dashboard. See THIRD_PARTY_NOTICES.md for
publisher and licensing notes.

## Licence

Project code is released under the MIT License. Official feed content and
publisher branding are not covered by the project's licence.
