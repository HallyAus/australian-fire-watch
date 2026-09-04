# Australian Fire Watch status

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
