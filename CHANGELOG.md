# Changelog

All notable changes to sea-mile are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic
versioning.

## [Unreleased]

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
