# Third-party notices

NSW Fire Watch is MIT-licensed, but the following bundled software, imagery,
and fetched data retain their own terms.

## MapLibre GL JS

The `maplibre-gl-csp.js`, `maplibre-gl-csp-worker.js`, and `maplibre-gl.css`
files under `custom_components/nsw_fire_watch/frontend/vendor/` are from
MapLibre GL JS 5.24.0 and are redistributed under its BSD 3-Clause licence. The
matching CSP worker is loaded from the same Home Assistant origin. The complete
upstream licence is included as `frontend/vendor/MAPLIBRE-LICENSE.txt`.

- Project: <https://maplibre.org/maplibre-gl-js/>
- Source package: <https://www.npmjs.com/package/maplibre-gl/v/5.24.0>

## OpenFreeMap and OpenStreetMap data

The incident map uses the keyless OpenFreeMap public vector-tile service and
its Liberty style. No OpenFreeMap account or API key is bundled or required.
OpenFreeMap requires attribution; the frontend renders permanent OpenFreeMap,
OpenMapTiles, and OpenStreetMap credits directly beneath every map. Map data is
from OpenStreetMap and is subject to the Open Database Licence and related
attribution requirements. The public service has no project-level service
guarantee, so NSW Fire Watch keeps fire status and incident lists independent
of the map and shows an official-source fallback if it cannot load.

- OpenFreeMap: <https://openfreemap.org/>
- OpenMapTiles: <https://openmaptiles.org/>
- OpenStreetMap copyright: <https://www.openstreetmap.org/copyright>

## Bureau of Meteorology attribution image

The frontend embeds the Bureau of Meteorology's unmodified website-footer
attribution image for display only when direct Bureau FBI or warning data is
shown. It is not covered by this repository's MIT licence and is not project
branding. The image links to the Bureau's required attribution information.

- Bureau attribution policy: <http://www.bom.gov.au/data-access/3rd-party-attribution.shtml>
- Bureau copyright: <https://www.bom.gov.au/copyright>

## NSW Rural Fire Service and Bureau data

Official NSW RFS and Bureau feed content is fetched by each user's Home
Assistant installation and is not redistributed in this repository. See the
README's data-source and attribution section for the applicable notices and
limitations.
