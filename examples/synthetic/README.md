# Synthetic GeoJSON demo

This folder has a small demo map. The demo uses six fixed, made-up
origin-destination routes. The route IDs and coordinates are example values.
They do not come from any real port record.

Build the demo file:

```bash
uv run python scripts/build_synthetic_demo.py
```

Serve the repository root, then open the interactive map:

```bash
uv run python -m http.server 8000
```

Open `http://localhost:8000/examples/synthetic/` in a browser.

Opening `examples/synthetic/index.html` directly as a local file also works.
The route data loads from `synthetic_routes.geojson.js`, a generated
`<script>`-loadable copy of the same GeoJSON, so no server is required.

The demo uses `searoute` with `units="naut"`. The demo shows how the library
builds a route. The demo is not navigation guidance.
