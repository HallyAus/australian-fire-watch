# Australian Fire Watch — Queensland fire data API discovery and implementation handover

> **Status:** Core data-source discovery / read-only proof of concept complete; production hardening and integration implementation outstanding.  
> **Investigation date:** 28 October 2026 (Australia/Brisbane).  
> **Repository:** [HallyAus/australian-fire-watch](https://github.com/HallyAus/australian-fire-watch)  
> **Suggested repository location:** `docs/qld-fire-data-api-discovery.md`  
> **Scope:** Queensland fire danger ratings, local fire bans, and State of Fire Emergency. Existing Queensland incident feeds are out of scope.

## 1. Executive summary / new-chat context

Australian Fire Watch already supports Queensland incident and warning monitoring, but the repository's documented fire-danger, fire-ban, FBI and BOM enrichment pipeline is NSW-specific. We investigated public datasets behind the Queensland Fire Department (QFD, legacy QFES naming) maps to provide Queensland-specific enrichment without HTML scraping.

**Three ArcGIS FeatureServer layers have now been discovered via the published official QFD ArcGIS Experience configurations, and successfully queried without authentication:**

1. **Fire danger / four-day forecast** — `BOM_Fire_Danger_Ratings_Public_View_/FeatureServer/0`.
2. **Local fire bans for all LGAs** — `LGAs_Firebans_Public_View/FeatureServer/0` (plus a separate active-ban-only view).
3. **State of Fire Emergency by LGA** — `StateOfEmergency_View/FeatureServer/0`.

A **point-in-polygon lookup using Brisbane CBD coordinates** returned one matching record from each of the three principal layers. The fire-danger records included four ratings **with explicit matching calendar dates**. Their record timestamp matched a fresh update on the morning of 28 October 2026 AEST. Local ban and State of Fire Emergency layers returned explicit negative statuses; **positive declarations, partial-LGA restrictions, and reliable feed-freshness semantics are NOT yet proven**.

**Recommended decision:** Proceed with a Queensland-specific *read-only provider implementation* using the direct ArcGIS layers and Home Assistant's existing asynchronous integration/coordinator architecture. Do not claim production readiness, or treat a missing/stale status as “no ban,” until remaining acceptance criteria are met.

### Current technical readiness

| Capability | Evidence / current state | Readiness |
|---|---|---|
| Public API discovery | URLs extracted from official ArcGIS Experience configs | Confirmed |
| Anonymous JSON queries | Live tests returned `error: null` | Confirmed |
| Coordinate-to-district lookup | Brisbane CBD -> `Southeast Coast`, one record | Confirmed |
| Fire danger today + next 3 days | Four ratings, four date fields, source timestamp | Confirmed at test time |
| Queensland local fire ban | Brisbane CBD -> `Brisbane City`, `No Fire Ban` | Negative case confirmed |
| State of Fire Emergency | Brisbane CBD -> `BRISBANE CITY`, `No` | Negative case confirmed |
| Active-ban filtered view | Filter `HASFIREBAN = 'Fire Ban'`, count 0 | Filter confirmed; no positive samples |
| State-of-emergency positive status | `Yes` inferred from `No` convention, not observed | Unverified |
| Partial-LGA application | Polygon queries possible, but boundaries semantics unknown | Unverified |
| Fire ban source refresh semantics | Data edit dates/record timestamps differ from processing dates | Unverified |
| Fire Behaviour Index (FBI) | No FBI field in discovered FDR layer | Not sourced |
| Data reuse/licensing for direct ArcGIS layers | Must review public QFD/ArcGIS terms | Unverified |

## 2. Original application discovery

### Fire bans

Official QFD page: <https://www.fire.qld.gov.au/safety-education/using-fire-outdoors/fire-bans-and-restrictions>

QFD's public web app:
<https://experience.arcgis.com/experience/fdd90c941e51441eb768c2ed3fe12d41?org=publicsafetyqld>

ArcGIS Experience item ID: `fdd90c941e51441eb768c2ed3fe12d41`  
Application metadata title: **QFES Fire Bans**  
Owner: `PublicSafetyQld_Data`  
Type: `Web Experience`  
Its public resources include `config/config.json`; its *published* configuration was downloaded via the item `/data?f=json` endpoint.

Published configuration `dataSources` returned:

| Data source | Type | Item ID | URL / role |
|---|---|---|---|
| `dataSource_8` | `WEB_MAP` | `d829169f8b4247caa7539db1060e863c` | Web map |
| `dataSource_9` | `FEATURE_SERVICE` | `1a2a050fc8f340f8ba53b4a89f4db676` | Active fire-ban view |

The published configuration referenced these layers:

```text
https://services1.arcgis.com/vkTwD8kHw2woKBqV/arcgis/rest/services/LGAs_Firebans_Public_View/FeatureServer/0
https://services1.arcgis.com/vkTwD8kHw2woKBqV/arcgis/rest/services/LGAs_Firebans_With_Firebans_Public_View/FeatureServer/0
https://services1.arcgis.com/vkTwD8kHw2woKBqV/arcgis/rest/services/StateOfEmergency_View/FeatureServer/0
```

### Fire danger ratings

Official QFD page: <https://www.fire.qld.gov.au/prepare/bushfire/fire-danger-ratings>

QFD ArcGIS Experience:
<https://experience.arcgis.com/experience/053770d3874a424baf8f34ecc5aaf169>

ArcGIS Experience ID: `053770d3874a424baf8f34ecc5aaf169`  
The published configuration referenced Web Map item `f3fefe922222432eaa19588288672c28` in `dataSource_5` through `dataSource_8` and included this layer:

```text
https://services1.arcgis.com/vkTwD8kHw2woKBqV/arcgis/rest/services/BOM_Fire_Danger_Ratings_Public_View_/FeatureServer/0
```

### How to repeat configuration discovery

```bash
APP_ID="fdd90c941e51441eb768c2ed3fe12d41"  # Or the FDR Experience ID
BASE="https://www.arcgis.com/sharing/rest/content/items/$APP_ID"

curl -fsSL "$BASE/data?f=json" -o app-config.json
jq '(.dataSources // {}) | to_entries |
    map({id: .key, type: .value.type, itemId: .value.itemId, url: .value.url})' \
  app-config.json

jq -r '.. | objects | .url? // empty
       | select(type == "string")
       | select(test("FeatureServer|MapServer"; "i"))' \
  app-config.json | sort -u
```

The configuration proves these services are **referenced by the published QFD application**. This is not, by itself, a contractual availability guarantee, refresh SLA, or direct endorsement of third-party reuse.

## 3. Direct ArcGIS layer contracts

Common URL prefix:

```text
https://services1.arcgis.com/vkTwD8kHw2woKBqV/arcgis/rest/services/
```

All inspected layers reported `type: Feature Layer`, `capabilities: Query`, `geometryType: esriGeometryPolygon`, `maxRecordCount: 2000`, and `isView: true`. The three core services each supported anonymous querying in the investigation. Geometry may be omitted using `returnGeometry=false`.

### 3.1 Queensland fire danger ratings

**Service:**

```text
BOM_Fire_Danger_Ratings_Public_View_/FeatureServer/0
```

**Fields observed in layer metadata:**

| API field | Purpose / interpretation |
|---|---|
| `OBJECTID` | ArcGIS record key |
| `Area_Name` | Fire weather district / forecast area |
| `Day1` ... `Day4` | Fire danger classification for each respective date |
| `Date1` ... `Date4` | ArcGIS epoch-millisecond dates matching each `DayN` |
| `FMETimeStamp` | ArcGIS epoch-millisecond record/source timestamp; exact upstream semantics still worth validating |
| `Shape__Area`, `Shape__Length` | Geometry metadata; not required for status sensors |

**Brisbane CBD spatial test:** longitude `153.0251`, latitude `-27.4698` (PUBLIC test point, **not** a private home address). Query returned **one** result: `Area_Name = "Southeast Coast"`.

| Forecast field | Date (AEST) | Rating |
|---|---|---|
| `Day1` / `Date1` | Wed 28 Oct 2026 | `Moderate` |
| `Day2` / `Date2` | Thu 29 Oct 2026 | `Moderate` |
| `Day3` / `Date3` | Fri 30 Oct 2026 | `Moderate` |
| `Day4` / `Date4` | Sat 31 Oct 2026 | `No Rating` |

Record `FMETimeStamp`: `2026-10-27T22:02:13Z` = **28 Oct 2026, 08:02:13 AEST**.  
Layer `editingInfo.dataLastEditDate` at test time: `2026-10-27T22:02:15Z` (approximately two seconds later). This supports the data having been recently processed **at the time of the test**; no guaranteed update interval has been established.

Raw date fields and conversions:

| Field | Epoch ms | UTC timestamp | AEST date |
|---|---:|---|---|
| `Date1` | `1793109600000` | 2026-10-27 14:00 UTC | 28 Oct |
| `Date2` | `1793196000000` | 2026-10-28 14:00 UTC | 29 Oct |
| `Date3` | `1793282400000` | 2026-10-29 14:00 UTC | 30 Oct |
| `Date4` | `1793368800000` | 2026-10-30 14:00 UTC | 31 Oct |

**Interpretation rule:** Match a requested day using the corresponding `DateN` **converted to `Australia/Brisbane`**, not by assuming `Day1` is always today. The feed may cross midnight or update during the morning. `No Rating` is a valid rating and must not be treated as null, failure, or unavailable. Use the current AFDRS rating vocabulary (`No Rating`, `Moderate`, `High`, `Extreme`, `Catastrophic`) while logging rather than silently accepting unrecognised values; legacy renderers may contain older labels.

**Reproducible query:**

```bash
BASE="https://services1.arcgis.com/vkTwD8kHw2woKBqV/arcgis/rest/services"
LAYER="$BASE/BOM_Fire_Danger_Ratings_Public_View_/FeatureServer/0"

curl -fsS -G "$LAYER/query" \
  --data-urlencode 'geometry=153.0251,-27.4698' \
  --data-urlencode 'geometryType=esriGeometryPoint' \
  --data-urlencode 'inSR=4326' \
  --data-urlencode 'spatialRel=esriSpatialRelIntersects' \
  --data-urlencode 'where=1=1' \
  --data-urlencode 'outFields=Area_Name,Day1,Day2,Day3,Day4,Date1,Date2,Date3,Date4,FMETimeStamp' \
  --data-urlencode 'returnGeometry=false' \
  --data-urlencode 'f=json' | jq '.error, [.features[]?.attributes]'
```

### 3.2 Local Fire Ban — all council records

**Service:**

```text
LGAs_Firebans_Public_View/FeatureServer/0
```

Layer fields: `OBJECTID`, `SHIRE_NAME`, `DATE_FROM`, `DATE_TO`, `HASFIREBAN`, `FMETimestamp`, `Link`.

- `SHIRE_NAME`: local government area name.
- `HASFIREBAN`: observed status `No Fire Ban`; separate active-only view proves the literal positive filter value `Fire Ban`.
- `DATE_FROM`, `DATE_TO`: epoch-millisecond dates when present; absent in all 78 records seen during the investigation.
- `FMETimestamp`: often null or old; **not an established global freshness signal**.
- `Link`: optional related URL; null in observed records.

**All-record query at investigation time:** `count = 78`, with 78 records reporting `HASFIREBAN = "No Fire Ban"`.  
**Brisbane CBD spatial query:** exactly one result:

```json
{
  "OBJECTID": 76,
  "SHIRE_NAME": "Brisbane City",
  "DATE_FROM": null,
  "DATE_TO": null,
  "HASFIREBAN": "No Fire Ban",
  "FMETimestamp": 1761602294510,
  "Link": null
}
```

`FMETimestamp = 1761602294510` converts to **2025-10-27T21:58:14.510Z / 2025-10-28 07:58:14.510 AEST**. This is approximately one year before the investigation and **must not be mistaken for a recent poll timestamp**.

Service metadata at test time:

- `dataLastEditDate = 1791583288628` = **2026-10-10 08:01:28.628 AEST**.
- `lastEditDate = 1792711775214` = **2026-10-23 09:29:35.214 AEST**.

These dates describe ArcGIS edits, **not necessarily the last completed upstream status validation**.

### 3.3 Local Fire Ban — active-only view

**Service:**

```text
LGAs_Firebans_With_Firebans_Public_View/FeatureServer/0
```

Metadata showed:

```json
{
  "isView": true,
  "viewDefinitionQuery": "HASFIREBAN = 'Fire Ban'"
}
```

`returnCountOnly=true` returned `count: 0`; the feature query returned `features: []`, `error: null`. **This specifically proves the view's filtering expression and that it contained no active records at test time.** It is not a basis for inferring that a missing or failing general-layer response means “no ban.”

### 3.4 State of Fire Emergency

**Service:**

```text
StateOfEmergency_View/FeatureServer/0
```

Fields: `OBJECTID`, `LGA_Name`, `LGA_code`, `InStateOfEmergency`, `Shape__Area`, `Shape__Length`.

**All-record query at investigation time:** 78 records; all returned `InStateOfEmergency = "No"`.  
**Brisbane CBD spatial test:** exactly one result:

```json
{
  "OBJECTID": 219,
  "LGA_Name": "BRISBANE CITY",
  "LGA_code": "1000",
  "InStateOfEmergency": "No",
  "Shape__Area": 0.12346936408448528,
  "Shape__Length": 3.6812681657856881
}
```

**Candidate positive mapping:** `Yes` -> `on`, `No` -> `off`. Only `No` has been observed; confirm real positive values before production release. There were **no effective/expiry-date fields** on this layer.

Service metadata at test time:

- `dataLastEditDate = 1792663495197` = **2026-10-22 20:04:55.197 AEST**.
- `lastEditDate = 1792711540118` = **2026-10-23 09:25:40.118 AEST**.

## 4. Open-data aggregator cross-check

A secondary dataset was tested via **Queensland Opendatasoft**:

```text
https://queensland.opendatasoft.com/api/explore/v2.1/catalog/datasets/fire-bans-queensland
https://queensland.opendatasoft.com/api/explore/v2.1/catalog/datasets/fire-bans-queensland/records
```

At the time of investigation, metadata reported:

- `dataset_id: fire-bans-queensland`, `dataset_uid: da_ym4tr2`.
- Publisher listed as **Queensland Fire Department**, with the QFD fire-ban page as a reference.
- Licence listed as **CC BY 4.0** (for this dataset; **do not assume this automatically establishes separate direct ArcGIS reuse rights**).
- `records_count: 78`.
- Metadata `modified` / `data_processed: 2026-10-27T17:06:16+00:00` (**28 Oct 2026, 03:06:16 AEST**).
- Fields included `shire_name`, `hasfireban`, `firebantoday`, `date_from`, `date_to`, `fmetimestamp`, `link`, `geo_shape`, `geo_point_2d`.
- `update_frequency` was `null`.

A `limit=100` fields-only query returned:

| Check | Result |
|---|---|
| Total records | 78 |
| `hasfireban` | `No Fire Ban` for all 78 |
| `firebantoday` | `No Fire Ban` for all 78 |
| Duplicate council names | None found in query |
| Differences between the two status fields | None found |
| Missing `fmetimestamp` | 27 / 78 |
| Oldest non-null `fmetimestamp` | `2025-10-04T02:53:20.254Z` |
| Newest non-null `fmetimestamp` | `2026-10-10T00:01:09.800Z` |
| Records with non-null `date_from` or `date_to` | 0 |

Brisbane City returned `No Fire Ban` with null dates, but **the aggregator's Brisbane `fmetimestamp` was `2025-10-27T22:58:14.510Z` while the direct ArcGIS integer value converts to `2025-10-27T21:58:14.510Z`** — a **one-hour inconsistency**. Cause unknown (potential datetime conversion issue); explicitly test timestamp semantics before using the aggregator for validation or diagnostics.

**Decision:** Prefer direct published ArcGIS layers referenced by the official map. Retain Opendatasoft as an optional independent comparison, not the primary dependency, until provenance, update cadence, and timestamp conversion are understood. A new `modified` timestamp on an aggregator can mean data processing and does **not**, by itself, prove fresh field values.

Example secondary API call:

```bash
BASE='https://queensland.opendatasoft.com/api/explore/v2.1/catalog/datasets/fire-bans-queensland'
curl -fsS -G "$BASE/records" \
  --data-urlencode 'limit=100' \
  --data-urlencode 'select=shire_name,hasfireban,firebantoday,date_from,date_to,fmetimestamp,link' \
  | jq '{total_count, brisbane: [.results[] | select(.shire_name == "Brisbane City")]}'
```

## 5. Tested spatial-query contract

All three primary services successfully accepted the following ArcGIS point query parameters using **Brisbane CBD only as a public sample**:

```text
geometry=153.0251,-27.4698
geometryType=esriGeometryPoint
inSR=4326
spatialRel=esriSpatialRelIntersects
where=1=1
returnGeometry=false
f=json
```

**Coordinate order:** ArcGIS simple point syntax is **longitude,latitude** (`x,y`), not latitude,longitude. Home Assistant typically provides latitude and longitude separately; construct requests accordingly.

**Reproducible end-to-end test:**

```bash
#!/usr/bin/env bash
set -euo pipefail

BASE='https://services1.arcgis.com/vkTwD8kHw2woKBqV/arcgis/rest/services'
LON='153.0251'  # Brisbane CBD sample only
LAT='-27.4698'

for SERVICE in \
    'BOM_Fire_Danger_Ratings_Public_View_' \
    'LGAs_Firebans_Public_View' \
    'LGAs_Firebans_With_Firebans_Public_View' \
    'StateOfEmergency_View'; do
  echo "========== $SERVICE =========="
  URL="$BASE/$SERVICE/FeatureServer/0/query"
  curl --fail --silent --show-error --get "$URL" \
    --data-urlencode "geometry=$LON,$LAT" \
    --data-urlencode 'geometryType=esriGeometryPoint' \
    --data-urlencode 'inSR=4326' \
    --data-urlencode 'spatialRel=esriSpatialRelIntersects' \
    --data-urlencode 'where=1=1' \
    --data-urlencode 'outFields=*' \
    --data-urlencode 'returnGeometry=false' \
    --data-urlencode 'f=json' \
    | jq '{error, count: (.features // [] | length), records: [.features[]?.attributes]}'
done
```

Note: for an active-only layer, zero features when no ban exists is expected. For the **general LGA** and **danger** layers, zero or multiple point matches requires explicit handling (boundary gaps, overlaps, invalid coordinates, or source changes), not automatic safe status.

## 6. Proposed Home Assistant integration design (not implemented)

**Integration domain:** `australian_fire_watch`.  
**Relevant repository root:** `custom_components/australian_fire_watch/`.  
The published repository README identifies version 1.4.1 and states that NSW enrichment is implemented; the repository includes its own `AGENTS.md` contributor/safety instructions. Review the current checked-out tree before making file-specific changes. Do not assume the architecture on `main` has stayed identical since this investigation.

### 6.1 Provider design

Add a **Queensland-specific enrichment provider** alongside existing jurisdiction/incident handling, not a separate Home Assistant custom integration:

```text
Monitored location (configured latitude, longitude)
    |
    v
Queensland ArcGIS enrichment provider (async HTTP)
    |---- FDR FeatureServer/0: district, four date/rating pairs, source time
    |---- LGA Firebans FeatureServer/0: ban state, LGA, dates, source time
    |---- StateOfEmergency FeatureServer/0: emergency state, LGA
    |
    v
Normalized jurisdiction enrichment snapshot
    |
    v
Australian Fire Watch coordinator / entity platform / frontend
```

Implementation principles:

1. Use Home Assistant's shared `aiohttp` client session (e.g. `async_get_clientsession(hass)`), asynchronous non-blocking requests, sensible connect/read timeouts, and limited, bounded retries. No synchronous `requests` or filesystem calls in the event loop.
2. Parse and validate ArcGIS `error` objects even when HTTP status is `200`. Treat invalid JSON, missing features/fields, duplicate geography matches, and unrecognised statuses as source errors or unsupported data.
3. Reuse existing `DataUpdateCoordinator` and normalized-model patterns. Keep each QLD enrichment source's health independent so a missing emergency source does not make a valid danger forecast appear healthy/unhealthy by accident.
4. Query point geometry with `inSR=4326` and `returnGeometry=false`; do not download full state polygons for routine entity updates.
5. Date conversion: `datetime.fromtimestamp(ms / 1000, tz=ZoneInfo("Australia/Brisbane"))` (aware datetime); match date-specific forecasts by local date. Avoid manual +10 offsets in general utility functions.
6. Distinguish **poll success time**, **source record time**, **layer data last-edit time**, and **forecast validity date**. Do not infer successful upstream refresh from a null/unchanged `FMETimestamp`, nor automatically mark a dataset stale because a council's status did not change.
7. Implement a documented freshness policy after confirming the source refresh cadence; do not claim official data is current solely because an HTTP request succeeded.
8. Preserve unknown/unavailable/stale distinctly from known `off`, `No Fire Ban`, or `No Rating`. Never infer no restriction from a High/Extreme rating or from an empty active-ban-only view if the general-layer query is missing.
9. Check whether each returned geometry represents a full LGA vs a partial restricted area; legal applicability may require dedicated polygons, separate exceptions, or a formal coverage specification from QFD.
10. Retain source attribution and a link to the official QFD guidance. Clearly label the software as supplementary to official emergency services.

### 6.2 Preliminary normalized data contract

**Illustrative design, not a current class definition:**

```python
@dataclass(frozen=True)
class QldEnrichmentSnapshot:
    district: str | None
    forecast: tuple[tuple[date, str], ...]  # each is a dated FDR
    fdr_source_updated: datetime | None
    lga: str | None
    fire_ban: bool | None  # None == unknown/unavailable
    ban_start: datetime | None
    ban_end: datetime | None
    state_of_emergency: bool | None
    danger_health: str
    ban_health: str
    emergency_health: str
```

Avoid forcing a single combined availability flag. Represent independent source errors and stale ages appropriately; the model above is intentionally a sketch.

### 6.3 Entity proposal

| Entity function | Candidate HA representation | Notes |
|---|---|---|
| Today's fire danger | Existing danger sensor, correctly populated for QLD | Retain `No Rating` as valid |
| Tomorrow / next 3 days | Forecast sensor(s) or dated attributes, consistent with existing architecture | Prefer explicit dates |
| Local fire ban | `binary_sensor` | `on` only for verified `Fire Ban` |
| State of Fire Emergency | Separate `binary_sensor` | `No` observed; positive value untested |
| Fire weather district / LGA | Sensor attribute(s) or diagnostic sensor(s) | Geographic context |
| Ban start/end | Attributes or timestamp entities if present | No positive samples yet |
| Per-feed health and source timestamps | Diagnostic sensor / attributes | Must expose uncertainty |

Entity IDs and unique IDs should follow current integration registry conventions and remain stable across upgrades. Do **not** add the example above verbatim to YAML configuration; it represents intended runtime entities.

### 6.4 Preliminary status semantics

| Input | Interpretation | Safe mapping? |
|---|---|---|
| FDR `Moderate`, `High`, `Extreme`, `Catastrophic`, `No Rating` | Valid rating categories | Yes, after date/freshness validation |
| Fire-ban `HASFIREBAN = 'Fire Ban'` | Ban active | Yes, filter confirms literal value (positive row not yet tested) |
| Fire-ban `HASFIREBAN = 'No Fire Ban'` | No ban reported by matched row | Yes, if source and geometry are validated |
| Emergency `InStateOfEmergency = 'No'` | No emergency reported | Yes, if source and geometry are validated |
| Emergency `InStateOfEmergency = 'Yes'` | Presumed emergency active | **Unverified positive-case assumption** |
| Null, missing, unexpected, failed, or stale status | Unknown / unavailable | Never map to `off` |
| Empty active-only fire ban layer | No records in that filtered view at that moment | Not sufficient alone for all-clear |

## 7. Risks, gaps, and release gates

| ID | Priority | Required follow-up / acceptance criterion |
|---|---|---|
| QLD-01 | P0 | Find or safely reproduce a **positive fire ban** example. Validate `DATE_FROM`, `DATE_TO`, `Link`, status transitions, and cancellation/extension semantics. Do not fabricate active examples in live feeds. |
| QLD-02 | P0 | Confirm **partial-LGA restrictions** and which FeatureServer polygons actually represent enforceable restricted areas. Exercise point queries on known partial coverage. |
| QLD-03 | P0 | Confirm **currentness/freshness contract** for general ban and emergency views, including unchanging LGAs and source outages. Keep last-good values as historical only, not present all-clear. |
| QLD-04 | P0 | Test a real or documented **positive State of Fire Emergency** value and coverage logic; no dates exposed in observed schema. |
| QLD-05 | P0 | Validate zone mapping and date handling across district boundaries, midnight AEST, delayed update cycles, null fields, gaps and overlaps. |
| QLD-06 | P1 | Check direct ArcGIS service **terms of use, attribution, polling limits and change stability**; aggregator's CC BY 4.0 is separate. |
| QLD-07 | P1 | Determine the cause/implications of the **one-hour Opendatasoft vs ArcGIS Brisbane `fmetimestamp` discrepancy**. |
| QLD-08 | P1 | Integrate independent source health, error reporting, and dashboard behaviour; no stale or unknown source must appear green/safe. |
| QLD-09 | P1 | Write deterministic fixtures/tests for negative, positive (synthetic test fixture only), unknown, stale, time/date, and geographic edge cases. |
| QLD-10 | P2 | Investigate **Fire Behaviour Index** and any BOM warning products if those features are in scope. Current FDR layer provides ratings, not FBI. |

### Suggested implementation increments

1. **Provider skeleton and models:** asynchronous ArcGIS client, response validation, data models, and tests using captured negative-case fixtures.
2. **Fire-danger integration:** dynamic date-to-rating mapping, QLD district metadata, today's sensor, dated forecast and source health.
3. **Local-ban and emergency integration:** geographic point queries, independent binary sensors, strict status validation and diagnostics.
4. **Lifecycle and safety hardening:** source age, outages, status changes, cancellation/expiry, positive fixtures, partial-area restrictions, and source attribution.
5. **Dashboard + documentation + release validation:** card states, unknown-data treatment, examples, unit/HA tests, and contributor-required validation.

### Proposed definition of done (for a production-ready QLD release)

- [ ] The location resolves to exactly the correct fire weather district and legal ban coverage area, including partial-LGA cases.
- [ ] A valid QLD forecast has explicit Queensland dates and accepted AFDRS classifications.
- [ ] All three sources independently report successful polling, valid responses, and freshness diagnostics.
- [ ] Live positive-case data or authoritative fixtures confirm status and declaration-date semantics.
- [ ] Failed/stale/unmatched data is `unknown`/`unavailable` and never shown as safe.
- [ ] Sensible service request timeouts, retries, refresh intervals and source attribution are documented.
- [ ] Automated tests cover dates, parsing, geography, negative/positive/unknown states, outages, and source changes.
- [ ] Repository `AGENTS.md`, official Home Assistant development requirements, hassfest/config checks and release procedures have been followed.

## 8. Repository references and safety guidance

- Repository: <https://github.com/HallyAus/australian-fire-watch>
- Project contributor/safety guidance: <https://github.com/HallyAus/australian-fire-watch/blob/main/AGENTS.md>
- Home Assistant developer documentation: <https://developers.home-assistant.io/>
- Home Assistant integration quality scale: <https://developers.home-assistant.io/docs/core/integration-quality-scale/>
- ArcGIS Feature Service query reference: <https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service/>
- ArcGIS query features guide: <https://developers.arcgis.com/documentation/portal-and-data-services/data-services/feature-services/query-features/>

The repository specifically requires separation of official warning level, incident status, type, proximity, and feed health; treats unknown/stale as never safe; retains official links and timestamps; and uses deterministic tests. Its public contributor guide also specifies its development/release workflow — consult it before pushing or publishing. **This handover has not changed the repository or installed Home Assistant instance.**

## 9. Quick-start prompt for a new ChatGPT development session

> I am extending `HallyAus/australian-fire-watch` to implement Queensland fire danger, local fire ban and State of Fire Emergency enrichment in Home Assistant. Read the attached `QLD_Fire_Data_API_Discovery_and_Implementation_Handover.md`, inspect the current repository and `AGENTS.md`, and use the confirmed ArcGIS service contracts documented there. Implement the QLD provider incrementally, with async Home Assistant-native networking, dated 4-day FDR forecasts, location-based queries, separate source health, and strict unknown/stale handling. Do **not** assume positive emergency or partial-LGA semantics have been validated. Start by assessing the existing coordinator/models/entity interfaces and proposing precise modifications and tests.

## 10. Evidence boundaries / chronology

All API discovery, metadata, response bodies, record counts, district labels, sample values and timestamps in sections 2–5 came from **commands run by the user and their pasted terminal outputs during the 28 October 2026 AEST investigation**. They are point-in-time observations, not guaranteed current beyond that test. The design, proposed entity contract, priorities and recommended acceptance tests in sections 6–9 are **implementation recommendations**, not observed features of the current codebase.

No positive fire ban or emergency record was observed during the investigation, and no code was committed. Discovery of a working public endpoint alone does not guarantee authoritative legal coverage or operational reliability.
