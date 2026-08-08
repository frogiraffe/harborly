# Changelog

All notable user-visible changes are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [1.1.2] - 2026-08-08

### Changed

- Consolidated public and maintainer documentation into focused guides.
- Renamed the CLI registry override to `HARBORLY_DATA_DIR`.

### Fixed

- Removed the mismatched PyPI environment claim from trusted publishing.

## [1.1.1] - 2026-08-07

### Added

- Ordered CLI waypoints through repeatable `route --via`, with typed passage
  restrictions derived from `PassageRestriction`.
- `matrix --speed-knots` duration output for JSON, tables, and streamed edge CSV.
- Async parity methods for route IDs, coordinate routes, and batch routing.

### Changed

- Async edge iteration now streams through a bounded, cancellation-aware bridge.
- Vessel speed must be finite and positive across CLI, synchronous, and asynchronous
  routing entry points.
- GIS exporters now have end-to-end KML topology, XML escaping, GeoParquet WKB, and
  CLI artifact verification.

### Fixed

- Matrix workers preserve the configured cache failure policy.
- Multi-format route exports stage atomically and reject duplicate output paths.
- The optional API release smoke uses the versioned `/v1/livez` endpoint.
- Release security scanning no longer flags the HTML-map type narrowing path.

## [1.0.0] - 2026-08-06

### Added

- Source-aware port identity resolution supporting WPI, UN/LOCODE, and GeoNames.
- Exact, prefix, fuzzy, proximity, and country-filtered port search.
- Analytical sea routing using the `searoute` maritime graph.
- Bounded-memory distance matrix calculation and streaming (`iter_distance_edges`, `matrix --edge-csv`).
- Fast SQLite persistent route caching with WAL mode and cache maintenance commands (`cache info`, `cache prune`, `cache clear`).
- CSV matching engine with human-in-the-loop decision review workflow (`harborly match`).
- FastAPI HTTP service (`harborly serve`) with `/v1/livez`, `/v1/readyz`, and `/v1/route` endpoints.
- Interactive Terminal UI (`harborly tui`) with braille world map visualization.
- GeoJSON export and standalone HTML route map generation with bundled coastlines.
- Reproducible data pipeline (`harborly data download`, `build`, `prepare`, `verify`, `lock`).
- AsyncSeaRouter: async/await drop-in for SeaRouter (route, route_sequence, route_ids, route_many, distance_matrix, iter_distance_edges).
- PassageRestriction enum: restrict Suez, Panama, Kiel, Baban, Northwest passages via `SeaRouter(restrictions=[...])`.
- route_sequence(): multi-leg routing over an ordered list of Port objects, returns SequenceSeaRoute with per-leg SeaRoute and aggregated totals.
- SequenceSeaRoute: legs, total_distance_nmi, total_great_circle_nmi, duration_hours, duration_days, to_kml(), write_kml(), to_geojson_feature_collection().
- speed_knots, duration_hours, duration_days on SeaRoute: pass speed_knots to compute ETA.
- KML export: `harborly route --kml route.kml`, `harborly export --format kml`. Programmatic access via `harborly.kml`.
- GeoParquet export: `harborly export --format geoparquet` (OGC WKB, CRS OGC:CRS84, GeoParquet 1.0.0 spec). Programmatic access via `harborly.geoparquet`.

[1.1.2]: https://github.com/frogiraffe/harborly/releases/tag/v1.1.2
[1.1.1]: https://github.com/frogiraffe/harborly/releases/tag/v1.1.1
[1.0.0]: https://github.com/frogiraffe/harborly/releases/tag/v1.0.0
