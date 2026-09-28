# Station coordinates and data quality

The assessment CSV has **8,151 rows, 6,738 unique OPIS truckstop IDs, and no latitude/longitude columns**. Of those IDs, **6,626 are in US states** and 112 are Canadian. Almost every address is a highway/interchange description rather than a numbered street address. Treating a city centre or geocoded highway exit as a station would introduce false locations.

The supplied `station_coordinates.csv` contains **1,094 matched US stations across 43 states** as of 2026-09-28. **5,532 US stations remain unresolved**. The application imports all US stations but only stations with supplied coordinates can enter fuel planning. This is partial coverage: the cheapest station in the complete assessment dataset may be among the unresolved records. Optimization results are therefore conditional on the available coordinate coverage.

## Matching rules

The preparation script uses factual location records from the official [Pilot/Flying J locator](https://locations.pilotflyingj.com/search) and [OpenStreetMap](https://www.openstreetmap.org/copyright). It makes no network calls during a route request.

| Match method | Stations | Rule |
| --- | ---: | --- |
| Official Pilot/Flying J locator | 593 | Exact store number, city, and state; use the site's routable/geocoded/display coordinate, never its separate city coordinate. |
| OSM chain and store reference | 359 | Exact chain plus store number, read from an OSM reference/name or a recognised official store URL; any supplied city/state must agree. |
| OSM unique chain, city, and state | 142 | Exactly one assessment OPIS ID for that chain/city/state, and exactly one distinct mapped OSM site among matching entries. Explicit conflicting store numbers prevent a match. |

Matching normalizes punctuation and the familiar city prefixes `Ft`/`Fort` and `St`/`Saint`. It does not use fuzzy geographic or name similarity. Multiple OSM fuel canopies or pumps count as one site only when every pair is within 0.15 mile (about 241 metres); separate sites are ambiguous and skipped. Conflicting store references on a source record are also skipped.

These are location matches, **not independent verification of each station's current operation or exact driveway**. OSM can be incomplete or stale, and unique city/chain matches are weaker evidence than explicit store references. OSM way/relation coordinates are geometry centres, which can be inside the forecourt rather than the entrance. The route planner must still account for road access. Highway descriptions in the assessment are retained for display but are not treated as exact street addresses. No city-centre coordinates are fabricated for unresolved stations.

Every exported row includes its source page URL. Canadian records are outside the assessment's US scope. Source prices are not taken from the locator or OSM: all fuel prices remain from the provided CSV snapshot. Duplicate price rows lack dates; the importer documents its chosen minimum-listed-price policy separately.

## Reproduce or extend the coordinates

Normal setup needs only the supplied coordinate CSV. Regeneration is optional and works offline from the checked-in compact source snapshots:

```sh
.venv/bin/python scripts/enrich_stations.py
```

`pilot-stations.json` contains the relevant public factual fields for 816 US locator entries. `coordinate-pois.json` contains only the tags/coordinates needed for matching 6,640 OSM fuel POIs, with OSM timestamp **2026-09-28T01:23:57Z**. The geographic OSM extract includes some adjacent Canadian points; these are not city/state matched to US records, and Petro-Canada is explicitly not classified as the US Petro chain.

An opt-in refresh uses the public locator's 50-result pagination (17 sequential requests for the captured network) and one bounded OSM query:

```sh
.venv/bin/python scripts/enrich_stations.py --download-pilot --download-osm
```

The script also accepts `--csv`, `--pilot`, `--osm`, and `--output` paths. A larger local OSM extract can extend matching coverage without per-station geocoding requests. A timed-out OSM response is rejected rather than silently interpreted as complete. Public services may be unavailable; the packaged CSV and snapshots allow setup without contacting them.

To add individually verified locations, provide an enriched CSV to the application's station-import command with these columns:

```csv
opis_id,latitude,longitude,source
```

Keep a URL identifying the particular station as provenance. Do not insert city coordinates to improve coverage counts.

## Attribution

OpenStreetMap data: © OpenStreetMap contributors, available under the [Open Database License](https://www.openstreetmap.org/copyright). The compact OSM source snapshot is an extraction of that database and retains its provenance and licence notice. OSM rows in the combined coordinate file retain a direct OSM object URL. Official Pilot/Flying J entries retain the corresponding public location-page URL; only factual store identifiers, cities, states, and coordinates are cached.
