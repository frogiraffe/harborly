# Library API

This page describes the public API of `harborly`. The library builds a local port
registry, searches it, and calculates an approximate sea route. Routing uses the
searoute package.

## Public API surface

The stable top-level exports are the core types: `Port`, `PortGroup`,
`PortRegistry`, `SeaRoute`, `SeaRouter`, `AsyncSeaRouter`, `SequenceSeaRoute`,
`PassageRestriction`, `BatchMatchResult`, `MatchStatus`,
`ConfidenceTier`, `MatchReason`, `MatchPolicy`, `RetryPolicy`,
`RouteQualityFlag`, `RouteQualityPolicy`, `CanonicalEvidence`, `BackendError`,
`BackendErrorKind`, and the `HarborlyError` family (`RegistryDataError`,
`SourceDataError`, `PortNotFoundError`, `AmbiguousPortError`,
`PortCoordinateError`, `RoutingError`).

Lower-level APIs are imported from their defining modules:

- `harborly.geo`: `validate_coordinate`, `CoordinateCheck`, `great_circle_nmi`.
- `harborly.text`: `canonical_key`, `normalize_display_text`.
- `harborly.sources`: `parse_wpi_dms`, `parse_unlocode_coordinates`.
- `harborly.matching`: `decide_exact_match`, `ExactMatchDecision`, `MatchCandidate`, `MatchPolicy`.
- `harborly.ports`: `PortSearchResult`, `NearbyPortResult`, `NearbyPortGroup`.
- `harborly.canonical`: `assign_canonical_ids`, `assign_canonical_ids_with_evidence`, `CanonicalEvidence`.
- `harborly.routing`: `RouteQualityFlag`, `RouteQualityPolicy`, `assess_route_length`.
- `harborly.build`: `build_reference_registry`, `download_reference_data`.
- `harborly.kml`: `to_kml_string`, `write_route_kml`.
- `harborly.geoparquet`: `write_ports_geoparquet`, `write_route_geoparquet`.

## Data lifecycle

The wheel includes a registry derived from WPI and GeoNames:

```python
from harborly import PortRegistry

registry = PortRegistry.bundled()
```

`PortRegistry.from_directory(path)` loads an alternate processed registry.

The CLI selects `--data-dir`, `SEA_MILE_DATA_DIR`,
`data/reference/processed` in the current directory, then the bundled registry.

A local build adds UN/LOCODE and may add a local OpenStreetMap export:

```bash
harborly data download
harborly data build
```

`harborly data prepare` executes both operations. Existing snapshots are reused
unless `--refresh` is specified. `--json` returns the complete manifests.

The Python calls are `download_reference_data` and `build_reference_registry`:

```python
from harborly.build import build_reference_registry, download_reference_data

download_reference_data("reference")
build_reference_registry("reference")
```

`harborly data verify` checks a local build. `verify_reference_data` in
`harborly.validation` returns the same report.

The build manifest records a `registry_schema_version` and a deterministic
`registry_content_hash`. When it loads a directory, `PortRegistry.from_directory` reads
the manifest and refuses a schema version this build of harborly does not support,
rather than failing later on a missing or renamed column. The content hash is
order-independent, so a rebuild from the same sources produces the same hash.

`harborly data lock` writes `harborly.lock.json` from the download manifest, pinning
each source's URL, snapshot label, size, and SHA-256. `harborly data build --lock`
verifies local raw snapshots before building and aborts on a mismatch. The
`write_source_lock`, `load_source_lock`, and `lock_mismatches` functions in
`harborly.build` expose the same behavior.

## Port records

A `Port` object is one provider record. It is not a cross-source consensus record.
The main fields are:

- `registry_id`, a stable, provider-qualified ID.
- `provider` and `provider_id`.
- `name`, `country_code`, and an optional `unlocode`.
- `latitude`, `longitude`, and `coordinate_resolution`.
- `function_code` and `source_version`.
- `variant_count` and `coordinate_conflict`.
- `canonical_id`, a stable ID shared by every record for the same physical port.

`Port.to_geojson_feature` returns one GeoJSON point feature. The feature properties
keep the provider and source fields.

[Data dictionary](DATA_DICTIONARY.md) documents every field each public model
serializes, with its type, whether it can be null, its unit, and its meaning.

## Search and resolution

```python
registry.search("Pireus", country_code="GR", minimum_score=75)
registry.search_grouped("Mersin", country_code="TR")
registry.get("WPI:42230")
registry.get_by_unlocode("GRPIR")
registry.resolve("GRPIR")
registry.group_for("TRMER")
```

`search` returns a ranked list of `PortSearchResult` objects. Each result holds the
matched alias, the match method, and a match score. A five-character query that
matches a known UN/LOCODE code returns with `match_method="exact_unlocode"`. This
result takes full precedence and never mixes with fuzzy matches against the code.

`search_grouped` returns a list of `PortGroup` objects. Each group is one physical
port with the source records that describe it. Records group by a shared UN/LOCODE
code, or by country, name, and coordinate agreement, so a GeoNames record joins a WPI
or UN/LOCODE record for the same place. A `PortGroup` holds:

- `name`, `country_code`, and `unlocode`.
- `members`, the source `Port` records.
- `sources`, the provider names in priority order.
- `latitude` and `longitude`, or `None` when the members disagree.
- `coordinate_conflict`, true when members that share an identity disagree on location.
- `best_score`, `match_method`, and `best_id`, the representative record ID.

`group_for` returns the `PortGroup` for a single UN/LOCODE code or registry ID. Use it
to read every source record for one known port.

### Canonical IDs

Every record carries a stable `canonical_id`, so one physical port has one identifier
across sources and across rebuilds. A port with a UN/LOCODE code uses the code as its
canonical ID. A code-less port attaches to a nearby coded record of the same name when
there is one, and otherwise gets a deterministic `SM-<hash>` from its country, name,
and rounded coordinate. `registry.resolve_canonical("TRMER")` returns the `PortGroup`
for a canonical ID. `assign_canonical_ids` computes the IDs for a registry frame, which
the build stores in the Parquet file. `PortGroup` also exposes `canonical_id`.

`resolve` is stricter than `search`. It accepts a registry ID, a UN/LOCODE code, or
one unambiguous exact alias. It does not pick a fuzzy result on its own. When two or
more providers share a UN/LOCODE code, `resolve` prefers a record with a usable
coordinate, and it prefers the WPI record over the UN/LOCODE record. A GeoNames record
with the same name but no shared code stays ambiguous.

A shared UN/LOCODE code is not enough when the coordinates disagree by a large amount.
`resolve` raises `AmbiguousPortError` when two coordinate-bearing records under the
same identity differ by more than 25 nautical miles. Change this limit with
`PortRegistry.from_directory(..., coordinate_agreement_nmi=...)`. Treat a change to
this limit as an explicit decision.

## Nearby-port search

```python
nearby = registry.nearest(39.87, 26.16, country_code="TR", limit=5, max_distance_nmi=25)
grouped = registry.nearest_grouped(39.87, 26.16, country_code="TR", limit=5)
```

Each `NearbyPortResult` holds a provider record and the great-circle distance from the
input coordinate. `nearest_grouped` returns `NearbyPortGroup` objects instead. Each one
holds a `PortGroup` and the nearest distance, so one physical port appears once even
when several sources describe it.

This search produces candidates; it does not establish port identity. Acceptance
requires review of name, country, function code, source, and coordinates.

When the `fast` extra (scipy) is installed, an unfiltered `nearest` call uses a k-d
tree. A `country_code` filter uses the full scan. Both paths return the same ranked
results.

## Registry helpers

`PortRegistry` supports `len(registry)`, `registry_id in registry`, and iteration over
every `Port`. It also offers `registry.ports()` for every record, `registry.countries()`
for the country codes present, `registry.ports_in_country("TR")` for one country's
records, and the `registry.providers` count by provider.

## Bulk name matching

`PortRegistry.match_names` resolves many port names at once and returns one
`BatchMatchResult` per input name:

```python
results = registry.match_names(["Mersin", "Hamilton"], country_codes=["TR", "US"])
```

Each `BatchMatchResult` holds the input `query`, the `country_code`, a `status`, a
`confidence_tier`, the `selected_registry_id`, a stable `reason_code`, and a short
explanatory `reason`. The `status` is a `MatchStatus` value, the `confidence_tier`
is a `ConfidenceTier` value from `A` to `D`, and the `reason_code` is a
`MatchReason` value. Programmatic handling must use `reason_code`; `reason` text
may change. The `MatchReason` values are `unique_exact_wpi`,
`unique_exact_unlocode`, `coordinate_conflict`, `multiple_identities`,
`no_candidate`, and `fuzzy_candidates_only`, plus `manual_decision` when the CLI
review workflow applies a reviewed choice.

Each result also carries `candidates`, a tuple of `MatchCandidate` records. Each holds
the `registry_id`, `provider`, `name`, `country_code`, coordinates, and `unlocode` of
one match that informed the decision, so a review step can show the evidence
behind a `review_required` or `unresolved` outcome. `match_method` and `name_score`
record how the candidate was found, so a reviewer can tell an `exact_alias` hit from
a `fuzzy_alias` suggestion. It also carries `rules_applied`, the ordered tuple of
decision-rule tokens that fired, such as `single_exact_wpi` then
`coordinate_conflict_detected`.

### Fuzzy candidates are review evidence, never an auto-resolution

When no exact official match exists, `match_names` falls back to a fuzzy alias
search so a reviewer has something to choose from. Fuzzy evidence never selects a
port on its own: such a result is reported as `review_required` with reason code
`fuzzy_candidates_only` and `selected_registry_id` left unset. Only exact official
matches can reach `auto_resolved`. A row whose country cell is empty is searched
against the global alias pool under the same review-only rule.

Pass a `MatchPolicy` to control the fuzzy score cutoff and how many candidates are
offered:

```python
from harborly import MatchPolicy

policy = MatchPolicy(fuzzy_score_cutoff=90.0, max_strong_candidates=3)
results = registry.match_names(names, country_codes=countries, policy=policy)
```

`match_names` delegates each decision to `decide_exact_match`. A single exact WPI
match and a single exact UN/LOCODE match are not necessarily the same physical
port. Places can share a name within one country, including locations separated
by hundreds of nautical miles. Candidate coordinates allow
`decide_exact_match` to return an `ExactMatchDecision` with review status instead
of selecting a conflicting record. Call `decide_exact_match` directly when
candidate ID lists are already available.

`match_series` takes a pandas Series of names and returns the same `BatchMatchResult`
list as `match_names`. It reads a missing cell as an empty name.

```python
results = registry.match_series(frame["port_name"], country_codes=frame["country"])
```

`match_dataframe` returns a copy of a frame with eight appended columns:
`harborly_status`, `harborly_reason_code`, `harborly_registry_id`, `harborly_name`,
`harborly_country_code`, `harborly_latitude`, `harborly_longitude`, and
`harborly_unlocode`. These are the same columns that `harborly match --output` writes.

```python
enriched = registry.match_dataframe(
    frame, name_column="port_name", country_column="country"
)
```

To match a file too large to hold in memory, read it in chunks and match each chunk on
its own. Neither the reader nor the matcher holds the whole file.

```python
import pandas as pd

header = True
for chunk in pd.read_csv("big.csv", chunksize=10_000, dtype=str, keep_default_na=False):
    enriched = registry.match_dataframe(chunk, name_column="port_name")
    enriched.to_csv("out.csv", mode="a", header=header, index=False)
    header = False
```

The `harborly match --output` command streams the same way. It reads the input in
chunks and appends each block to the output file, so it does not load the whole input
either.

## Sea routes

```python
from harborly import SeaRouter

router = SeaRouter()
route = router.route(origin, destination)
route.summary()
route.to_geojson_feature()

router.route_coordinates(36.8, 34.65, 37.94, 23.63)
router.route_many([(origin, destination)])
router.distance_matrix([origin, destination])
for row, column, distance_nmi in router.iter_distance_edges(
    [origin, destination],
    max_workers=4,
):
    print(row, column, distance_nmi)
```

The default settings use the searoute A* algorithm, the NetworkX backend, the
`northwest` passage restriction, and explicit nautical-mile units. Pass a
`RouteQualityPolicy` to customise the plausibility thresholds:

```python
from harborly import SeaRouter, RouteQualityPolicy, RetryPolicy

quality_policy = RouteQualityPolicy(
    high_detour_ratio=2.5,
    lower_bound_tolerance_nmi=1.0,
)
retry_policy = RetryPolicy(
    attempts=4,
    base_backoff_seconds=0.25,
    max_backoff_seconds=8.0,
    jitter_ratio=0.5,
)
router = SeaRouter(quality_policy=quality_policy, retry_policy=retry_policy)
```

Backend retries are configured via `RetryPolicy`, which accepts 1–8 attempts,
finite non-negative backoff times, and a `jitter_ratio` from 0.0 to 1.0.

`overall_timeout_seconds` (default `None`, meaning no budget) caps the whole
retry ladder. Before each backoff the router checks whether the wait still fits
the budget; where it does not, it stops instead of sleeping and raises
`RoutingError` with the reason `timeout_budget_exhausted`, chaining the failure
that was being retried. Without it, `RetryPolicy(attempts=8,
max_backoff_seconds=8.0)` can spend roughly 24 seconds asleep inside a single
`route()` call, which under `harborly serve` holds a threadpool worker for that
whole time.

The budget bounds *scheduling*, not execution. A backend call already running
cannot be interrupted, so one slow attempt can still overrun the budget. A hard
per-attempt deadline requires a backend that accepts one; the bundled
`searoute` backend is a synchronous in-process call and does not.

Timeouts, connection errors, HTTP 429, and HTTP 5xx responses are internally
classified as transient. `BackendError` exposes the resulting
`BackendErrorKind` (`NETWORK`, `TIMEOUT`, `RATE_LIMIT`, `SERVER`,
`INVALID_RESPONSE`, or `UNKNOWN`) and a `transient` boolean.

Advanced callers can import `CircuitBreakerPolicy` from `harborly.router` and
pass it to `SeaRouter` to set `failure_threshold` and `recovery_seconds`. This
documented lower-level policy protects against repeated calls while a backend
is unavailable. When tripped, calls raise `RoutingError` with the stable reason
`circuit_breaker_open`.

A `SeaRoute` holds:

- `distance_nmi` and `great_circle_nmi`.
- `detour_ratio` and `quality_flag`.
- the routing backend name and version, in `engine` and `engine_version`.
- the effective routing config: `algorithm`, `backend`, and `restrictions`.
- the origin and destination provider records.
- a GeoJSON LineString geometry, on export.

The `quality_flag` is a `RouteQualityFlag` value. A returned route is either `ok` or
`high_detour_ratio` for a route far longer than the great-circle lower bound, or
`coincident_endpoints` when the origin and destination are the same point. The
remaining values, `below_great_circle_lower_bound`, `nonzero_route_for_coincident_endpoints`,
`invalid_route_distance`, and `invalid_great_circle_distance`, describe a route that
fails the plausibility check, which raises `RoutingError` rather than returning.
Programmatic handling must use `RouteQualityFlag`; descriptive text is not a
stable interface. `SeaRouter` memoizes results per instance, keyed on the ports
and the config.

The `engine` and `engine_version` fields are the routing backend name and version. The
default backend is searoute. The `algorithm`, `backend`, and `restrictions` fields are
the effective routing configuration, so a route records the exact settings that produced
it. Routing runs behind a small internal backend interface. That interface is not a
public extension point, and it may change without notice.

The searoute backend does not expose the graph nodes it uses when it snaps an endpoint
to its routing network. harborly therefore does not report or estimate snapped
coordinates. A route retains the submitted origin and destination and does not
present an inferred snapped point as observed data.

`route_ids` routes two registry IDs. `route_coordinates` routes two raw `lat, lon`
points without a registry lookup. `route_many` routes a list of port pairs.
`distance_matrix` returns the pairwise sea distance for a list of ports. The bundled
searoute backend declares symmetric distances, so harborly calculates one route for
each unordered pair. An internal backend that does not declare symmetry is calculated
in both directions. Each worker process runs an initializer that pre-imports the
routing backend modules, so the first task in a worker does not pay the import cost.
The default worker count is capped at four, tasks are submitted as bounded batches,
and `max_workers` can override the count. The dense `distance_matrix` result itself
uses O(n²) memory. `iter_distance_edges` uses the same bounded scheduler but yields
`(row_index, column_index, distance_nmi)` tuples without constructing the matrix.
For symmetric backends it yields each unordered pair once; directional backends
yield both directions.
Routing needs the `routing` extra. `SeaRouter` imports without it,
but a route call raises `ImportError` when it is missing.

Persistent caches are opt-in through `SeaRouter(cache_path=...)`. The CLI can
inspect and maintain the same explicit file with `cache info`, `cache prune`,
and `cache clear`. Cache schema, retention, retry, circuit-breaker, and partial
result behavior are documented in
[Routing and cache operations](ROUTING_AND_CACHE.md).

`SeaRouter(cache_failure_policy=...)` takes a `CacheFailurePolicy` and decides
what a failing cache costs the caller. Every entry the cache holds can be
recomputed, so a cache failure need not be a routing failure — but which answer
is right depends on who is asking, so it is stated rather than assumed.

- `CacheFailurePolicy.STRICT` (default, and the behaviour of every release so
  far) turns any read, write, or eviction failure into a `RoutingError` with
  the reason `cache_access_failed`. A caller who asked for a cached result
  should hear that the cache is broken.
- `CacheFailurePolicy.BEST_EFFORT` logs the failure at `WARNING` on the
  `harborly.router` logger and answers from a fresh computation: an unreadable
  entry becomes a cache miss, an unwritable result is still returned, and a
  failed eviction no longer replaces the routing error that triggered it. For a
  long-running service that would rather be slow than unavailable.

Neither policy changes what a *healthy* cache does.

## Optional service and visualizations

`harborly serve` starts the FastAPI application from `harborly.api` with Uvicorn
after checking that both the `api` and `routing` extras are installed. The base
URL redirects to `/docs`, and `GET /v1/livez` returns the service name, liveness
status, and installed package version. `GET /v1/readyz` probes the dependencies
a route request needs and returns `503` when any is unusable; `SeaRouter`
exposes the same probe as `check_ready()`, which returns `ReadinessCheck`
records without computing a route.

The `GET /v1/route` endpoint accepts `origin`, `destination`, and optional
`origin_country` and `destination_country` query parameters. It resolves both
ports through `PortRegistry.bundled()`, routes them with `SeaRouter`, and returns:

```json
{
  "distance_nmi": 412.5,
  "geojson": {
    "type": "Feature",
    "properties": {},
    "geometry": {
      "type": "LineString",
      "coordinates": [[34.65, 36.8], [23.63, 37.94]]
    }
  }
}
```

`GET /route` is a deprecated alias of the same endpoint and is removed in 2.0.

The OpenAPI document defines the route, GeoJSON, port-provenance, health, and
error response models. Errors carry `{schema_version, error: {code, message,
retryable, details}}`, where `code` is the raising exception's stable `.code`.
HTTP 404 indicates an unknown port, 409 an ambiguous identity, 422 invalid
input, 502 a routing-backend failure, and 503 unavailable routing or an open
circuit breaker. See [HTTP service](API_SERVICE.md) for the full contract.

The local application intentionally has no matrix endpoint and supplies no
authentication, rate limiting, TLS termination, or request deadline. See
[HTTP service](API_SERVICE.md) before deploying it outside a workstation.

Install the `api` and `routing` extras together for this command. `create_app` accepts
injected registry and router objects for isolated application tests; the default
application uses the bundled registry.

`harborly route ORIGIN DESTINATION --html-map route.html` writes an interactive
Folium preview. The route geometry crosses the visualization boundary as
`LonLat(longitude, latitude)` before Folium receives its required latitude,
longitude locations. Install the `map` and `routing` extras.

`harborly route ORIGIN DESTINATION --kml route.kml` writes a KML document
suitable for Google Earth and GIS tools. `harborly export --format kml` exports
matching port records. The KML module (`harborly.kml`) exposes `to_kml_string`
and `write_route_kml` for programmatic access:

```python
from harborly.kml import to_kml_string, write_route_kml

kml_str = to_kml_string(route)          # SeaRoute or SequenceSeaRoute
write_route_kml(seq, "voyage.kml")      # writes to disk
```

`harborly export --format geoparquet --output ports.geoparquet` exports matching
port records as an OGC GeoParquet file. `harborly.geoparquet` provides
`write_ports_geoparquet` and `write_route_geoparquet`:

```python
from harborly.geoparquet import write_ports_geoparquet, write_route_geoparquet

write_route_geoparquet(route, "route.geoparquet")   # LineString WKB geometry
write_ports_geoparquet(ports, "ports.geoparquet")   # Point WKB geometry
```

GeoParquet files use OGC WKB encoding, CRS `OGC:CRS84` (lon/lat WGS84), and
include a `geo` metadata key compliant with the GeoParquet 1.0.0 specification.
`MultiLineString` routes (e.g. antimeridian-crossing) are encoded as WKB type 5.
`pyarrow` is a core dependency and is always available in a standard installation.

When opened directly as a `file://` URL, the HTML uses the embedded Natural
Earth 110m coastline and does not request public raster tiles. When served over
HTTP or HTTPS, it adds the detailed OpenStreetMap layer. This prevents local
files, which cannot supply the required web-page referrer, from rendering a
grid of 403 responses. To view detailed tiles locally, run
`python -m http.server 8000` in the output directory and open
`http://127.0.0.1:8000/route.html`. Folium's generated HTML can still reference
Leaflet and supporting front-end assets on CDNs, so the artifact is not a
fully offline application.

The `tui` command launches an interactive split-screen terminal UI built on
Textual. The left pane shows a DataTable of search results; the right pane
renders a braille world map with embedded NE 110m coastlines, port markers,
and port clustering at low zoom levels.

The UI supports vim-style modal navigation: press `Esc` to enter browse mode
(pan, zoom, go-to-port shortcuts), then `i` to return to insert mode for
search input. Viewport state (`zoom`, `center_lat`, `center_lon`) is managed
by `BrailleWorldMap` in `harborly.tui.map_canvas`.

Install the `tui` extra: `pip install harborly[tui]`.

## Coordinates and text helpers

`validate_coordinate` returns a `CoordinateCheck` and rejects missing, non-numeric,
out-of-range, and (0, 0) coordinates. `great_circle_nmi` returns the Haversine
distance in nautical miles using the 6,371.0087714 km mean Earth radius.

`canonical_key` builds an accent-insensitive search key. `normalize_display_text`
normalizes Unicode and whitespace but keeps accents. `parse_wpi_dms` and
`parse_unlocode_coordinates` parse the two source coordinate formats. They return
`None` for an out-of-range value or for an invalid minute or second component.
WPI values with 60 seconds are accepted because the source uses that value for
rounded coordinates.

`assess_route_length` checks a sea-route result against physical plausibility
rules. It accepts an optional `RouteQualityPolicy` to customise thresholds:

```python
from harborly.routing import assess_route_length, RouteQualityPolicy

assessment = assess_route_length(400, 300, policy=RouteQualityPolicy(high_detour_ratio=2.0))
```

## Error types

Every recoverable public error is a subclass of `HarborlyError`:

- `RegistryDataError`, the local registry files are missing or invalid.
- `SourceDataError`, a public snapshot could not be downloaded or read.
- `PortNotFoundError`, no port matches the identifier or exact name.
- `AmbiguousPortError`, more than one independent port identity matches.
- `PortCoordinateError`, a selected port has no usable routing coordinate.
- `RoutingError`, the routing backend or persistent cache failed, the backend
  returned an unusable result, or the route failed the plausibility check. Its
  `reason` attribute carries a stable token: `backend_call_failed`,
  `cache_access_failed`, `malformed_backend_result`, `implausible_route`, or
  `circuit_breaker_open`. Programmatic error handling must use this token rather
  than the message.

The CLI prints each error to `stderr` and exits with status code 2.
