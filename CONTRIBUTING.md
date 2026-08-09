# Contributing

Thanks for improving Harborly.

## Code of conduct

### Standards and scope

Treat everyone respectfully and constructively: welcome newcomers, give feedback
on the work rather than the person, accommodate different experience levels,
and assume good faith. Harassment, personal or political attacks, demeaning or
discriminatory comments, publishing private information, and sustained
disruption are not acceptable.

This applies in all project spaces, including issues, pull requests,
discussions, and public representation of the project.

### Reporting and enforcement

Report conduct concerns privately to the maintainers through GitHub private
vulnerability reporting or by direct message to the repository owner. Reports
are handled confidentially. Maintainers may warn a participant, remove content,
or block a participant; they will explain the decision to the reporter.

## Development setup

See [Getting Started](docs/GETTING-STARTED.md) for prerequisites and first-run
instructions. For the full contributor environment, install the development,
audit, and optional-feature dependencies:

```bash
uv sync --locked --all-extras --group audit
```

## Coding standards

- Format Python with Ruff: `uv run ruff format src tests scripts`.
- Check formatting and lint with `uv run ruff format --check src tests scripts`
  and `uv run ruff check src tests scripts`.
- Type-check package code with `uv run mypy src`.
- Run `uv run python scripts/check_docs.py` when documentation changes.

CI enforces the formatting, linting, documentation, type-checking, and test
commands on pull requests to `main`.

## Pull requests

- Target `main`. No contributor branch-naming convention is documented; use a
  short, descriptive branch name.
- Use an imperative commit subject and explain user-visible behavior and its
  reason in the commit body.
- Add or update tests for behavior changes, then run `uv run pytest -q`.
- Run the Ruff, Mypy, and documentation checks in the PR template before
  requesting review.
- Keep public names, CLI commands, and JSON output documented, and comply with
  the [public compatibility contract](#public-compatibility-contract).
- Complete the PR summary and change list so reviewers can verify the intent
  and scope.

## Issue reporting

Use [GitHub Issues](https://github.com/frogiraffe/harborly/issues) for bugs and
feature requests.

- For bugs, include the observed and expected behavior, a minimal reproduction,
  relevant input, Harborly and Python versions, operating system, installed
  extras, and the full output or error.
- For feature requests, describe the problem, proposed capability, and any
  impact on the public Python API, CLI, output schema, registry format, or data
  sources.

## Security

Report suspected vulnerabilities through the private
[security advisory form](https://github.com/frogiraffe/harborly/security/advisories/new),
not in a public issue or pull request before a fix is available. Include the
affected Harborly version, operating system, Python version, installed extras,
the smallest reproducing input or command, and observed impact.

Harborly parses external CSV, ZIP, JSON, GeoJSON, and Parquet data. Consider
malformed-input denial of service, resource exhaustion, archive or parser
defects, dependency compromise, path handling errors, and upstream data
tampering when reporting or reviewing a vulnerability. Recorded SHA-256 source
digests protect a downloaded snapshot after its first download; they do not
authenticate the upstream server or establish that initial trust.

Release artifacts use GitHub Actions and PyPI Trusted Publishing, with workflow
actions pinned to commit SHAs. The repository does not define an EOL table for
released package versions. Harborly uses semantic versioning, and the 1.x
contract below identifies the maintained public interfaces. CI validates Python
3.11 through 3.14 on Linux, plus Python 3.14 on macOS and Windows; it also runs
the complete suite on Python 3.11 with declared minimum direct dependencies.

## Public compatibility contract

Harborly uses semantic versioning. The following contracts apply throughout the
1.x series.

### Python API

The names in `harborly.__all__` are stable: `AmbiguousPortError`,
`AsyncSeaRouter`, `BackendError`, `BackendErrorKind`, `BatchMatchResult`,
`CacheFailurePolicy`, `CanonicalEvidence`, `ConfidenceTier`, `MatchPolicy`,
`MatchReason`, `MatchStatus`, `PassageRestriction`, `Port`,
`PortCoordinateError`, `PortGroup`, `PortNotFoundError`, `PortRegistry`,
`RegistryDataError`, `RetryPolicy`, `RouteQualityFlag`, `RouteQualityPolicy`,
`RoutingError`, `HarborlyError`, `SeaRoute`, `SeaRouter`, `SequenceSeaRoute`,
and `SourceDataError`.

These lower-level APIs are also stable within 1.x:

- `harborly.kml.to_kml_string(route)` and
  `harborly.kml.write_route_kml(route, path)`
- `harborly.geoparquet.write_ports_geoparquet(ports, path)` and
  `harborly.geoparquet.write_route_geoparquet(route, path)`

Breaking signature changes, removals, or incompatible semantic changes require
a major version. `SeaRouter.distance_matrix` remains the dense-matrix API;
`SeaRouter.iter_distance_edges` is its bounded-memory streaming counterpart and
yields `(row_index, column_index, distance_nmi)` in deterministic order. Names
outside `harborly.__all__` are implementation interfaces unless another
document explicitly defines them as public.

### CLI and JSON output

Documented commands, arguments, and exit status values are stable within 1.x.
Text-table formatting and error wording may change, so scripts should use
`--json`. The `route --kml` flag and `export --format kml` and
`export --format geoparquet` are stable 1.x CLI options.

`schema_version` identifies the JSON format. New optional fields may be added
within schema version 1; removing a field, changing its type, or incompatibly
changing an enum requires a new schema version. Integrations must use
`error.code` and structured `details`; `message` is not stable.

### Registry and GIS exports

`registry_schema_version` identifies the processed Parquet format, and
`PortRegistry.from_directory` rejects unsupported versions. Registry contents,
record counts, aliases, coordinates, and provider coverage may change with
source snapshots and are not API constants.

KML output follows KML 2.2, with `MultiLineString` geometries encoded as a KML
`<MultiGeometry>`. GeoParquet output follows GeoParquet 1.0.0, uses OGC WKB for
the geometry column, represents OGC:CRS84 as `crs=null`, and always includes
the `geo` metadata key. New optional GIS-export columns may be added in 1.x.
