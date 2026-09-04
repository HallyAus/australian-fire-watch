# Third-party notices

Australian Fire Watch project code is MIT-licensed. Government feed content,
publisher names, and publisher branding remain subject to their owners' terms.

## Home Assistant native map

The dashboard uses Home Assistant's built-in map card and does not redistribute
a mapping engine, tile style, or tile data. Map rendering, attribution, and
provider selection are controlled by the user's Home Assistant version.

## Official emergency-service feeds

Each Home Assistant instance retrieves public publisher products directly:

- ACT Emergency Services Agency CAP data, published under CC BY 4.0.
- NSW Rural Fire Service CAP, GeoJSON, IncidentAlerts, and fire-danger products.
- NT Police, Fire and Emergency Services public incident-map data.
- Queensland Fire Department public ESCAD incident data.
- South Australian Country Fire Service Alert SA fire CAP data.
- Tasmania Fire Service bushfire and alert KML.
- Emergency Management Victoria public events GeoJSON.
- Department of Fire and Emergency Services WA designated incident and warning RSS.

The dashboard exposes the selected publisher's official page and attribution.
No feed content is bundled in a release.

## Bureau of Meteorology

Optional NSW enrichment fetches Bureau of Meteorology public products directly.
The existing unmodified Bureau attribution image remains embedded in the
frontend so attribution is available through local and remote Home Assistant
access.

## Access safeguards

Polling is no more frequent than five minutes. Conditional requests, response
size limits, timeouts, exponential backoff, and last-known-good retention reduce
publisher load. Malformed or unexpected responses fail closed.

Emergency WA's designated RSS endpoints are used instead of undocumented APIs,
and are polled no more frequently than the publisher's five-minute limit.
TasALERT feeds that require publisher permission are not used.
