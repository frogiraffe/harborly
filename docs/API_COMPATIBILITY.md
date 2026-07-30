# API compatibility

sea-mile uses semantic versioning. The following interfaces are maintained
throughout the 1.x series.

## Python API

The names in `sea_mile.__all__` are stable:

`AmbiguousPortError`, `BackendError`, `BackendErrorKind`, `BatchMatchResult`,
`CacheFailurePolicy`, `CanonicalEvidence`, `ConfidenceTier`, `MatchPolicy`,
`MatchReason`, `MatchStatus`, `Port`, `PortCoordinateError`, `PortGroup`,
`PortNotFoundError`, `PortRegistry`, `RegistryDataError`, `RetryPolicy`,
`RouteQualityFlag`, `RouteQualityPolicy`, `RoutingError`, `SeaMileError`,
`SeaRoute`, `SeaRouter`, and `SourceDataError`.

Breaking signature changes, removals, and incompatible semantic changes require
a major version.

## Removed in 2.0

Each entry below had two spellings: a policy object and a loose keyword ladder
that predated it. Two ways to say the same thing means two things to document,
two to validate, and an unstated question about which one wins. 2.0 keeps the
policy objects and removes the ladders. There is no transition shim — the old
spellings raise `TypeError`, so a caller finds out at the call rather than
silently getting a default.

| Removed | Replacement |
| --- | --- |
| `SeaRouter(retry_attempts=...)` | `SeaRouter(retry_policy=RetryPolicy(attempts=...))` |
| `SeaRouter(backoff_seconds=...)` | `SeaRouter(retry_policy=RetryPolicy(base_backoff_seconds=...))` |
| `SeaRouter.retry_attempts` | `SeaRouter.retry_policy.attempts` |
| `SeaRouter.backoff_seconds` | `SeaRouter.retry_policy.base_backoff_seconds` |
| `assess_route_length(..., high_detour_ratio=...)` | `assess_route_length(..., policy=RouteQualityPolicy(high_detour_ratio=...))` |
| `assess_route_length(..., lower_bound_tolerance_nmi=...)` | `assess_route_length(..., policy=RouteQualityPolicy(lower_bound_tolerance_nmi=...))` |
| `GET /route`, `GET /healthz` | `GET /v1/route`, `GET /v1/livez` |

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
