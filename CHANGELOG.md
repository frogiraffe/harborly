# Changelog

All notable user-visible changes are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.6.1] - 2026-07-30

### Fixed

- `match_names`, and therefore `sea-mile match`, searched exact aliases only. A
  misspelled or transliterated destination resolved to `unresolved` with no
  candidates, so `--review` wrote a row a human could not act on. Such a name now
  falls back to a fuzzy alias search and is reported as `review_required` with
  the new `fuzzy_candidates_only` reason code. Fuzzy evidence never selects a
  port: only exact official matches reach `auto_resolved`, and the auto-resolved
  set is unchanged.
- Rows with an empty country cell were dropped from candidate generation
  entirely. They are now searched against the global alias pool, review-only.
- Code-less registry records took a synthetic identity from their coordinate
  rounded to a fixed ~6 nmi grid, so records a single nautical mile apart could
  receive different identities while the rest of the package treats 25 nmi as one
  place, and a corrected coordinate could silently change an identity. Such
  records are now clustered within `coordinate_agreement_nmi`.
- `benchmarks.route_accuracy`'s reference-distance scoring crashed the whole
  benchmark run on the first `RoutingError` (e.g. an antimeridian-crossing
  pair the backend rejects). It now catches per-pair routing failures and
  reports them separately instead of aborting the run.
- `README.md` used 15 repository-relative links (`docs/...`, `CHANGELOG.md`,
  `SECURITY.md`, `CONTRIBUTING.md`, `LICENSE`). PyPI renders this file as the
  package long description and resolves relative links against the project
  page, not the repository, so every one of these 404'd from PyPI. They are
  now absolute `https://github.com/frogiraffe/sea-mile/...` URLs, and
  `scripts/check_docs.py` now hard-fails on any future repository-relative
  link, broken same-document anchor, or relative image in the root README.
- The bug report issue template's "Installed extras" list was missing `api`
  and `map`, two of the six extras `pyproject.toml` actually declares.

### Added

- `MatchCandidate.match_method` and `MatchCandidate.name_score`, also written to
  the review CSV as `candidate_match_method` and `candidate_name_score`, so a
  reviewer can tell an exact hit from a fuzzy suggestion.
- `match_names` accepts a `MatchPolicy`, which was public and documented but
  previously could not be applied to the public matching entry point.
- A regression test that the bundled artifact's precomputed `canonical_id`
  column still agrees with `assign_canonical_ids`. Nothing compared the two
  before, so the shipped data could drift away from the code silently.
- `benchmarks.matching_performance`, profiling `match_names` latency and
  throughput under bulk-CSV-shaped workloads. Identified that per-query cost
  is dominated by a full `DataFrame.merge` against the entire registry in
  `search_results_from_candidates`, not fuzzy scoring; see
  `docs/PERFORMANCE.md`.
- `scripts/check_docs.py`, a conservative documentation prose linter run in
  CI: fails on banned phrasing, prints heuristic AI-writing signals for
  human review without failing the build or rewriting anything.
- Populated `benchmarks/route_accuracy/data/reference_distances.csv` with 44
  curated port pairs from NGA Pub. 151 (2001), each hand-verified against
  the source text. Scoring against the current backend gives 2.03% median
  absolute percentage error; see `benchmarks/route_accuracy/data/README.md`.
- `docs/README.md`, a documentation index grouping the project's guides by
  audience, and a link to it from `README.md`. Fixes `docs/PERFORMANCE.md`
  and `examples/synthetic/README.md`, which were not reachable from any
  public entry point.
- `scripts/check_external_links.py`, a scheduled (weekly), non-blocking
  workflow that HEAD/GET-probes every absolute external link in the project's
  documentation and reports confirmed 404/410 responses. Never gates a pull
  request or a release.

### Changed

- **Data break.** The bundled registry was rebuilt with the clustered canonical
  identities. 16955 of 20070 records carry a different `SM-*` synthetic
  `canonical_id`, and the distinct identity count falls from 19327 to 19191 as
  115 identities absorb records the rounding grid had split. UN/LOCODE-derived
  canonical IDs are unaffected. Persisted `SM-*` identifiers must be remapped.

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

[Unreleased]: https://github.com/frogiraffe/sea-mile/compare/v1.6.1...HEAD
[1.6.1]: https://github.com/frogiraffe/sea-mile/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/frogiraffe/sea-mile/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/frogiraffe/sea-mile/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/frogiraffe/sea-mile/compare/v1.3.0...v1.4.0
