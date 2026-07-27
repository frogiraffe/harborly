# Changelog

All notable user-visible changes are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.6.0] - 2026-07-27

### Added

- Cache inspection, retention pruning, clearing, and optional vacuum commands.
- Executable minimum-dependency CI coverage and dependency-policy documentation.
- Dedicated architecture, routing/cache, and HTTP service documentation.

### Changed

- Reorganized the README around installation and a short user-first quick start.
- Broadened dependency compatibility by lowering validated minimum versions.

## [1.5.0] - 2026-07-27

### Added

- Bounded-memory `SeaRouter.iter_distance_edges` and CLI `matrix --edge-csv`.
- Explicit matrix worker control and a four-worker automatic cap.
- Reproducible wheel and sdist verification, CycloneDX SBOM generation, build
  provenance attestations, and PyPI Trusted Publishing.
- Minimum coverage enforcement, security scanning, dependency auditing, and
  Dependabot configuration.

### Changed

- Hardened parallel downloads against malformed range responses and oversized
  aggregate payloads.
- Included routing graph versions in persistent cache keys.
- Expanded documentation for output schemas, performance, bundled data, and
  release operations.

### Fixed

- Preserved optional extras when reinstalling uv tools.
- Redirected the local API root to `/docs` and documented health and route
  response models.
- Prevented public tile-server 403 grids in `file://` HTML maps.
- Made the worker-cap regression test independent of runner CPU count.

## [1.4.0] - 2026-07-27

### Added

- Circuit-breaker and configurable retry and route-quality policies.
- Canonical evidence and expanded production-hardening regression coverage.

### Fixed

- Retried concurrent SQLite WAL initialization on Windows.
- Included Pandera as a required runtime dependency.

[Unreleased]: https://github.com/frogiraffe/sea-mile/compare/v1.6.0...HEAD
[1.6.0]: https://github.com/frogiraffe/sea-mile/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/frogiraffe/sea-mile/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/frogiraffe/sea-mile/compare/v1.3.0...v1.4.0
