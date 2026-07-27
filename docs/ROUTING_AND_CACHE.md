# Routing and cache operations

## Retry and circuit breaker behavior

`SeaRouter` defaults to four attempts with exponential backoff starting at
0.25 seconds. `RetryPolicy` accepts 1–8 attempts, finite non-negative delay
values, and jitter from 0.0 to 1.0. Timeouts, connection failures, HTTP 429, and
HTTP 5xx are transient; malformed responses and other permanent failures stop
immediately.

The circuit breaker is opt-in through `CircuitBreakerPolicy`. Its policy
defaults to five consecutive transient failures and a 30-second recovery
window. After the window, one half-open probe is allowed. A failed probe opens
the breaker again; a successful probe closes it.

Breaker state belongs to one `SeaRouter` instance. Matrix worker processes each
construct their own router, so breaker state is not shared across processes.
One failed edge raises an error for the operation. A dense matrix is never
returned partially. `iter_distance_edges` may already have yielded earlier
edges to its caller; the CLI protects `--edge-csv` with a temporary file and
only replaces the requested output after every edge succeeds.

## Persistent cache

Passing `cache_path` stores raw backend results in SQLite. Cache keys include:

- origin and destination coordinates;
- effective routing algorithm, graph backend, and restrictions;
- routing engine and package version;
- routing graph version;
- cache-key format version.

Every operation opens a short-lived connection. WAL mode, a 30-second busy
timeout, autocommit isolation, and `BEGIN IMMEDIATE` serialize concurrent
writes. Invalid JSON, non-finite distances, and malformed geometries are
evicted on read.

## Maintenance

The cache is opt-in and has no implicit global path. Pass the same explicit path
used by `route --cache` or `matrix --cache`:

```bash
sea-mile cache info .cache/routes.sqlite3
sea-mile cache prune .cache/routes.sqlite3 --older-than-days 90
sea-mile cache clear .cache/routes.sqlite3
```

Add `--vacuum` to `prune` or `clear` to reclaim free SQLite pages. Vacuuming
requires an exclusive database lock and should run while route writers are
stopped. Every maintenance command supports `--json`.

`info` reports the absolute path, database schema version, entry count, oldest
and newest timestamps, main database bytes, and WAL bytes.

## Schema policy

SQLite `PRAGMA user_version` versions the table layout independently from cache
keys. Version `0` databases with the original routes table are adopted as
schema `1`. A cache created by a newer unsupported sea-mile version fails
closed instead of being modified.

Future compatible table changes must ship an explicit migration. Because the
database is only a performance cache, an incompatible file can always be
replaced with a new path without losing source or registry data.
