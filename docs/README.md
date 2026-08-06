# Documentation index

## Start here

- [Project README](https://github.com/frogiraffe/harborly/blob/main/README.md) —
  installation, quick start, CLI overview.
- [Cookbook](COOKBOOK.md) — task-oriented recipes.
- [Synthetic map example](https://github.com/frogiraffe/harborly/tree/main/examples/synthetic) —
  a runnable demo with made-up routes, no network access required.

## Interfaces and contracts

- [Library API](LIBRARY_API.md) — the public Python surface.
- [API compatibility](API_COMPATIBILITY.md) — what the 1.x series guarantees.
- [Output schemas](OUTPUT_SCHEMAS.md) — versioned JSON schemas and exit codes.
- [HTTP service](API_SERVICE.md) — routes, health checks, error contract.

## Data and methodology

- [Data dictionary](DATA_DICTIONARY.md) — registry and alias field reference.
- [Sources, attribution, and limitations](SOURCES_AND_LIMITATIONS.md) — data
  provenance and the accuracy boundary.

## Internals and operations

- [Routing and cache operations](ROUTING_AND_CACHE.md).
- [Terminal UI](TUI.md) — installation and keybindings.

## Maintainers

Not needed to install or use harborly — for people changing the code or
cutting a release.

- [Architecture](maintainers/ARCHITECTURE.md) — module layout and data flow.
- [Performance](maintainers/PERFORMANCE.md) — `match_names` and search benchmarks.
- [Dependency policy](maintainers/DEPENDENCY_POLICY.md).
- [Release procedure](maintainers/RELEASING.md).
- [Contributing](https://github.com/frogiraffe/harborly/blob/main/CONTRIBUTING.md).
- [Security](https://github.com/frogiraffe/harborly/blob/main/SECURITY.md).
