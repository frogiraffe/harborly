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
