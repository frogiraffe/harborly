# sea-mile

sea-mile is a Python library and command-line tool for port search and approximate
sea-route distance. It builds a local port registry from public sources and finds
ports by name, by code, or by coordinate. It calculates an approximate sea route
between two ports in nautical miles.

Routing uses the searoute package. A sea-mile route is for analysis and map display.
Do not use it for navigation, voyage planning, or a safety decision.

## Features

- Build a local registry from NGA World Port Index, UNECE UN/LOCODE, GeoNames, and an
  optional OpenStreetMap export.
- Search port names and aliases with exact, prefix, and fuzzy matching.
- Group records from different sources into one physical port.
- Resolve a UN/LOCODE code or a provider record ID.
- Find the nearest ports to a coordinate.
- Match a CSV of port names in bulk, with a review flag for unsafe matches.
- Calculate a sea route between ports or raw coordinates, and a distance matrix.
- Export matching records as CSV or GeoJSON.
- Read machine-readable JSON from the search, inspection, routing, matching, and data
  commands with `--json`.

## Install

sea-mile uses [uv](https://docs.astral.sh/uv/). Set up the project and build the
local data:

```bash
uv sync --dev
uv run sea-mile data prepare
```

`data prepare` downloads each source once and builds two local Parquet files. Later
runs reuse the existing download. Pass `--refresh` to download the sources again. The
GeoNames archive is large, about 420 MB, and this repository does not store it.

To get a bare `sea-mile` command on your PATH, install it as a tool:

```bash
uv tool install .
sea-mile info
```

Sea routing needs the `routing` extra. Install it with `uv tool install '.[routing]'`
or `uv sync --extra routing` in the project.

## Command line

Grouped output is the default for `search` and `near`. One row is one physical port,
and the `SOURCES` column shows which providers describe it. Add `--all-sources` to see
one row per source record.

```bash
uv run sea-mile info
uv run sea-mile search Mersin --country TR
uv run sea-mile search Mersin --country TR --all-sources
uv run sea-mile show TRMER
uv run sea-mile near 39.87 26.16 --country TR --limit 5
uv run sea-mile route TRMER GRPIR --geojson route.geojson
uv run sea-mile route 36.8,34.65 37.94,23.63
uv run sea-mile matrix TRMER GRPIR TRIST
uv run sea-mile export --country TR --format geojson --output tr.geojson
uv run sea-mile match ports.csv --country-column country
uv run sea-mile data verify
```

Add `--json` for machine-readable output on `info`, `search`, `show`, `near`, `route`,
`matrix`, `match`, and the `data` commands. The `export` command selects its output
with `--format`, and `tui` is interactive, so neither takes `--json`. Add `--verbose`
before a command to log progress to stderr, and `--version` to print the version.

### Exit codes

- `0`: the command completed, including a search or match that found no results.
- `1`: `data verify` ran and one or more of its checks failed.
- `2`: a usage, data, resolution, or missing-dependency error. The message goes to
  stderr.

The `route` command prints the sea distance and the great-circle lower bound in
nautical miles, plus the detour ratio, the routing engine version, the algorithm, and
a quality flag. The origin and destination each accept a port ID, a UN/LOCODE code, or
a `lat,lon` coordinate. For example, `TRMER` (Mersin) to `GRPIR` (Piraeus) is about
594 nautical miles, and the great-circle lower bound is about 528.

The `matrix` command prints the pairwise sea distance between two or more ports. The
`export` command writes matching records as CSV or GeoJSON, for a `--query`, a
`--country`, or both. The `match` command reads a CSV with a name column and an
optional country column and prints one decision per row: `auto_resolved`,
`review_required`, or `unresolved`.

Install the `tui` extra for an interactive search:

```bash
uv sync --extra tui
uv run sea-mile tui
```

Type a name or a UN/LOCODE code, browse the grouped ports with the arrow keys, and
read the source records for the highlighted port in the detail pane.

## Python API

```python
from sea_mile import PortRegistry, SeaRouter

registry = PortRegistry.from_directory("data/reference/processed")

groups = registry.search_grouped("Mersin", country_code="TR")
origin = registry.resolve("TRMER")
destination = registry.resolve("GRPIR")
route = SeaRouter().route(origin, destination)

print(route.distance_nmi)
feature = route.to_geojson_feature()
```

Use `search` or `search_grouped` to inspect candidates first. Then pass a UN/LOCODE
code or a provider record ID such as `WPI:44860` to `resolve`. `resolve` does not
choose between two independent records when they disagree on location. It raises
`AmbiguousPortError`, and the CLI `show` and `route` commands raise the same error.

Read [Library API](docs/LIBRARY_API.md) and
[Sources and limitations](docs/SOURCES_AND_LIMITATIONS.md) for the full data contract.

## Data sources and licensing

sea-mile ships code only. It downloads each source to your machine and redistributes
no source data.

- NGA World Port Index. A work of the United States federal government.
- UNECE UN/LOCODE. Published by the UN Economic Commission for Europe.
- GeoNames. Licensed under Creative Commons Attribution 4.0. This product contains
  GeoNames data, available from https://www.geonames.org/.
- OpenStreetMap. Optional and user-supplied, licensed under the ODbL. sea-mile does
  not download it.

See [Sources and limitations](docs/SOURCES_AND_LIMITATIONS.md) for the coverage,
attribution, and routing details.

## Development

The library needs only the core dependencies. The test suite and the `scripts` folder
also need the optional extras.

```bash
uv sync --dev --extra analysis --extra tui --extra fast --extra routing
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run mypy src
uv run pytest -q
uv build
```

The extras are `routing` (searoute for sea routing), `tui` (textual for the terminal
search), `fast` (scipy for a k-d tree in `nearest`), and `analysis` (pyproj for the
`data verify` route cross-check). The demo builder in `scripts` needs the `routing`
extra.

`sea-mile data verify` recomputes the build checks from your local snapshots. It
checks the source checksums, the registry integrity rules, and the WPI and UN/LOCODE
coordinate agreement. When pyproj is installed, it also checks the `TRMER` to `GRPIR`
route against an independent WGS84 calculation.

The test suite includes `tests/test_docs_current.py`, which fails when a CLI command or
a public export is not documented, so the docs stay current with the code.
