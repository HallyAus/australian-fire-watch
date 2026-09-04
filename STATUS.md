# Australian Fire Watch status

## 0.2.1 national release

- Prevented YAML import from racing an existing pre-v2 config-entry migration
  and creating a duplicate monitored location during upgrade.

## 0.2.0 national release candidate

- HACS install and technical nsw_fire_watch domain remain backward compatible.
- Config flow supports ACT, NSW, NT, Queensland, South Australia, Tasmania,
  Victoria, and Western Australia.
- Jurisdiction-specific CAP, GeoJSON, JSON, KML, and GeoRSS adapters normalise
  official incident records into one safety model.
- The integration-owned sidebar dashboard, Lovelace card, and dashboard strategy
  remain bundled with the integration.
- The interim MapLibre/OpenFreeMap renderer and vendor assets have been removed.
  The dashboard now creates Home Assistant's native map card.
- Existing NSW RFS cross-checking and NSW/BOM fire-danger enrichment remain.
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
