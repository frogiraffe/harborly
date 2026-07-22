# Changelog

All notable changes to sea-mile are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic
versioning.

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
  match, tui, and data commands, plus JSON output on every command.
- A data verify command that checks a local build against its manifests.
- A typed public API, property tests for the parsers and coordinate math, and a
  benchmark for search and nearest.
