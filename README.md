# sea-mile

**Port identity, spatial search, and analytical sea routing.**

sea-mile is a typed Python SDK and CLI for resolving real-world port identities,
finding nearby ports, reviewing ambiguous CSV matches, and calculating
approximate sea-route distances in nautical miles. The package ships with a
source-aware registry, works offline for search, and preserves the public 1.x
API while its internals evolve.

> Routes are analytical approximations on the `searoute` maritime graph. They
> are not suitable for navigation, voyage planning, or safety-critical use.

## Architecture

### Stable API, modular core

`PortRegistry` remains the public facade. Alias indexing is implemented in
`search.py`. Coordinate indexing is implemented in `spatial.py`. Registry
loading, grouping, and resolution remain in `ports.py`. Lazy top-level imports
allow the package to load without the optional routing dependency.

### Spatial correctness

Coordinate order is explicit at every boundary:

- `LatLon(latitude, longitude)` is the SDK/internal contract;
- `LonLat(longitude, latitude)` is the X/Y contract used by searoute and
  GeoJSON;
- cKDTree indexes Earth-centered Cartesian XYZ, derived from validated WGS84
  latitude and longitude.

Latitude is constrained to `[-90, 90]`, longitude to `[-180, 180]`, and route
lengths are checked against their great-circle lower bound. Source parsers also
reject invalid degree-minute-second components.

### Artifact bundling

Source archives are not stored in Python modules. A scheduled GitHub Actions
workflow downloads public snapshots, normalizes the records, and computes a
deterministic content hash. The workflow opens a pull request when the normalized
content changes. CI includes the Parquet files in the wheel and tests the built
wheel.

### Concurrency, caching, and backoff

The bundled searoute backend declares that its distances are symmetric. For this
backend, an `n`-port matrix calculates `n(n-1)/2` route edges. A backend that
does not declare symmetry calculates both directions. `SeaRouter` distributes
the route edges across a spawn-based `ProcessPoolExecutor`. Set
`max_workers=1` for sequential execution.

Each process opens its own short-lived SQLite connection. WAL mode,
`busy_timeout=30000`, a 30-second connection timeout, autocommit isolation, and
`BEGIN IMMEDIATE` serializes cache writes from concurrent workers.
Deterministic cache keys include coordinates, effective routing configuration,
engine, and engine version.

Transient backend failures—timeouts, transport errors, HTTP 429, and HTTP
5xx—receive exponential backoff. The implementation permits at most eight
attempts and caps each delay at eight seconds. Malformed geometry and other
permanent failures fail immediately. The default `searoute` engine is local.

### Data contracts and quality

Strict Pandera schemas validate human-reviewed decision CSVs, generated
`review.csv` rows, and distance-matrix edges. ID columns are read as strings
without coercion. The schemas reject extra columns, duplicate or missing row
IDs, invalid types, non-finite distances, and out-of-range coordinates. CI runs
Ruff, mypy, pytest, and wheel builds through `uv`.

## Installation

Install the complete CLI with routing:

```bash
uv tool install 'sea-mile[routing]'
```

Add `api`, `map`, or `tui` to install the optional server and visualizations:

```bash
uv tool install 'sea-mile[routing,api,map,tui]'
```

For a source checkout:

```bash
uv sync --dev --extra analysis --extra api --extra fast --extra map --extra routing --extra tui
uv run sea-mile info
```

The wheel contains the compact bundled registry. Search, resolution, and nearest
queries need no download; routing requires the `routing` extra.

## Python SDK

```python
from sea_mile import PortRegistry, SeaRouter

registry = PortRegistry.bundled()
origin = registry.resolve("TRMER")
destination = registry.resolve("GRPIR")

router = SeaRouter(cache_path=".cache/sea-mile/routes.sqlite3")
route = router.route(origin, destination)
matrix = router.distance_matrix(
    [origin, destination, registry.resolve("TRIST")],
    max_workers=4,
)

print(route.distance_nmi, route.quality_flag)
```

`PortRegistry.from_directory(path)` loads a local build. `resolve` accepts exact
registry IDs, canonical IDs, UN/LOCODEs, and exact aliases. It does not select a
fuzzy match. Ambiguity raises `AmbiguousPortError`.

See [Library API](docs/LIBRARY_API.md), [API compatibility](docs/API_COMPATIBILITY.md),
[data dictionary](docs/DATA_DICTIONARY.md), and
[output schemas](docs/OUTPUT_SCHEMAS.md).

## CLI

| Command | Operation |
| --- | --- |
| `info` | Inspect the active registry |
| `search` | Run exact, prefix, or fuzzy search |
| `show` | Resolve one port |
| `near` | Find nearby ports |
| `route` | Calculate one sea route |
| `matrix` | Calculate a process-parallel distance matrix |
| `match` | Match CSV rows and emit review data |
| `export` | Export CSV or GeoJSON |
| `tui` | Launch the interactive terminal search and map |
| `serve` | Serve bundled port routes over HTTP |
| `data download` | Download source snapshots |
| `data build` | Build the normalized registry |
| `data prepare` | Download and build source data |
| `data lock` | Pin local source integrity |
| `data verify` | Run provenance and integrity checks |

The TUI displays a braille world map with embedded coastlines and port markers.
Press `Esc` to enter browse mode, then use `+`/`-` to zoom, `h`/`j`/`k`/`l`
to pan, `g` to center on the selected port, and `0` to reset the view. Press
`i` to return to insert mode and continue typing in the search bar.

```bash
sea-mile search Mersin --country TR
sea-mile show TRMER
sea-mile near 39.87 26.16 --country TR --limit 5
sea-mile route TRMER GRPIR --geojson route.geojson --html-map route.html
sea-mile matrix TRMER GRPIR TRIST --cache .cache/routes.sqlite3
sea-mile export --country TR --format geojson --output tr.geojson
sea-mile match ports.csv --country-column country
sea-mile serve --host 127.0.0.1 --port 8000
```

The server exposes
`GET /route?origin=TRMER&destination=GRPIR`. It uses the bundled registry and
returns `distance_nmi` together with a GeoJSON route feature.

The registry lookup order is `--data-dir`, `SEA_MILE_DATA_DIR`, the checkout's
`data/reference/processed`, then the bundled artifact.

### Human review CSV

```bash
sea-mile match ports.csv \
  --name-column port_name \
  --country-column country \
  --id-column row_id \
  --output matched.csv \
  --review review.csv
```

`review.csv` contains one row per candidate for `review_required` and
`unresolved` inputs. A decision file has two columns:

| Column | Contract |
| --- | --- |
| `row_id` | Required, non-empty, and unique |
| `chosen_registry_id` | Required provider-qualified ID |

```bash
sea-mile match ports.csv \
  --name-column port_name \
  --id-column row_id \
  --decisions decisions.csv \
  --output matched.csv
```

Unknown registry IDs, extra columns, duplicate IDs, or empty values stop the
operation before output is accepted. Applied decisions receive
`manually_resolved`.

### JSON and exit codes

Commands that support `--json` emit one schema-versioned document:

```json
{
  "schema_version": "1",
  "command": "search",
  "data": [],
  "warnings": []
}
```

Use `schema_version` and structured `error.code` in automation; human-readable
messages may evolve.

| Exit code | Meaning |
| --- | --- |
| `0` | Success, including empty results |
| `1` | `data verify` found failed checks |
| `2` | Validation, data, resolution, routing, or dependency error |
| `130` | Interrupted with `Ctrl-C` |

## Reproducible data builds

```bash
sea-mile data prepare
sea-mile data verify
sea-mile data lock
sea-mile data build --lock sea-mile.lock.json
```

Snapshots are bounded by timeout and retry policies. The lock records URL,
snapshot label, byte size, and SHA-256, while the normalized registry carries
provider versions and a deterministic content hash.

The bundled data derives from NGA World Port Index and GeoNames. Local builds
can add UN/LOCODE and user-supplied OpenStreetMap data. See
[sources, attribution, and limitations](docs/SOURCES_AND_LIMITATIONS.md).

## Development and release gate

```bash
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run mypy src
uv run pytest -q
uv build
```

Python 3.11–3.13 are tested on Linux; the latest supported version is also
tested on macOS and Windows. Security reports follow [SECURITY.md](SECURITY.md);
contributions follow [CONTRIBUTING.md](CONTRIBUTING.md).
