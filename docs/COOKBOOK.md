# Cookbook

These recipes use the installed `sea-mile` command. In a source checkout,
prefix each command with `uv run`.

See also the
[synthetic GeoJSON map example](https://github.com/frogiraffe/sea-mile/tree/main/examples/synthetic)
for a runnable demo with made-up routes that needs no network access.

## Resolve before routing

Use exact identities for repeatable automation:

```bash
sea-mile search "Port Said" --country EG
sea-mile show EGPSD --json
sea-mile route EGPSD GRPIR --json
```

`resolve` and `show` do not silently select fuzzy results. If a name is
ambiguous, narrow it by country or choose a provider-qualified registry ID from
the search results.

## Stream a large matrix

A dense matrix retains O(n²) cells. Stream edges to an atomic CSV output when
the full matrix is unnecessary:

```bash
sea-mile matrix TRMER GRPIR TRIST EGPSD \
  --edge-csv route-edges.csv \
  --workers 4 \
  --cache .cache/routes.sqlite3
```

If an edge fails, the requested CSV is not replaced with a partial file.

## Maintain the route cache

```bash
sea-mile cache info .cache/routes.sqlite3 --json
sea-mile cache prune .cache/routes.sqlite3 --older-than-days 90
sea-mile cache clear .cache/routes.sqlite3 --vacuum
```

Stop active writers before vacuuming. Clearing a cache removes computed routes,
not registry or source data.

## Create a portable route map

```bash
sea-mile route TRMER GRPIR \
  --geojson route.geojson \
  --html-map route.html
```

The file opens without a tile server by using bundled coastline geometry. Serve
its directory over HTTP when the optional OpenStreetMap tile layer is wanted:

```bash
python -m http.server 8000
```

Then open `http://127.0.0.1:8000/route.html`.

## Review ambiguous CSV matches

```bash
sea-mile match ports.csv \
  --name-column port_name \
  --country-column country \
  --id-column row_id \
  --output matched.csv \
  --review review.csv
```

Record one `chosen_registry_id` per `row_id` in a two-column decisions file,
then apply it:

```bash
sea-mile match ports.csv \
  --name-column port_name \
  --id-column row_id \
  --decisions decisions.csv \
  --output matched.csv
```

## Run the local HTTP service

```bash
sea-mile serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`. The root URL redirects there. See
[HTTP service](API_SERVICE.md) before any non-local deployment.

## Route avoiding a canal (PassageRestriction)

From Python, use the `PassageRestriction` enum to route around blocked or restricted passages. For example, to avoid the Suez Canal and route via the Cape of Good Hope:

```python
from sea_mile import SeaRouter, PassageRestriction

router = SeaRouter(restrictions=[PassageRestriction.SUEZ])
```

From the CLI:

```bash
sea-mile route TRMER DEHAM --restrictions suez
```

## Multi-leg voyage (route_sequence)

To calculate a continuous sequence of routes connecting multiple points:

```python
seq = router.route_sequence([origin, mid, dest], speed_knots=14.0)

# Access individual legs and aggregates
print(seq.legs)
print(seq.total_distance_nmi)
print(seq.duration_days)

# Export the entire voyage
seq.write_kml('voyage.kml')
```

## Compute ETA for a voyage (speed_knots)

You can compute the estimated time en route by supplying a vessel speed:

```python
route = router.route(origin, dest, speed_knots=14.0)

print(route.duration_hours)
print(route.duration_days)
```

If no speed is provided, `duration_hours` and `duration_days` will be `None`.

## Export to KML and GeoParquet

To export routes using the CLI:

```bash
# KML
sea-mile route TRMER GRPIR --kml route.kml

# GeoParquet (OGC WKB encoding, CRS OGC:CRS84, GeoParquet 1.0.0 spec)
sea-mile export --format geoparquet --output ports.geoparquet --country TR
```

From Python:

```python
# KML
from sea_mile.kml import write_route_kml
write_route_kml(route, 'route.kml')

# GeoParquet
from sea_mile.geoparquet import write_route_geoparquet, write_ports_geoparquet
write_route_geoparquet(route, 'route.geoparquet')
write_ports_geoparquet(ports, 'ports.geoparquet')
```

## Concurrent routes with AsyncSeaRouter

`AsyncSeaRouter` is a drop-in replacement for `SeaRouter` in asynchronous contexts.

```python
import asyncio
from sea_mile import AsyncSeaRouter

async def main():
    router = AsyncSeaRouter()
    
    # Run multiple routes concurrently
    routes = await asyncio.gather(
        router.route(origin1, dest1),
        router.route(origin2, dest2)
    )
    
    # Or sequence them
    seq = await router.route_sequence([origin, mid, dest])
```
