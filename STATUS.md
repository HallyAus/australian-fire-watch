# Australian Fire Watch status

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
