# API compatibility

sea-mile uses semantic versioning. The following interfaces are maintained
throughout the 1.x series.

## Python API

The names in `sea_mile.__all__` are stable:

`AmbiguousPortError`, `BackendError`, `BackendErrorKind`, `BatchMatchResult`,
`CanonicalEvidence`, `ConfidenceTier`, `MatchPolicy`, `MatchReason`,
`MatchStatus`, `Port`, `PortCoordinateError`, `PortGroup`,
`PortNotFoundError`, `PortRegistry`, `RegistryDataError`, `RetryPolicy`,
`RouteQualityFlag`, `RouteQualityPolicy`, `RoutingError`, `SeaMileError`,
`SeaRoute`, `SeaRouter`, and `SourceDataError`.

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

## Supported environments

CI validates Python 3.11, 3.12, 3.13, and 3.14 on Linux. Python 3.14 is also
validated on macOS and Windows. The complete suite also runs on Python 3.11
with the declared minimum direct dependencies. Dependency constraints and
update rules are described in [Dependency policy](DEPENDENCY_POLICY.md).

Security reports follow [SECURITY.md](../SECURITY.md).
