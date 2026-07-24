# Library API

This page describes the public API of `sea_mile`. The library builds a local port
registry, searches it, and calculates an approximate sea route. Routing uses the
searoute package.

## Public API surface

The stable top-level exports are the core types: `Port`, `PortGroup`, `PortRegistry`,
`SeaRoute`, `SeaRouter`, `BatchMatchResult`, `MatchStatus`, `ConfidenceTier`,
`MatchReason`, `RouteQualityFlag`, and the `SeaMileError` family (`RegistryDataError`,
`SourceDataError`, `PortNotFoundError`, `AmbiguousPortError`, `PortCoordinateError`,
`RoutingError`).

Lower-level APIs are imported from their defining modules:

- `sea_mile.geo`: `validate_coordinate`, `CoordinateCheck`, `great_circle_nmi`.
- `sea_mile.text`: `canonical_key`, `normalize_display_text`.
- `sea_mile.sources`: `parse_wpi_dms`, `parse_unlocode_coordinates`.
- `sea_mile.matching`: `decide_exact_match`, `ExactMatchDecision`, `MatchCandidate`.
- `sea_mile.ports`: `PortSearchResult`, `NearbyPortResult`, `NearbyPortGroup`.
- `sea_mile.canonical`: `assign_canonical_ids`.
- `sea_mile.build`: `build_reference_registry`, `download_reference_data`.

## Data lifecycle

The wheel includes a registry derived from WPI and GeoNames:

```python
from sea_mile import PortRegistry

registry = PortRegistry.bundled()
```

`PortRegistry.from_directory(path)` loads an alternate processed registry.

The CLI selects `--data-dir`, `SEA_MILE_DATA_DIR`,
`data/reference/processed` in the current directory, then the bundled registry.

A local build adds UN/LOCODE and may add a local OpenStreetMap export:

```bash
sea-mile data download
sea-mile data build
```

`sea-mile data prepare` executes both operations. Existing snapshots are reused
unless `--refresh` is specified. `--json` returns the complete manifests.

The Python calls are `download_reference_data` and `build_reference_registry`:

```python
from sea_mile.build import build_reference_registry, download_reference_data

download_reference_data("reference")
build_reference_registry("reference")
```

`sea-mile data verify` checks a local build. `verify_reference_data` in
`sea_mile.validation` returns the same report.

The build manifest records a `registry_schema_version` and a deterministic
`registry_content_hash`. When it loads a directory, `PortRegistry.from_directory` reads
the manifest and refuses a schema version this build of sea-mile does not support,
rather than failing later on a missing or renamed column. The content hash is
order-independent, so a rebuild from the same sources produces the same hash.

`sea-mile data lock` writes `sea-mile.lock.json` from the download manifest, pinning
each source's URL, snapshot label, size, and SHA-256. `sea-mile data build --lock`
verifies local raw snapshots before building and aborts on a mismatch. The
`write_source_lock`, `load_source_lock`, and `lock_mismatches` functions in
`sea_mile.build` expose the same behavior.

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
`unique_exact_unlocode`, `coordinate_conflict`, `multiple_identities`, and
`no_candidate`, plus `manual_decision` when the CLI review workflow applies a
reviewed choice.

Each result also carries `candidates`, a tuple of `MatchCandidate` records. Each holds
the `registry_id`, `provider`, `name`, `country_code`, coordinates, and `unlocode` of
one exact match that informed the decision, so a review step can show the evidence
behind a `review_required` or `unresolved` outcome. It also carries `rules_applied`, the
ordered tuple of decision-rule tokens that fired, such as `single_exact_wpi` then
`coordinate_conflict_detected`.

`match_names` delegates each decision to `decide_exact_match`. A single exact WPI
match and a single exact UN/LOCODE match are not necessarily the same physical
port. Places can share a name within one country, including locations separated
by hundreds of nautical miles. Candidate coordinates allow
`decide_exact_match` to return an `ExactMatchDecision` with review status instead
of selecting a conflicting record. Call `decide_exact_match` directly when
candidate ID lists are already available.

### Matching pandas frames and large files

`match_series` takes a pandas Series of names and returns the same `BatchMatchResult`
list as `match_names`. It reads a missing cell as an empty name.

```python
results = registry.match_series(frame["port_name"], country_codes=frame["country"])
```

`match_dataframe` returns a copy of a frame with eight appended columns:
`sea_mile_status`, `sea_mile_reason_code`, `sea_mile_registry_id`, `sea_mile_name`,
`sea_mile_country_code`, `sea_mile_latitude`, `sea_mile_longitude`, and
`sea_mile_unlocode`. These are the same columns that `sea-mile match --output` writes.

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

The `sea-mile match --output` command streams the same way. It reads the input in
chunks and appends each block to the output file, so it does not load the whole input
either.

## Sea routes

```python
from sea_mile import SeaRouter

router = SeaRouter()
route = router.route(origin, destination)
route.summary()
route.to_geojson_feature()

router.route_coordinates(36.8, 34.65, 37.94, 23.63)
router.route_many([(origin, destination)])
router.distance_matrix([origin, destination])
```

The default settings use the searoute A* algorithm, the NetworkX backend, the
`northwest` passage restriction, and explicit nautical-mile units. A `SeaRoute` holds:

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
to its routing network. sea-mile therefore does not report or estimate snapped
coordinates. A route retains the submitted origin and destination and does not
present an inferred snapped point as observed data.

`route_ids` routes two registry IDs. `route_coordinates` routes two raw `lat, lon`
points without a registry lookup. `route_many` routes a list of port pairs.
`distance_matrix` returns the pairwise sea distance for a list of ports. Routing needs
the `routing` extra. `SeaRouter` imports without it, but a route call raises
`ImportError` when it is missing.

## Coordinates and text helpers

`validate_coordinate` returns a `CoordinateCheck` and rejects missing, non-numeric,
out-of-range, and (0, 0) coordinates. `great_circle_nmi` returns the Haversine
distance in nautical miles using the 6,371.0087714 km mean Earth radius.

`canonical_key` builds an accent-insensitive search key. `normalize_display_text`
normalizes Unicode and whitespace but keeps accents. `parse_wpi_dms` and
`parse_unlocode_coordinates` parse the two source coordinate formats and return `None`
for an out-of-range value.

## Error types

Every recoverable public error is a subclass of `SeaMileError`:

- `RegistryDataError`, the local registry files are missing or invalid.
- `SourceDataError`, a public snapshot could not be downloaded or read.
- `PortNotFoundError`, no port matches the identifier or exact name.
- `AmbiguousPortError`, more than one independent port identity matches.
- `PortCoordinateError`, a selected port has no usable routing coordinate.
- `RoutingError`, the routing backend failed, returned an unusable result, or produced
  a route that fails the plausibility check. Its `reason` attribute carries a stable
  token: `backend_call_failed`, `malformed_backend_result`, or
  `implausible_route`. Programmatic error handling must use this token rather
  than the message.

The CLI prints each error to `stderr` and exits with status code 2.
