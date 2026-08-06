# HTTP service

`harborly serve` is a local FastAPI convenience application. It requires the
`api` and `routing` extras and defaults to `127.0.0.1:8000`.

## Endpoints

- `GET /` redirects to the interactive OpenAPI documentation at `/docs`.
- `GET /v1/livez` returns the service name, installed version, and liveness.
- `GET /v1/readyz` reports whether this process can currently serve a route.
- `GET /v1/route` resolves two bundled port identities and calculates one
  approximate route.

## Liveness and readiness

They answer different questions, and conflating them was a real gap: a server
without the `routing` extra reported itself healthy on liveness and then
failed every route request, so a supervisor could not tell the two apart.

`/v1/livez` says the process is up. It says nothing about dependencies and
always returns `200` while the process can answer at all — restarting on it
would only replace a process that is fine.

`/v1/readyz` probes what a route request actually needs and returns `200` with
`"status": "ready"`, or `503` with `"status": "not_ready"`:

```json
{
  "service": "harborly",
  "status": "ready",
  "version": "1.0.0",
  "checks": [
    {"name": "port_registry", "passed": true, "detail": "20070 records"},
    {"name": "routing_backend", "passed": true, "detail": "searoute 1.6.0"},
    {"name": "route_cache", "passed": true, "detail": "not configured"}
  ]
}
```

It does not compute a route — far too expensive to run on every poll. It loads
the registry, touches the routing backend (which is what surfaces a missing
`routing` extra, since the import is lazy), and reads from the persistent cache
if one is configured.

The cache check follows `CacheFailurePolicy`. Under `STRICT` an unusable cache
fails every request, so the process reports not-ready. Under `BEST_EFFORT` the
same cache costs only speed, so the process stays ready and the check's
`detail` records the degradation.

The service deliberately has no HTTP matrix or bulk-routing endpoint. Each
route request contains one origin and one destination, preventing an
unbounded O(n²) matrix request through this application.

## Error contract

Every failure returns the same body, so a client can branch on `error.code`
without parsing English:

```json
{
  "schema_version": "1",
  "error": {
    "code": "routing_error",
    "message": "routing backend call failed",
    "retryable": true,
    "details": {"reason": "backend_call_failed"}
  }
}
```

`code` is the raising exception's stable `.code`; `message` is human-readable
and may change between releases. `details` carries whatever the failure knows —
for routing failures a `reason` drawn from `RoutingErrorReason`, for query
validation the FastAPI `errors` list.

`retryable` is true only where an identical request could later succeed:
`backend_call_failed`, `circuit_breaker_open`, and `timeout_budget_exhausted`.
Those responses also carry a `Retry-After` header. Everything else names a
condition that will hold again, so retrying only adds load.

`circuit_breaker_open` and `timeout_budget_exhausted` report `503`, because
they describe this service declining to serve rather than an upstream
answering badly; other routing failures report `502`.

| Status | Meaning |
| --- | --- |
| `404` | A port identity was not found. |
| `409` | An identity was ambiguous. |
| `422` | Query or coordinate validation failed. |
| `500` | An unexpected harborly failure. |
| `502` | The routing backend failed. |
| `503` | Routing is unavailable, or the circuit breaker is open. |

## Deployment boundary

The built-in server does not provide authentication, authorization, TLS
termination, rate limiting, request deadlines, or cross-process admission
control. Do not expose it directly to the public internet.

A public deployment should put the ASGI application behind infrastructure that
enforces authentication as required, request and upstream timeouts, concurrency
limits, rate limits, TLS, access logs, and process supervision. These controls
are deployment policy and intentionally remain outside the local library.
