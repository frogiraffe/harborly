# Stability policy

sea-mile follows semantic versioning. This page states what is stable at 1.0, what may
still change, and how long a deprecation lasts. It is the contract you integrate against.

## What is frozen at 1.0

These surfaces do not change in a breaking way without a major version bump.

- **The public Python API.** The names in `sea_mile.__all__`: `Port`, `PortGroup`,
  `PortRegistry`, `SeaRoute`, `SeaRouter`, `BatchMatchResult`, `MatchStatus`,
  `ConfidenceTier`, `MatchReason`, `RouteQualityFlag`, and the `SeaMileError` family
  (`RegistryDataError`, `SourceDataError`, `PortNotFoundError`, `AmbiguousPortError`,
  `PortCoordinateError`, `RoutingError`).
- **The CLI.** The command names (`info`, `search`, `show`, `near`, `route`, `matrix`,
  `export`, `match`, `tui`, and the `data` subcommands), their documented flags, and the
  exit codes (0 success, 1 `data verify` reported failures, 2 usage or data or resolution
  or dependency error).
- **The JSON envelope.** `schema_version` 1 and the field set of every command's `data`
  and `error`, as recorded in [Output schemas](OUTPUT_SCHEMAS.md) and
  [Data dictionary](DATA_DICTIONARY.md). A breaking change to the shape bumps
  `schema_version`, not the field meanings under 1.
- **The error codes** on every public exception.
- **The registry schema version.** A build stamps `registry_schema_version` and a reader
  refuses a version it cannot read, so a stored registry never loads as the wrong shape.

## What may still change

- **The internal module layout.** Modules outside `sea_mile.__all__` may move. A move
  keeps a deprecation shim at the old path for one minor release before removal.
- **The normalized registry content.** A new source snapshot changes the records. The
  build is reproducible from a lockfile, but the numbers are not a stable API.
- **Human-readable text output.** The table and summary text is for people, not
  automation. Automation uses `--json`.
- **Benchmark numbers.** [Performance](PERFORMANCE.md) records a reference machine. The
  figures track the code and the hardware.

## Supported environments

- **Python** 3.11, 3.12, and 3.13, tested in CI on every change.
- **Operating systems** Linux, macOS, and Windows, tested in CI on every change.
- **Dependencies** the core install needs `httpx`, `pandas`, `pyarrow`, `rapidfuzz`, and
  `tenacity`. Sea routing, the terminal UI, the k-d tree, and the verify cross-check are
  optional extras.

## Deprecation policy

A public name that is going away first warns with a `DeprecationWarning` for one minor
release, with the replacement named in the message, and is removed no earlier than the
next minor release. The relocated 0.7 modules and the removed top-level names follow this
schedule. See [Migration](MIGRATION.md).

## Security

Report a vulnerability as described in [SECURITY.md](../SECURITY.md). Recorded SHA-256
values are provenance and integrity for a downloaded snapshot, not authentication of the
first download.
