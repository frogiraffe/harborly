# Sources, attribution, and limitations

## Attribution and redistribution

The wheel includes a normalized registry derived from WPI and GeoNames. It does
not contain raw source archives. Snapshot URLs, labels, sizes, and SHA-256
digests are stored in the bundled `registry_manifest.json`.

UN/LOCODE records are generated only by a local build and are not redistributed
in the wheel. OpenStreetMap records are included only when a user supplies a
local export.

The current bundled manifest contains 20,070 WPI and GeoNames source records
and 34,216 aliases. Of those records, 2,563 carry a UN/LOCODE supplied by WPI.
Counts can change in later releases; `harborly info --json` and the bundled
manifest are authoritative for the installed wheel. A local reference build
can add the complete port-function subset of the discovered UN/LOCODE release.

## Data sources

### NGA World Port Index

- Publisher: National Geospatial-Intelligence Agency (NGA).
- Product page: https://msi.nga.mil/Publications/WPI
- Use in harborly: port names, aliases, coordinates, and UN/LOCODE links.
- Licensing: a work of the United States federal government.

The bundled registry includes the WPI-derived records. The WPI publication is a
United States Government work for which no copyright is claimed under Title 17
U.S.C. A local download records the checksum and retrieval date in
`data/reference/manifest.json`.

### UNECE UN/LOCODE

- Publisher: United Nations Economic Commission for Europe (UNECE).
- Product page: https://unece.org/trade/uncefact/unlocode
- Downloads: https://unlocode.unece.org/
- Use in harborly: records with a port function code, the five-character location code,
  the name, the status, the function flags, and an optional coordinate.

UN/LOCODE is a location-code list rather than a berth database. Many port-coded
records have no coordinate. Coordinates use arc-minute precision and may be less
precise than WPI or GeoNames coordinates. harborly discovers and downloads the
latest official GitLab release for local processing and records the resolved
release in its manifest. It does not include derived UN/LOCODE records in the wheel.

### GeoNames

- Publisher: GeoNames.
- Dump: https://download.geonames.org/export/dump/
- Feature codes: https://www.geonames.org/export/codes.html
- License: Creative Commons Attribution 4.0,
  https://creativecommons.org/licenses/by/4.0/
- Required attribution: this product contains GeoNames data, available from
  https://www.geonames.org/.

The bundled registry includes the `ANCH`, `DCK`, `DCKB`, `DCKY`, `FYT`, `HBR`,
`LDNG`, `MAR`, and `PRT` feature codes. GeoNames coordinates remain
provider-specific candidates and do not overwrite another provider's record.
Some upstream GeoNames rows do not provide a country code. harborly preserves
that missing value rather than inferring a country from coordinates, so those
records are excluded when a country filter is used.

### OpenStreetMap (optional)

- Publisher: OpenStreetMap contributors.
- License: Open Database License (ODbL), https://www.openstreetmap.org/copyright
- Use in harborly: harbor, port, and marina point features.

OpenStreetMap is an optional local source. harborly does not download it. Place a
GeoJSON export of harbor, port, and marina point features under
`data/reference/raw/osm/<label>/`, then run `harborly data build`. The build includes
the export as the `OPENSTREETMAP` provider only when the file is present. A GeoJSON
export carries the ODbL attribution and share-alike terms with it.

Generate an export by querying the Overpass API for the target area. Select nodes
tagged `harbour`, `leisure=marina`, or a `seamark:type` of harbour or marina
inside the bounding box, and return center points with `out center`. Convert the
result with a tool such as `osmtogeojson` and save it as
`data/reference/raw/osm/<label>/ports.geojson`. harborly reads the `name`,
`addr:country`, and harbor, port, or marina tags from each point feature.

## Routing engine

- Engine: searoute-py, https://github.com/genthalili/searoute-py
- License, per the package metadata: Apache-2.0.
- Install: the `routing` extra.

The searoute-py project calculates approximate routes on a maritime graph. Its
documentation states that these routes are not for a mariner's use. harborly repeats
that warning in every GeoJSON route. A harborly route does not account for draft,
water depth, weather, a traffic separation scheme, a local notice, a vessel class, a
port-entry rule, a closure, or a navigational hazard.

The searoute backend does not expose the graph nodes it uses when it snaps an endpoint
to its routing network. harborly therefore does not report or estimate snapped
coordinates. A route retains the submitted origin and destination. harborly does
not expose an inferred snapped coordinate.

harborly routes through a small internal backend interface, with searoute as the default
backend. The route records the backend name and version in `engine` and `engine_version`.
The interface is internal. It is not a public plugin point.

## Optional extras

- `routing`: searoute, for sea routing and the distance matrix.
- `tui`: textual, for interactive terminal search with a braille world map.
- `api`: FastAPI and Uvicorn, for the optional HTTP server.
- `map`: Folium, for interactive HTML route previews.
- `fast`: scipy, for a k-d tree in `nearest`.
- `analysis`: pyproj, for the WGS84 route cross-check in `data verify`.

The API and HTML map features also need `routing` when they calculate a route.
HTML previews include the public-domain Natural Earth 110m coastline for
tile-independent `file://` viewing. The detailed OpenStreetMap raster layer is
enabled only when the page is served over HTTP or HTTPS so the browser can send
the referrer required by the public tile service. Folium's output may still load
Leaflet and supporting assets from CDNs, so the HTML is not fully offline.
Public OSM tiles are a best-effort external service, not a bundled data source
or availability guarantee.

## What the registry count means

The registry holds source records, not unique physical ports. Each provider
contributes records. One physical port can have a record in two or more sources. One
large port can have more than one terminal, or a nearby named facility, as a separate
record. `harborly info` reports record counts for the active build.

Grouped search collapses records that describe the same physical port. Use it to read
one row per port. Use `resolve` to select one record for routing. harborly does not
claim to hold a record for every port in the world.

Coordinates from different providers can disagree because their records may
refer to different terminals, use different precision, or contain upstream
errors. `harborly data verify --json` reports cross-provider agreement metrics;
large differences are retained as provenance evidence and are not silently
averaged or overwritten.

`data verify` targets the local reference directory selected by
`--reference-root`, the checkout fallback, or the user-data fallback. The report
includes the resolved path and labels it `local_reference_build`; it does not
verify or describe the smaller registry embedded in the wheel.

## A single exact match is not always the same port

Real places can share a name within one country. A single exact WPI match and a single
exact UN/LOCODE match can be two different ports, hundreds of nautical miles apart, for
example two United States places named "Hamilton". `harborly match` and
`decide_exact_match` compare the WPI and UN/LOCODE coordinates and ask for a review when
they disagree, instead of picking one record. See [Library API](LIBRARY_API.md) for the
call shape.

## Port identity review procedure

1. Search the exact aliases first, with the expected country code.
2. Check every provider record and its source version.
3. Use a fuzzy search only to build a candidate list.
4. Check `nearest` results and distances when a known coordinate is available.
5. Check the point on a map. Confirm that it is on, or near, the correct facility.
6. Record the selected provider ID, confidence level, and rationale.
7. Calculate the route. Check the great-circle distance and the detour ratio.

Fuzzy and nearest-port results are candidate-generation evidence. A source-record
replacement requires an explicit recorded decision.
