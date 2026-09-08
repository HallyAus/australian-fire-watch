# Australian Fire Watch status

## 1.3.1 visible cameras and compact-card tidy-up

- Show Watchtowers camera sites and branded VIEW buttons immediately in both
  card layouts and incident cards, without a dropdown.
- Replace the compact card's blue BOM image strip with a readable source link
  in the footer, preserving attribution.
- Tighten camera-section spacing and explanatory text, align site information
  with the VIEW button on larger screens, and correct the singular site count.
- Local validation: 87 Python unit tests and 10 frontend tests pass; Python
  compilation, undefined-name lint, JavaScript syntax and JSON/YAML syntax pass.
  A supplementary mypy run reports 26 typing errors in four unchanged backend
  files, identical to the pre-change main revision; this UI patch does not
  resolve those existing findings.

## 1.3.0 Central Watch camera links

- Link current incidents to up to three nearby camera sites using the supplied
  25 views at 16 NSW/ACT locations, grouped by site and matched across borders.
- Add a configurable 1–30 km camera radius (default 30) and an option to disable
  camera links. The nearby-sites browser uses the dashboard monitoring radius.
- Include camera links in full/compact dashboards and current incident
  notifications, retaining official-source access and notification urgency.
- Adapt the supplied Central Watch logo into one branded VIEW button per site
  and retain the Watchtowers Networks attribution logo.
- Omit empty optional incident fields from the dashboard summary to keep camera
  context within HA's history-storage budget; event payloads retain those fields.
- Camera distance is supplementary context, not a visibility or online-status
  assessment. No incident API, stream embedding, scraping or camera polling.

## 1.2.1 original-card startup and recovery

- Register the bundled frontend during integration setup, before any external
  feed refresh. A slow or failed first refresh cannot defer card registration.
- Register and version the integration-owned Lovelace module automatically in
  storage mode; preserve unrelated resources and user-owned YAML resource lists.
- Retry a still-missing original card when returning to the dashboard, resuming
  the app or reconnecting. Recovery is bounded and targets only this card's
  missing-element error, never unrelated configuration errors.
- Keep the original card layout, map, warning semantics and notifications intact.
- Add startup/resource lifecycle and browser-event regression tests.

## 1.2.0 event-map and branding refresh

- Native Home Assistant map markers now use different icons for bush or
  vegetation fire, grass fire, planned burns, other fire, and unknown records.
- Official warning severity takes priority over marker colour. Known planned
  work is green only when no warning applies; unknown warnings remain slate.
- The full and compact map layouts use supported Home Assistant aspect ratios so
  markers are not clipped below the dashboard frame.
- The Australia-and-flame logo, synthetic desktop/mobile dashboard screenshots,
  and phone-notification preview replace the previous presentation assets.

## 1.1.0 cross-border coverage

- Select every state or territory covered by the monitoring radius. Most people
  need one jurisdiction; border communities may need two or more.
- One set of monitoring and alert radii is applied across jurisdiction borders.
- Partial failure in any selected jurisdiction prevents a false confirmed-clear
  state while healthy feeds can still raise or escalate a current warning.
- Existing 1.0.x single-jurisdiction config entries migrate automatically.
- The bundled dashboard links every selected official publisher.

## 1.0.1 reliability fixes

- Warning entity availability is separate from a valid no-warning assessment.
- Valid current feeds can add/escalate independently; missing/de-escalating
  records require complete source coverage.
- HTTP response bodies and validators are cached only after product validation.
- Notifications use an atomic lifecycle/outbox transaction, per-recipient retries,
  stable tags, bounded backoff, expiry and delivery-health diagnostics.
- NSW declarations retain their source calendar dates across midnight and outages.
- Published warning polygons (including holes) determine spatial alert relevance.
- NSW uses the common bushfire-only filtering policy after raw feed validation.
- Regression coverage includes actual Home Assistant setup, reload, unload,
  entity availability, failover and persistence failure paths.

## 1.0.0 national launch

- The public repository is `HallyAus/australian-fire-watch` and the Home
  Assistant domain is `australian_fire_watch`.
- Config flow supports ACT, NSW, NT, Queensland, South Australia, Tasmania,
  Victoria, and Western Australia.
- Jurisdiction-specific CAP, GeoJSON, JSON, KML, and GeoRSS adapters normalise
  official incident records into one safety model.
- The integration-owned sidebar dashboard, Lovelace card, and dashboard strategy
  ship inside the integration and use Home Assistant's native map card.
- NSW RFS cross-checking and NSW/BOM fire-danger enrichment are included.
- Non-NSW fire-danger enrichment is explicitly unavailable rather than inferred.
- Malformed, stale, or missing data never becomes a safe state.

## Publisher caveats

- Western Australia uses the all-regions incident and warning RSS feeds that
  Emergency WA designates on its About page. The coordinator's five-minute
  interval observes the publisher's stated automated-access limit.
- Tasmania uses the public TFS KML products, not permission-gated TasALERT feeds.
- Official schemas can change without notice; parser and live-feed validation is
  required before each release.

## Release validation

- Python unit and packaging tests.
- Python byte-code compilation.
- JavaScript syntax check.
- JSON and YAML parsing with duplicate-key rejection.
- Live official-feed parser smoke tests.
- Home Assistant configuration check before restart or rollout.
