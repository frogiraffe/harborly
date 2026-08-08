
# Harborly reference

This reference covers Harborly's public library, command-line interface, local
HTTP service, data contracts, and operational limits. It assumes the package is
installed; see the project README for installation and first-run instructions.

> [!IMPORTANT]
> Harborly routes are approximate graph routes for analysis. They are not
> suitable for navigation, voyage planning, or safety-critical use.

## Public library

The stable top-level API is exported from `harborly`:

```python
from harborly import (
    AmbiguousPortError,
    AsyncSeaRouter,
    BackendError,
    BackendErrorKind,
    BatchMatchResult,
    CacheFailurePolicy,
    CanonicalEvidence,
    ConfidenceTier,
    HarborlyError,
    MatchPolicy,
    MatchReason,
    MatchStatus,
    PassageRestriction,
    Port,
    PortCoordinateError,
    PortGroup,
    PortNotFoundError,
    PortRegistry,
    RegistryDataError,
    RetryPolicy,
    RouteQualityFlag,
    RouteQualityPolicy,
    RoutingError,
    SeaRoute,
    SeaRouter,
    SequenceSeaRoute,
    SourceDataError,
)
```

Lower-level helpers remain available from their defining modules:

| Module | Public helpers |
| --- | --- |
| `harborly.geo` | `validate_coordinate`, `CoordinateCheck`, `great_circle_nmi` |
| `harborly.text` | `canonical_key`, `normalize_display_text` |
| `harborly.sources` | `parse_wpi_dms`, `parse_unlocode_coordinates` |
| `harborly.matching` | `decide_exact_match`, `ExactMatchDecision`, `MatchCandidate` |
| `harborly.ports` | `PortSearchResult`, `NearbyPortResult`, `NearbyPortGroup` |
| `harborly.canonical` | `assign_canonical_ids`, `assign_canonical_ids_with_evidence` |
| `harborly.routing` | `assess_route_length` |
| `harborly.build` | `download_reference_data`, `build_reference_registry` |
| `harborly.kml` | `to_kml_string`, `write_route_kml` |
| `harborly.geoparquet` | `write_ports_geoparquet`, `write_route_geoparquet` |

### Registry API

Load the bundled registry, then resolve stable identities before automating a
route. `resolve` accepts a provider-qualified registry ID, a UN/LOCODE, or one
unambiguous exact alias. It never chooses a fuzzy match.

```python
from harborly import PortRegistry

registry = PortRegistry.bundled()
origin = registry.resolve("TRMER")
destination = registry.resolve("GRPIR")
```

| Method | Signature | Result |
| --- | --- | --- |
| `PortRegistry.from_parquet` | `(registry_path, aliases_path, *, coordinate_agreement_nmi=25.0)` | Loads a pair of processed Parquet files. |
| `PortRegistry.from_directory` | `(directory, *, coordinate_agreement_nmi=25.0)` | Loads the processed registry and alias Parquet pair from the directory. |
| `PortRegistry.bundled` | `(*, coordinate_agreement_nmi=25.0)` | Loads the distributed registry. |
| `search` | `(query, *, country_code=None, limit=10, fuzzy=True, minimum_score=75.0)` | Ranked provider records with alias evidence. |
| `search_grouped` | `(query, *, country_code=None, limit=10, fuzzy=True, minimum_score=75.0)` | One logical-port group per result. |
| `get` | `(registry_id)` | One provider record. |
| `get_by_unlocode` | `(unlocode)` | All source records for a code. |
| `resolve` | `(query, *, country_code=None)` | One unambiguous provider record. |
| `group_for` | `(query, *, country_code=None)` | The group for an ID or UN/LOCODE. |
| `resolve_canonical` | `(canonical_id)` | The group for a canonical identity. |
| `nearest` | `(latitude, longitude, *, country_code=None, limit=10, max_distance_nmi=None)` | Provider records ranked by great-circle distance. |
| `nearest_grouped` | `(latitude, longitude, *, country_code=None, limit=10, max_distance_nmi=None)` | Logical-port groups ranked by distance. |
| `match_names` | `(names, *, country_codes=None, policy=None)` | One `BatchMatchResult` per input name. |
| `match_series` | `(names, *, country_codes=None)` | The same matching operation for pandas Series. |
| `match_dataframe` | `(frame, *, name_column, country_column=None)` | A copy with Harborly match columns appended. |

`search` and `nearest` return source records. Their grouped variants combine
records that represent one physical port. A group is evidence, not a replacement
for a provider record; use `resolve` when routing.

Canonical IDs provide a deterministic cross-source identity. A UN/LOCODE is
used directly when available; otherwise Harborly derives an `SM-<hash>` value
from the country, name, and rounded coordinate. Records with materially
conflicting coordinates remain ambiguous instead of being silently merged.

### Data models and serialisation

Coordinates are WGS84 decimal degrees and distances are nautical miles. A
missing coordinate is `null`; `(0, 0)` is treated as a missing coordinate by
validation.

#### `Port`

`Port` is one provider-specific record, not a consensus record. `to_dict()`
serialises all fields and `to_geojson_feature()` produces a GeoJSON Point (or a
feature with `geometry: null` when the record has no coordinate).

| Field | Meaning |
| --- | --- |
| `registry_id` | Stable provider-qualified ID, such as `WPI:44860`. |
| `provider`, `provider_id` | Source name and its source-local identifier. |
| `country_code`, `name`, `unlocode` | Identity and display data; `unlocode` can be null. |
| `latitude`, `longitude`, `coordinate_resolution` | WGS84 position and its recorded precision. |
| `function_code`, `source_version` | Provider metadata and snapshot version. |
| `variant_count`, `coordinate_conflict` | Reconciliation provenance. |
| `canonical_id` | Cross-source physical-port identity, or an empty string before grouping. |

`PortSearchResult` adds `matched_alias`, `match_method`, and `name_score`.
`NearbyPortResult` adds `distance_nmi`. `PortGroup` contains `members`, ordered
`sources`, its canonical ID, representative position, conflict status, and the
representative's `best_score`, `match_method`, and `best_id`.

#### Bulk-match results

`BatchMatchResult.to_dict()` returns `query`, `country_code`, `status`,
`confidence_tier`, `selected_registry_id`, `reason_code`, `reason`,
`rules_applied`, and `candidates`. Each `MatchCandidate` records its provider
provenance, coordinates, UN/LOCODE, `match_method`, and `name_score`.

| Field | Values or use |
| --- | --- |
| `status` | `auto_resolved`, `review_required`, `unresolved`, or `manually_resolved`. |
| `confidence_tier` | `A` through `D`; an evidence tier, not a calibrated probability. |
| `reason_code` | `unique_exact_wpi`, `unique_exact_unlocode`, `coordinate_conflict`, `multiple_identities`, `no_candidate`, `fuzzy_candidates_only`, or `manual_decision`. |

Use `reason_code`, rather than the human-readable `reason`, in automation.
Fuzzy search only produces review candidates; it cannot auto-resolve a name.

`match_dataframe` and `harborly match --output` append these columns to input
rows: `harborly_status`, `harborly_reason_code`, `harborly_registry_id`,
`harborly_name`, `harborly_country_code`, `harborly_latitude`,
`harborly_longitude`, and `harborly_unlocode`.

### Routing API

`SeaRouter` calculates routes through the optional `searoute` backend. Importing
the class needs no routing extra, but calling a route without that extra raises
`ImportError`.

```python
from harborly import PassageRestriction, SeaRouter

router = SeaRouter(
    restrictions=[PassageRestriction.SUEZ],
    cache_path=".cache/harborly/routes.sqlite3",
)
route = router.route(origin, destination, speed_knots=14.0)
print(route.distance_nmi, route.duration_hours)
```

| Constructor or method | Signature | Result |
| --- | --- | --- |
| `SeaRouter` | `(*, algorithm="astar", backend="networkx", restrictions=("northwest",), cache_path=None, retry_policy=None, quality_policy=None, circuit_breaker_policy=None, cache_failure_policy=CacheFailurePolicy.STRICT)` | Synchronous router. |
| `route` | `(origin, destination, *, speed_knots=None)` | One `SeaRoute`. |
| `route_sequence` | `(ports, *, speed_knots=None)` | `SequenceSeaRoute`; requires at least two ports. |
| `route_ids` | `(registry, origin_id, destination_id)` | Routes two registry IDs. |
| `route_coordinates` | `(origin_latitude, origin_longitude, destination_latitude, destination_longitude, *, speed_knots=None)` | Routes raw coordinates. |
| `route_many` | `(pairs)` | One route per `(origin, destination)` pair. |
| `distance_matrix` | `(ports, *, max_workers=None)` | Dense pairwise distance matrix. |
| `iter_distance_edges` | `(ports, *, max_workers=None)` | Streaming `(row, column, distance_nmi)` tuples. |
| `check_ready` | `()` | Backend and cache readiness checks without computing a route. |

`AsyncSeaRouter(router=None, **kwargs)` exposes asynchronous versions of
`route`, `route_sequence`, `route_ids`, `route_coordinates`, `route_many`,
`distance_matrix`, and `iter_distance_edges`; it delegates blocking work to
threads.

`SeaRoute.summary()` returns source ports, both distance measures, quality,
speed/duration values, and effective routing metadata. `to_geojson_feature()`,
`to_kml()`, and `write_kml(path)` export the route. A `SequenceSeaRoute`
contains `ports`, `legs`, total distances, optional speed and durations, plus
`summary()`, `to_geojson_feature_collection()`, `to_kml()`, and `write_kml()`.

`speed_knots` must be positive. With a speed, `duration_hours` and
`duration_days` are derived from the route distance; otherwise they are null.

#### Quality, retries, and restrictions

The default router requests A* with the NetworkX backend and restricts the
Northwest passage. Other supported `PassageRestriction` values are `suez`,
`panama`, `kiel`, and `baban`.

`RouteQualityPolicy(lower_bound_tolerance_nmi=0.5, high_detour_ratio=3.0)`
checks that a result is physically plausible. A returned route has quality
`ok`, `high_detour_ratio`, or `coincident_endpoints`; other quality flags cause
a `RoutingError` instead of producing a route.

`RetryPolicy(attempts=4, base_backoff_seconds=0.25,
max_backoff_seconds=8.0, jitter_ratio=0.5, overall_timeout_seconds=None)`
controls transient backend retries. It accepts one to eight attempts. An
overall budget stops a retry when the next backoff cannot fit, but it cannot
interrupt an already running synchronous backend call.

`CircuitBreakerPolicy` is an advanced API from `harborly.router`. Pass it to
`SeaRouter` to protect repeated calls during transient backend failure; breaker
state belongs to one router instance and is not shared by matrix workers.

#### Matrices and persistent cache

`distance_matrix` necessarily retains an O(n²) result. Prefer
`iter_distance_edges` or the CLI's `--edge-csv` for large data sets. The
bundled backend is symmetric, so it computes each unordered pair once. Workers
are process-based; the default is capped at four, and a custom backend must be
serializable when more than one worker is requested.

An explicit `cache_path` enables SQLite caching across router instances and
processes. Cache keys include both endpoint coordinates, the effective routing
configuration, engine and graph versions, and the cache-key schema. Cache
connections use WAL mode, a 30-second busy timeout, and short write
transactions. Invalid cached JSON, distances, or geometry are evicted when
read.

The default `CacheFailurePolicy.STRICT` surfaces a cache read, write, or
eviction failure as `RoutingError(reason="cache_access_failed")`.
`CacheFailurePolicy.BEST_EFFORT` logs the failure and computes a fresh route.
Use the latter only when degraded routing is preferable to an unavailable
service.

The cache is a performance artifact: it contains no registry or source data.
Its schema version is independent of cache keys; a cache created by an unknown
newer schema fails closed rather than being changed.

### Errors

Every recoverable public exception derives from `HarborlyError`:

| Exception | Meaning |
| --- | --- |
| `RegistryDataError` | Local registry files are missing or invalid. |
| `SourceDataError` | A public source snapshot could not be downloaded or read. |
| `PortNotFoundError` | No port matched a requested identifier or exact name. |
| `AmbiguousPortError` | More than one independent port identity matched. |
| `PortCoordinateError` | A selected port lacks a usable coordinate. |
| `RoutingError` | Backend, cache, malformed-result, or plausibility failure. |

`RoutingError.reason` is a stable machine value: `backend_call_failed`,
`cache_access_failed`, `malformed_backend_result`, `implausible_route`,
`circuit_breaker_open`, or `timeout_budget_exhausted`. Do not automate against
exception message text.

## Command-line interface

`harborly` uses the active local registry. With no `--data-dir`, it checks
`HARBORLY_DATA_DIR`, then `data/reference/processed` in the current directory,
then the bundled registry. The `--data-dir` flag takes precedence.

| Command | Purpose |
| --- | --- |
| `info [--json]` | Show active registry size and provider coverage. |
| `search QUERY [--country CC] [--all-sources] [--json]` | Search aliases and names. |
| `show PORT [--country CC] [--json]` | Resolve an ID, UN/LOCODE, or exact alias. |
| `near LAT LON [--country CC] [--max-distance-nmi N] [--all-sources] [--json]` | Find nearby ports. |
| `match $input_path ...` | Match a CSV and optionally write enriched or review output. |
| `route ORIGIN DESTINATION ...` | Calculate one approximate route. |
| `matrix PORT ...` | Calculate a dense matrix or stream edges. |
| `cache info|prune|clear PATH` | Inspect or maintain a route cache. |
| `export` | Export matching ports as CSV, GeoJSON, KML, or GeoParquet. |
| `data download|build|prepare|verify|lock` | Maintain an optional local reference build. |
| `tui` | Launch the optional terminal UI. |
| `serve` | Run the optional local HTTP service. |

### CLI examples

Use exact IDs after search for repeatable operations:

```bash
harborly search "Port Said" --country EG
harborly show EGPSD --json
harborly route EGPSD GRPIR --json
```

Route via intermediate ports, apply passage restrictions, and write portable
side artifacts without changing the route JSON result:

```bash
harborly route TRMER GRPIR --via EGPSD --restrictions suez \
  --geojson route.geojson --kml route.kml --html-map route.html
```

For a large matrix, stream edge rows to an atomic CSV output rather than
retaining the dense result:

```bash
harborly matrix TRMER GRPIR TRIST EGPSD \
  --edge-csv route-edges.csv --workers 4 --cache .cache/routes.sqlite3
```

If any edge fails, the requested edge CSV is not replaced with a partial file.
For the cache used above:

```bash
harborly cache info .cache/routes.sqlite3 --json
harborly cache prune .cache/routes.sqlite3 --older-than-days 90
harborly cache clear .cache/routes.sqlite3 --vacuum
```

Stop active writers before `--vacuum`, which needs an exclusive database lock.

To review bulk-match ambiguity, first produce candidate records, then apply a
decisions file containing `row_id` and `chosen_registry_id`:

```bash
harborly match ports.csv --name-column port_name --country-column country \
  --id-column row_id --output matched.csv --review review.csv

harborly match ports.csv --name-column port_name --id-column row_id \
  --decisions decisions.csv --output matched.csv
```

### JSON output schema

Commands supporting `--json` write exactly one document to standard output.
The schema is versioned by `schema_version` and contains either `data` or
`error`.

```json
{
  "schema_version": "1",
  "command": "search",
  "data": [],
  "warnings": []
}
```

```json
{
  "schema_version": "1",
  "command": "show",
  "error": {
    "code": "port_not_found",
    "message": "no exact port match for the requested identifier",
    "details": {}
  }
}
```

`message` can change. Code handling should use `error.code`, whose values are
`port_not_found`, `ambiguous_port`, `port_coordinate`, `routing_error`,
`registry_data_error`, `source_data_error`, and `usage_error`. Recoverable CLI
errors exit with status 2. `matrix --edge-csv` cannot be combined with `--json`.
The interactive `tui` and `serve` commands do not support it.

## Local HTTP service

`harborly serve --host 127.0.0.1 --port 8000` starts a FastAPI application.
It requires both the `api` and `routing` extras. The root path redirects to the
interactive OpenAPI document at `/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Redirect to `/docs`. |
| `GET` | `/v1/livez` | Process liveness; does not probe dependencies. |
| `GET` | `/v1/readyz` | Whether the registry, backend, and cache can serve a route. |
| `GET` | `/v1/route` | Resolve and route two bundled port identities. |

`/v1/route` accepts required `origin` and `destination`, plus optional
two-character `origin_country` and `destination_country` filters:

```bash
curl 'http://127.0.0.1:8000/v1/route?origin=TRMER&destination=GRPIR'
```

Its success payload has the route distance plus a GeoJSON Feature with full
route provenance:

```json
{
  "distance_nmi": 412.5,
  "geojson": {
    "type": "Feature",
    "properties": {
      "routing_units": "nautical_miles",
      "navigation_warning": "Approximate graph route; not for navigation."
    },
    "geometry": {
      "type": "LineString",
      "coordinates": [[34.65, 36.8], [23.63, 37.94]]
    }
  }
}
```

The service error contract is:

```json
{
  "schema_version": "1",
  "error": {
    "code": "routing_error",
    "message": "routing backend call failed",
    "retryable": true,
    "details": {"reason": "backend_call_failed"}
  }
}
```

| Status | Meaning |
| --- | --- |
| `404` | Port identity not found. |
| `409` | Port identity ambiguous. |
| `422` | Invalid query, coordinate, or request validation. |
| `500` | Other Harborly domain error. |
| `502` | Routing backend failure. |
| `503` | Routing extra unavailable, readiness failed, circuit breaker open, or retry budget exhausted. |

Only `backend_call_failed`, `circuit_breaker_open`, and
`timeout_budget_exhausted` errors are marked retryable and receive a
`Retry-After` header. The service deliberately has no bulk/matrix route
endpoint.

The bundled server supplies no authentication, authorization, TLS termination,
rate limiting, request deadlines, or cross-process admission control. Do not
expose it directly to the public internet. Add those controls in deployment
infrastructure if a public service is required.

## Exports and visualisations

`route --geojson` writes a route Feature, and `route --kml` writes a KML route
document. `export --format kml` exports matching port records. Programmatic KML
exports accept either a `SeaRoute` or `SequenceSeaRoute`:

```python
from harborly.kml import write_route_kml

write_route_kml(route, "route.kml")
```

`export --format geoparquet` exports matching port records, and the
`harborly.geoparquet` module writes both port and route files. They use WKB
geometry, CRS `OGC:CRS84`, and GeoParquet 1.0.0 metadata.

```python
from harborly.geoparquet import write_ports_geoparquet, write_route_geoparquet

write_route_geoparquet(route, "route.geoparquet")
write_ports_geoparquet([origin, destination], "ports.geoparquet")
```

`route --html-map` requires the `map` extra. Directly opened files render the
embedded Natural Earth 110m coastline; when served over HTTP or HTTPS, the map
also enables an OpenStreetMap tile layer. The generated file can still load
front-end assets from CDNs, so it is not a fully offline application.

The `tui` command requires the `tui` extra and opens a Textual terminal search
interface with an embedded-coastline braille world map. It starts in insert
mode. Press `Esc` for browse mode, then use `+`/`-` to zoom, `h`/`j`/`k`/`l` to
pan, `g` to center on the selected port, `0` to reset, and `i` to return to
search. It is a search visualisation, not a navigation chart.

## Data sources and local builds

The bundled registry is derived from NGA World Port Index (WPI) and GeoNames.
It does not redistribute raw source archives. Its manifest records source
labels, URLs, sizes, and SHA-256 digests. A local reference build can add
UN/LOCODE data and a user-provided OpenStreetMap GeoJSON export.

| Source | Use and limitation |
| --- | --- |
| NGA WPI | Names, aliases, coordinates, and UN/LOCODE links. |
| UNECE UN/LOCODE | Local-build port-function records, codes, names, status, and optional coordinates; it is not a berth database. |
| GeoNames | Bundled maritime feature candidates; provider-specific coordinates never overwrite another source. GeoNames attribution is required. |
| OpenStreetMap | Optional local source only. It is never downloaded by Harborly and retains ODbL obligations. |

Build a local reference registry with `harborly data download` then
`harborly data build`, or run both with `harborly data prepare`. Existing
snapshots are reused unless `--refresh` is supplied. Use `data lock` to write a
source lockfile and `data build --lock PATH` to verify raw snapshots before a
build. `data verify` validates the local reference build; it does not verify
the compact registry embedded in the installed wheel.

OpenStreetMap data is opt-in. Place a GeoJSON port export under
`data/reference/raw/osm/<label>/` before `harborly data build`; eligible point
features become `OPENSTREETMAP` provider records.

Registry counts are counts of source records, not a claim of global port
coverage or unique physical ports. Source coordinates can disagree because they
describe different facilities, use different precision, or contain upstream
errors. Search, fuzzy matching, and nearest-port results are candidate evidence;
record an explicit source-ID decision before replacing an identity in data.

The routing backend does not expose the graph point to which it snaps an
endpoint. Harborly therefore retains the submitted endpoints and does not claim
an inferred snap as observed data. Routes do not account for draft, depth,
weather, vessel class, local rules, closures, or navigational hazards.
