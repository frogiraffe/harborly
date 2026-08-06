# Changelog

All notable user-visible changes are documented here. The project follows
[Semantic Versioning](https://semver.org/).

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

[1.0.0]: https://github.com/frogiraffe/harborly/releases/tag/v1.0.0
