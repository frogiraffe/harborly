# Changelog

All notable changes to sea-mile are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic
versioning.

## [Unreleased]

### Added

- A `registry_schema_version` and a deterministic `registry_content_hash` in the build
  manifest, plus a load-time check that refuses a processed registry whose schema this
  build of sea-mile cannot read. The content hash is order-independent, so two builds
  from the same sources produce the same hash.
- A source lockfile. `sea-mile data lock` pins each source snapshot's URL, label, size,
  and SHA-256 into `sea-mile.lock.json`, and `sea-mile data build --lock` verifies the
  local raw snapshots against it before building, for an offline reproducible build that
  fails loudly on drift.
- A performance benchmark with published budgets. `scripts/benchmark.py` now reports
  peak process memory and takes a `--no-kdtree` flag that measures `nearest` on the scan
  path, and the new `docs/PERFORMANCE.md` records build time, memory, and search and
  nearest latency on a reference machine.
- Pandas-native bulk matching. `PortRegistry.match_series` matches a Series of names and
  `PortRegistry.match_dataframe` returns a frame with the eight `sea_mile_` match columns
  appended, so a matching pipeline can stay in pandas. Reading a large file in chunks and
  matching each chunk keeps the whole file out of memory.

- A `RouteQualityFlag` enum. A `SeaRoute` now carries its `quality_flag` as this stable
  enum instead of a bare string, so automation can branch on it. The value is a string
  subclass, so the JSON output and string comparisons are unchanged.

- An internal routing backend boundary. `SeaRouter` now routes through a narrow internal
  interface with a default searoute adapter, so the searoute dependency stays in one
  place and a test can supply a fake backend. A route records the backend name and
  version in `engine` and `engine_version`, and the effective routing configuration in
  `algorithm`, `backend`, and `restrictions`. The interface is internal, not a public
  extension point, and the JSON output is unchanged.
- A `RoutingError` exception, with error code `routing_error`. A routing backend that
  fails, returns an unusable result, or produces a route that fails the plausibility
  check now raises this controlled error instead of leaking a third-party exception. It
  carries a stable `reason`, one of `backend_call_failed`, `malformed_backend_result`, or
  `implausible_route`, exposed in the `--json` error `details`, so automation can tell the
  failure modes apart without reading the message.

### Changed

- The registry build now writes its Parquet files and manifest through temporary files
  and an atomic rename, so a failed build no longer leaves a half-written registry.
- A route that fails the plausibility check now raises `RoutingError` instead of
  `PortCoordinateError`, so a failed route is distinct from a bad input coordinate.
- `sea-mile match` now reads its input in chunks and appends the `--output` and `--review`
  rows as it goes, so a large input no longer loads into memory all at once. The written
  output is unchanged.
- The top-level `sea_mile.__all__` now lists the core types only, so the advertised public
  surface is smaller. The names it dropped still import from `sea_mile` with a warning for
  one release. See Deprecated below and the Public API surface section in the library docs.
- Grouped the internal modules ahead of 1.0. String normalization moved to `sea_mile.text`,
  the coordinate and distance rules to `sea_mile.geo`, the source parsers under a
  `sea_mile.sources` package, and registry building and downloading under a `sea_mile.build`
  package. The old module paths still work for one release and warn on import.

### Deprecated

- Importing these lower-level helpers from the top-level `sea_mile` namespace now warns and
  will stop working after one release. Import them from the module named here instead.
  - `sea_mile.geo`: `validate_coordinate`, `CoordinateCheck`, `great_circle_nmi`.
  - `sea_mile.text`: `canonical_key`, `normalize_display_text`.
  - `sea_mile.sources`: `parse_wpi_dms`, `parse_unlocode_coordinates`.
  - `sea_mile.matching`: `decide_exact_match`, `ExactMatchDecision`, `MatchCandidate`.
  - `sea_mile.ports`: `PortSearchResult`, `NearbyPortResult`, `NearbyPortGroup`.
  - `sea_mile.canonical`: `assign_canonical_ids`.
  - `sea_mile.build`: `build_reference_registry`, `download_reference_data`.
- The old module paths for the relocated modules now warn on import and will be removed
  after one release. `sea_mile.normalization` is now `sea_mile.text`, `sea_mile.quality` is
  now `sea_mile.geo`, `sea_mile.reference`, `sea_mile.geonames`, and `sea_mile.osm` are now
  under `sea_mile.sources`, and `sea_mile.registry_build` and `sea_mile.source_data` are now
  under `sea_mile.build`.

## [0.3.0] - 2026-07-23

The first hardened release since 0.1.0. It makes the `--json` output a versioned,
schema-checked contract, adds explainable and reviewable bulk matching, and ships a
curated regression dataset. It carries the breaking JSON-envelope change, which is
allowed before 1.0.

### Added

- A curated golden identity dataset under `tests/golden/` and a test that runs it,
  asserting each labeled outcome and the bulk-matching precision, recall, and
  review-rate thresholds. It covers same-name ports, terminal versus city, accents,
  transliterations, historic names, coordinate conflicts, and missing coordinates.
- A `match` review workflow. `--output` writes the input rows back with appended
  `sea_mile_*` columns, `--review` writes the rows needing a human one row per
  candidate, and `--decisions` applies a reviewed `row_id`/`chosen_registry_id` file,
  marking those rows `manually_resolved`. `--id-column` names a stable input id.
- `docs/OUTPUT_SCHEMAS.md` documenting the JSON envelope, the `data` shape of each
  command, and the error codes.
- `docs/schemas/envelope-1.schema.json`, a JSON Schema for the envelope that the test
  suite validates the output of every `--json` command against.
- A stable machine-readable `code` on every public exception.
- A stable `reason_code` (the `MatchReason` enum) on every `BatchMatchResult` and in
  the `match --json` output, so automation can branch on the decision reason instead of
  the human `reason` text.
- A `candidates` list of `MatchCandidate` records on every `BatchMatchResult` and in the
  `match --json` output, exposing the exact records that informed each decision.
- A `rules_applied` trace on every `BatchMatchResult` and in the `match --json` output,
  recording the ordered decision-rule tokens that produced each outcome.
- Documented the `match` status, confidence-tier, and reason-code values, and the
  `route` quality flags.

### Changed

- CLI `--json` output is now a versioned envelope with `schema_version`, `command`,
  `data`, and `warnings`. A recoverable error emits the same envelope with an `error`
  object that holds a stable `code`, a `message`, and `details`, printed to stdout with
  exit code 2. Anything that parsed the previous bare JSON must now read the `data`
  field. See `docs/OUTPUT_SCHEMAS.md`.
- Scoped the README JSON note to the commands that emit JSON, and documented the
  CLI exit codes.

### Fixed

- `data prepare --json` now prints one valid JSON document, with `download` and
  `build` keys, instead of two concatenated objects that a JSON parser cannot read.
- The `matrix` command now requires two or more ports, matching its help text,
  instead of accepting a single port and returning a one-by-one matrix.
- The `route` summary now reports `restrictions` as a JSON array, so the JSON output
  round-trips through a parser unchanged.

### Removed

- The `--json` flag on `export` and `tui`, which those commands accepted but then
  ignored. `export` selects its output with `--format`, and `tui` is interactive.

## 0.1.0

First public release.

### Added

- Local port registry built from NGA World Port Index, UNECE UN/LOCODE, and
  GeoNames, with an optional OpenStreetMap source.
- Source-aware search with exact, prefix, and fuzzy matching, and grouped
  results that collapse records across sources into one physical port.
- Resolution by UN/LOCODE code or provider record ID, with an ambiguity guard
  when independent sources disagree on location.
- Nearest-port search, grouped or per source.
- Bulk name matching with a review flag for unsafe matches.
- Approximate sea routing over searoute, routing between raw coordinates, and a
  pairwise distance matrix.
- Command-line tool with the info, search, show, near, route, matrix, export,
  match, tui, and data commands, with `--json` output on the search, inspection,
  routing, matching, and data commands.
- A data verify command that checks a local build against its manifests.
- A typed public API, property tests for the parsers and coordinate math, and a
  benchmark for search and nearest.
