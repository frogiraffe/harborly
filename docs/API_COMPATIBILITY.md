# API compatibility

sea-mile uses semantic versioning. The following interfaces are maintained
throughout the 1.x series.

## Python API

The names in `sea_mile.__all__` are stable:

`AmbiguousPortError`, `AsyncSeaRouter`, `BackendError`, `BackendErrorKind`, `BatchMatchResult`,
`CacheFailurePolicy`, `CanonicalEvidence`, `ConfidenceTier`, `MatchPolicy`,
`MatchReason`, `MatchStatus`, `PassageRestriction`, `Port`, `PortCoordinateError`, `PortGroup`,
`PortNotFoundError`, `PortRegistry`, `RegistryDataError`, `RetryPolicy`,
`RouteQualityFlag`, `RouteQualityPolicy`, `RoutingError`, `SeaMileError`,
`SeaRoute`, `SeaRouter`, `SequenceSeaRoute`, and `SourceDataError`.

### Lower-level modules

The following module-level APIs are stable within 1.x:
- sea_mile.kml: to_kml_string(route), write_route_kml(route, path)
- sea_mile.geoparquet: write_ports_geoparquet(ports, path), write_route_geoparquet(route, path)

Breaking signature changes, removals, and incompatible semantic changes require
a major version.

`SeaRouter.distance_matrix` remains the dense matrix API.
`SeaRouter.iter_distance_edges` is its bounded-memory streaming counterpart and
yields `(row_index, column_index, distance_nmi)` tuples in deterministic order.

Modules and names not exported through `sea_mile.__all__` are implementation
interfaces unless another document explicitly defines them as public.

## Command-line interface

Documented commands, arguments, and exit status values are stable within 1.x.
Text tables and error wording may change without a major version. Scripts should
use `--json`.

`--kml` on `route` and `--format kml` / `--format geoparquet` on `export` are stable 1.x CLI flags.

## JSON output

`schema_version` identifies the JSON format. New optional fields may be added
within schema version 1. Removing a field, changing its type, or changing an
enum incompatibly requires a new schema version.

Error handling is defined by `error.code` and structured `details`; `message` is
not stable.

## Registry format

`registry_schema_version` identifies the processed Parquet format.
`PortRegistry.from_directory` rejects unsupported versions. Registry contents,
record counts, aliases, coordinates, and provider coverage may change with source
snapshots and are not API constants.

## GIS export formats

- KML output follows the KML 2.2 schema. MultiLineString geometries are encoded as KML <MultiGeometry>.
- GeoParquet output follows the GeoParquet 1.0.0 specification. Geometry column uses OGC WKB encoding. CRS is OGC:CRS84 (lon/lat WGS84, crs=null per spec). The geo metadata key is always present in Parquet schema metadata.
- These formats are additive in 1.x; new optional columns may be added without a major version.

## Supported environments

CI validates Python 3.11, 3.12, 3.13, and 3.14 on Linux. Python 3.14 is also
validated on macOS and Windows. The complete suite also runs on Python 3.11
with the declared minimum direct dependencies. Dependency constraints and
update rules are described in [Dependency policy](maintainers/DEPENDENCY_POLICY.md).

Security reports follow [SECURITY.md](../SECURITY.md).
