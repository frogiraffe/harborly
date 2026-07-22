# Changelog

All notable changes to sea-mile are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic
versioning.

## [Unreleased]

### Fixed

- `data prepare --json` now prints one valid JSON document, with `download` and
  `build` keys, instead of two concatenated objects that a JSON parser cannot read.
- The `matrix` command now requires two or more ports, matching its help text,
  instead of accepting a single port and returning a one-by-one matrix.

### Changed

- Scoped the README JSON note to the commands that emit JSON, and documented the
  CLI exit codes.

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
