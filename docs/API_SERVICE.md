# HTTP service

`sea-mile serve` is a local FastAPI convenience application. It requires the
`api` and `routing` extras and defaults to `127.0.0.1:8000`.

## Endpoints

- `GET /` redirects to the interactive OpenAPI documentation at `/docs`.
- `GET /healthz` returns the service name, installed version, and liveness.
- `GET /route` resolves two bundled port identities and calculates one
  approximate route.

The service deliberately has no HTTP matrix or bulk-routing endpoint. Each
route request contains one origin and one destination, preventing an
unbounded O(n²) matrix request through this application.

## Error contract

OpenAPI defines successful route, GeoJSON, port provenance, and error models.
The route endpoint uses:

| Status | Meaning |
| --- | --- |
| `404` | A port identity was not found. |
| `409` | An identity was ambiguous. |
| `422` | Query or coordinate validation failed. |
| `502` | The routing backend failed. |
| `503` | The routing dependency is unavailable. |

The `detail` field is human-readable. Clients needing the more detailed stable
error tokens should use the Python API or CLI JSON contract.

## Deployment boundary

The built-in server does not provide authentication, authorization, TLS
termination, rate limiting, request deadlines, or cross-process admission
control. Do not expose it directly to the public internet.

A public deployment should put the ASGI application behind infrastructure that
enforces authentication as required, request and upstream timeouts, concurrency
limits, rate limits, TLS, access logs, and process supervision. These controls
are deployment policy and intentionally remain outside the local library.
