# sea-mile

[![CI](https://github.com/frogiraffe/sea-mile/actions/workflows/ci.yml/badge.svg)](https://github.com/frogiraffe/sea-mile/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sea-mile.svg)](https://pypi.org/project/sea-mile/)
[![Python](https://img.shields.io/pypi/pyversions/sea-mile.svg)](https://pypi.org/project/sea-mile/)
[![License](https://img.shields.io/pypi/l/sea-mile.svg)](LICENSE)

**Port identity, spatial search, and analytical sea routing.**

`sea-mile` is a typed Python SDK and CLI for resolving real-world port identities,
finding nearby ports, reviewing ambiguous CSV matches, and calculating
approximate sea-route distances in nautical miles. The package ships with a
source-aware offline registry and preserves its documented public interfaces
throughout the 1.x series.

> Routes are analytical approximations on the `searoute` maritime graph. They
> are not suitable for navigation, voyage planning, or safety-critical use.

## What it does

- Resolves registry IDs, canonical IDs, UN/LOCODEs, and exact aliases.
- Searches port names with exact, prefix, fuzzy, country, and proximity filters.
- Matches CSV rows and supports an auditable human-review decision workflow.
- Calculates approximate sea routes and bounded-process distance matrices.
- Streams large matrix edge sets without constructing a dense matrix.
- Exports CSV, GeoJSON, HTML maps, and a terminal UI.
- Builds and verifies source-aware registry artifacts.

## Installation

Install the complete CLI with routing:

```bash
uv tool install 'sea-mile[routing]'
```

Add `api`, `map`, or `tui` to install the optional server and visualizations:

```bash
uv tool install --force 'sea-mile[routing,api,map,tui]'
```

When changing an existing uv tool installation, always list every capability
that installation must keep. `uv tool install` reconciles the isolated tool
environment with the new requirement, so extras omitted from a later command
can be removed. Quote the requirement to prevent shell glob expansion.

For a source checkout:

```bash
uv sync --dev --extra analysis --extra api --extra fast --extra map --extra routing --extra tui
uv run sea-mile info
```

Commands from a source checkout must use `uv run sea-mile`. A bare `sea-mile`
can resolve to a separate installation under `~/.local/bin` and will not see
packages added to the checkout's `.venv`.

The wheel contains the compact bundled registry. Search, resolution, and nearest
queries need no download; routing requires the `routing` extra.

## 30-second quick start

```bash
sea-mile search Mersin --country TR
sea-mile show TRMER
sea-mile near 39.87 26.16 --country TR --limit 5
sea-mile route TRMER GRPIR
```

Create reusable route artifacts:

```bash
sea-mile route TRMER GRPIR \
  --geojson route.geojson \
  --html-map route.html
```

The route command prints the resolved ports, approximate distance, routing
engine, physical-quality flag, and the navigation warning. Use `--json` when a
script needs the stable schema described in
[output schemas](docs/OUTPUT_SCHEMAS.md).

Example output:

```text
origin: Mersin (WPI:44860)
destination: Piraievs (WPI:42230)
distance_nmi: 594.46
great_circle_nmi: 528.19
detour_ratio: 1.125
quality_flag: ok
engine: searoute 1.6.0 (astar, networkx)
```

## Accuracy and limitations

Registry coordinates retain source provenance and resolution, but they do not
represent berth-level positions. Route geometry follows an approximate
maritime graph; restrictions, graph coverage, and source coordinates can all
affect the result. Treat `quality_flag` as a physical consistency check, not a
navigation certificate. See
[sources, attribution, and limitations](docs/SOURCES_AND_LIMITATIONS.md) for
the complete data boundary.

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
[output schemas](docs/OUTPUT_SCHEMAS.md). Task-oriented examples are collected
in the [cookbook](docs/COOKBOOK.md).

## CLI

| Command | Operation |
| --- | --- |
| `info` | Inspect the active registry |
| `search` | Run exact, prefix, or fuzzy search |
| `show` | Resolve one port |
| `near` | Find nearby ports |
| `route` | Calculate one sea route |
| `matrix` | Calculate a process-parallel distance matrix |
| `cache` | Inspect, prune, or clear a persistent route cache |
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
See the dedicated [TUI guide](docs/TUI.md) for installation and controls.

```bash
sea-mile search Mersin --country TR
sea-mile show TRMER
sea-mile near 39.87 26.16 --country TR --limit 5
sea-mile route TRMER GRPIR --geojson route.geojson --html-map route.html
sea-mile matrix TRMER GRPIR TRIST --workers 4 --cache .cache/routes.sqlite3
sea-mile matrix TRMER GRPIR TRIST --workers 4 --edge-csv route-edges.csv
sea-mile cache info .cache/routes.sqlite3
sea-mile cache prune .cache/routes.sqlite3 --older-than-days 90 --vacuum
sea-mile export --country TR --format geojson --output tr.geojson
sea-mile match ports.csv --country-column country
sea-mile serve --host 127.0.0.1 --port 8000
```

`route --html-map` requires both the `routing` and `map` extras. The server
requires both the `api` and `routing` extras and checks them before it starts.
Its base URL redirects to the interactive API documentation at `/docs`;
`GET /healthz` reports liveness. The server exposes
`GET /route?origin=TRMER&destination=GRPIR`, which uses the bundled registry and
returns `distance_nmi` together with a GeoJSON route feature.

HTML maps opened directly from disk use the bundled Natural Earth coastline
instead of requesting remote tiles. This avoids the missing-`Referer` 403
response that public OpenStreetMap tile servers apply to `file://` pages. For
the detailed OpenStreetMap layer, serve the output directory locally and open
the HTTP URL:

```bash
python -m http.server 8000
# Open http://127.0.0.1:8000/route.html
```

`sea-mile serve` defaults to the loopback interface for local use. It does not
provide authentication, TLS termination, or rate limiting; do not expose it
directly to the public internet without an appropriate production ASGI
deployment and reverse proxy. The HTTP application deliberately exposes one
route per request and has no matrix endpoint.

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

`data verify` checks a local reference build, not the compact registry embedded
in the wheel. Its text and JSON output include `data_source` and the resolved
`reference_root` so automation records exactly which data was checked.

Snapshots are bounded by timeout and retry policies. The lock records URL,
snapshot label, byte size, and SHA-256, while the normalized registry carries
provider versions and a deterministic content hash.

The bundled data derives from NGA World Port Index and GeoNames. Local builds
can add UN/LOCODE and user-supplied OpenStreetMap data. See
[sources, attribution, and limitations](docs/SOURCES_AND_LIMITATIONS.md).

## Development and release gate

```bash
uv sync --locked --all-extras --group audit --python 3.14
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run mypy src
uv run pytest --cov=sea_mile -W error::ResourceWarning \
  -W error::pytest.PytestUnraisableExceptionWarning -q
uv run bandit -r src scripts
uv run pip-audit
SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)" uv build
SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)" \
  uv run python scripts/normalize_sdist.py dist/*.tar.gz
uv run twine check dist/*
```

Python 3.11–3.14 are tested on Linux; Python 3.14 is also tested on macOS and
Windows. A separate Python 3.11 job resolves every declared direct dependency at
its minimum supported version. The release workflow reruns the complete reusable
CI gate before publishing the exact artifacts tested by CI. It creates a
reproducible CycloneDX SBOM, SHA-256 checksum file, GitHub build-provenance
attestation, and GitHub Release. CI installs both the core-only wheel and the
optional API/routing/map workflow in isolated environments.

Design and maintenance details live outside this user guide:

- [Architecture](docs/ARCHITECTURE.md)
- [Routing and cache operations](docs/ROUTING_AND_CACHE.md)
- [HTTP service](docs/API_SERVICE.md)
- [TUI guide](docs/TUI.md)
- [Cookbook](docs/COOKBOOK.md)
- [Dependency policy](docs/DEPENDENCY_POLICY.md)
- [API compatibility](docs/API_COMPATIBILITY.md)
- [Release procedure](docs/RELEASING.md)
- [Changelog](CHANGELOG.md)

Security reports follow [SECURITY.md](SECURITY.md); contributions follow
[CONTRIBUTING.md](CONTRIBUTING.md).
