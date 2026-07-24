# sea-mile

sea-mile is a Python library and command-line interface for source-aware port
identity resolution and approximate analytical sea-route distances. It provides:

- a bundled registry derived from NGA World Port Index and GeoNames;
- exact, prefix, and fuzzy alias search;
- cross-source port grouping and ambiguity detection;
- nearest-port queries;
- CSV matching with an explicit review stage;
- approximate sea routes and distance matrices in nautical miles;
- CSV, GeoJSON, and JSON output.

Routing uses `searoute`. Results are suitable for analysis and map display, not
navigation, voyage planning, or safety-critical decisions.

## Installation

Install the command with routing support:

```bash
uv tool install 'sea-mile[routing]'
```

The wheel includes a 2.1 MB registry containing 20,070 WPI and GeoNames records,
so search and routing commands work without a data download.

For a source checkout:

```bash
uv sync --extra routing
uv run sea-mile info
```

`uv run` selects the project environment. It is not required after `uv tool
install` or another installation method that places `sea-mile` on `PATH`.

## Command line

The CLI loads registry data in this order:

1. `--data-dir`;
2. `SEA_MILE_DATA_DIR`;
3. `data/reference/processed` in the current checkout;
4. the registry distributed with the package.

Core commands:

| Command | Operation |
| --- | --- |
| `info` | Report registry size, provider counts, and the active data directory. |
| `search` | Rank alias matches and return one row per physical port. |
| `show` | Resolve a registry ID, canonical ID, UN/LOCODE, or exact alias. |
| `near` | Sort coordinate-bearing records using great-circle distance. |
| `route` | Calculate an approximate route between identifiers or coordinates. |
| `matrix` | Calculate pairwise route distances for two or more ports. |
| `match` | Resolve CSV rows and emit review artifacts. |
| `export` | Export selected provider records as CSV or GeoJSON. |
| `data` | Download, build, lock, or verify a local registry. |

```bash
sea-mile info
sea-mile search Mersin --country TR
sea-mile search Mersin --country TR --all-sources
sea-mile show TRMER
sea-mile near 39.87 26.16 --country TR --limit 5
sea-mile route TRMER GRPIR --geojson route.geojson
sea-mile route 36.8,34.65 37.94,23.63
sea-mile matrix TRMER GRPIR TRIST
sea-mile export --country TR --format geojson --output tr.geojson
sea-mile match ports.csv --country-column country
```

`search` and `near` return one grouped physical port per row. `--all-sources`
returns individual provider records. `--verbose` enables progress logging on
standard error.

### JSON output

`--json` emits one JSON document conforming to output schema version 1.
`schema_version` identifies the JSON format, `command` identifies the operation,
and `data` contains the result.

```json
{
  "schema_version": "1",
  "command": "search",
  "data": [],
  "warnings": []
}
```

Recoverable failures replace `data` with a structured `error` object:

```json
{
  "schema_version": "1",
  "command": "show",
  "error": {
    "code": "port_not_found",
    "message": "no exact port match",
    "details": {}
  }
}
```

Clients should check `schema_version` and use `error.code` and the documented
enum values for program logic. Error messages may change. See
[Output schemas](docs/OUTPUT_SCHEMAS.md) and
[Data dictionary](docs/DATA_DICTIONARY.md).

### Exit codes

| Status | Meaning |
| --- | --- |
| `0` | Command completed. Empty search or match results are successful. |
| `1` | `data verify` completed and reported one or more failed checks. |
| `2` | Argument validation, registry access, resolution, routing, or dependency failure. |

Diagnostics are written to standard error. JSON errors are written to standard
output when `--json` is active.

### Route metrics

`route` reports:

- `distance_nmi`: route length on the routing graph;
- `great_circle_nmi`: Haversine distance between the input coordinates;
- `detour_ratio`: `distance_nmi / great_circle_nmi`;
- routing engine, version, algorithm, backend, and restrictions;
- a route quality flag.

`great_circle_nmi` uses the Haversine formula and the 6,371.0087714 km mean
Earth radius specified by
[ITU-R P.1511-3](https://www.itu.int/rec/R-REC-P.1511/en). It is the shortest
arc between the two coordinates when Earth is approximated as a sphere. The
value does not account for land or routing restrictions, so it provides a
lower-bound check for the graph route. A 0.5-nautical-mile tolerance covers
numerical and graph-resolution effects.

### Match review

The file workflow preserves input row identity and separates deterministic
matches from manual decisions.

```bash
sea-mile match ports.csv \
  --name-column port_name \
  --country-column country \
  --id-column row_id \
  --output matched.csv \
  --review review.csv
```

`matched.csv` contains the input columns plus `sea_mile_*` result columns.
`review.csv` contains one row per candidate for rows with status
`review_required`. If `--id-column` is omitted, the input row number is used as
the stable row identifier.

Manual decisions use a CSV with two required columns:

| Column | Value |
| --- | --- |
| `row_id` | Identifier from the input or review file. |
| `chosen_registry_id` | Selected provider-qualified registry ID. |

```bash
sea-mile match ports.csv \
  --name-column port_name \
  --id-column row_id \
  --decisions decisions.csv \
  --output matched.csv
```

Applied decisions receive status `manually_resolved`. Candidate evidence and
rule tokens remain available in JSON output.

### Local registry builds

The bundled registry is sufficient for normal use. A local build adds the
official UN/LOCODE release and may include a user-supplied OpenStreetMap
GeoJSON export:

```bash
sea-mile data prepare
sea-mile data verify
```

The source download currently includes the approximately 400 MB GeoNames global
archive. Existing snapshots are reused unless `--refresh` is specified.

For a reproducible local build:

```bash
sea-mile data lock
sea-mile data build --lock sea-mile.lock.json
```

`data lock` records each source URL, snapshot label, byte size, and SHA-256
digest. `data build --lock` verifies all local raw snapshots before processing.
The lock authenticates equality with the recorded local snapshot; it does not
authenticate the initial upstream download or retrieve historical snapshots.

## Python API

```python
from sea_mile import PortRegistry, SeaRouter

registry = PortRegistry.bundled()

groups = registry.search_grouped("Mersin", country_code="TR")
origin = registry.resolve("TRMER")
destination = registry.resolve("GRPIR")
route = SeaRouter().route(origin, destination)

print(route.distance_nmi)
feature = route.to_geojson_feature()
```

Use `PortRegistry.from_directory(path)` for a locally built registry. `resolve`
accepts exact identifiers and aliases; it does not select a fuzzy match.
Conflicting identities raise `AmbiguousPortError`.

[Library API](docs/LIBRARY_API.md) documents call behavior and error semantics.
[Data dictionary](docs/DATA_DICTIONARY.md) defines the serialized fields.
[API compatibility](docs/API_COMPATIBILITY.md) defines the versioned public
interfaces.

## Data sources and licensing

The wheel contains normalized WPI and GeoNames records:

- NGA World Port Index, a United States Government work;
- GeoNames, licensed under CC BY 4.0 with attribution.

UN/LOCODE is downloaded only for local builds and is not redistributed in the
wheel. OpenStreetMap data is optional and user-supplied.

See [Sources, attribution, and limitations](docs/SOURCES_AND_LIMITATIONS.md) and
the bundled registry manifest for snapshot-level provenance.

## Development

Create the complete development environment:

```bash
uv sync --dev --extra analysis --extra fast --extra routing --extra tui
```

Run the validation suite:

```bash
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run mypy src
uv run pytest -q
uv build
```

Optional dependency groups:

| Extra | Purpose |
| --- | --- |
| `routing` | `searoute` route calculation. |
| `tui` | Textual terminal interface. |
| `fast` | SciPy k-d tree for unfiltered nearest-port queries. |
| `analysis` | PyProj cross-check used by `data verify`. |

Run `uv run python scripts/benchmark.py` for the synthetic performance suite.
See [Performance](docs/PERFORMANCE.md) for the measurement method.
