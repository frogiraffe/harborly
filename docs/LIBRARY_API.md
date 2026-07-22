# Library API

This page describes the public API of `sea_mile`. The library builds a local port
registry, searches it, and calculates an approximate sea route. Routing uses the
searoute package.

## Data lifecycle

The wheel does not include a port registry. You build your own local copy:

```bash
sea-mile data download
sea-mile data build
```

Run both steps together with `sea-mile data prepare`. `download` reuses an existing
snapshot. Pass `--refresh` to download the sources again. Both commands print a short
readable summary. Pass `--json` to print the full manifests.

An installed library writes the registry under
`~/.local/share/sea-mile/reference/`. In a checkout with a `data/reference/` folder,
the CLI uses that folder. Set the `SEA_MILE_DATA_DIR` environment variable to point
the read commands at a different processed registry.

The Python calls are `download_reference_data` and `build_reference_registry`:

```python
from sea_mile import build_reference_registry, download_reference_data

download_reference_data("reference")
build_reference_registry("reference")
```

`sea-mile data verify` checks a local build. The `verify_reference_data` function in
`sea_mile.validation` returns the same report.

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

This search finds candidate ports. It does not prove that a named place is the correct
port. Check the name, the country, the function code, the source, and a map before you
accept a result.

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
human `reason`. The `status` is a `MatchStatus` value, the `confidence_tier` is a
`ConfidenceTier` value from `A` to `D`, and the `reason_code` is a `MatchReason` value.
Branch automation on `reason_code`, not on the `reason` text, which may change. The
`MatchReason` values are `unique_exact_wpi`, `unique_exact_unlocode`,
`coordinate_conflict`, `multiple_identities`, and `no_candidate`.

Each result also carries `candidates`, a tuple of `MatchCandidate` records. Each holds
the `registry_id`, `provider`, `name`, `country_code`, coordinates, and `unlocode` of
one exact match that informed the decision, so a review step can show the evidence
behind a `review_required` or `unresolved` outcome.

`match_names` uses `decide_exact_match` under the hood. A single exact WPI match and a
single exact UN/LOCODE match are not always the same physical port. Real places can
share a name within one country, for example two United States places named "Hamilton"
that are hundreds of nautical miles apart. `match_names` passes the candidate
coordinates so `decide_exact_match` can catch this and return an `ExactMatchDecision`
with a review status instead of resolving to the wrong record. Call `decide_exact_match`
directly when you already have candidate ID lists.

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
- the routing engine name, version, algorithm, backend, and restrictions.
- the origin and destination provider records.
- a GeoJSON LineString geometry, on export.

A route shorter than the great-circle lower bound, beyond a small tolerance, is
rejected. A route with a large detour ratio is still returned with a
`high_detour_ratio` quality flag for a manual check. `SeaRouter` memoizes results per
instance, keyed on the ports and the config.

`route_ids` routes two registry IDs. `route_coordinates` routes two raw `lat, lon`
points without a registry lookup. `route_many` routes a list of port pairs.
`distance_matrix` returns the pairwise sea distance for a list of ports. Routing needs
the `routing` extra. `SeaRouter` imports without it, but a route call raises
`ImportError` when it is missing.

## Coordinates and text helpers

`validate_coordinate` returns a `CoordinateCheck` and rejects missing, non-numeric,
out-of-range, and (0, 0) coordinates. `great_circle_nmi` returns the Haversine distance
in nautical miles.

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

The CLI prints each error to `stderr` and exits with status code 2.
