# Contributing

## Environment

```bash
uv sync --dev --extra analysis --extra fast --extra routing --extra tui
```

## Validation

Run before submitting a pull request:

```bash
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run mypy src
uv run pytest -q
uv build
```

Behavior changes require tests. Public commands, exports, schemas, and serialized
fields require corresponding documentation updates.

## Engineering requirements

- Ambiguous identities must produce an explicit review result or typed error.
- Ordering and identifiers must be deterministic for identical inputs.
- JSON output must validate against the documented schema.
- Public API, CLI, and output-schema changes must follow
  [API compatibility](docs/API_COMPATIBILITY.md).
- Registry changes must preserve provider attribution and snapshot provenance.

## Source providers

A source parser belongs under `sea_mile.sources` and returns `(records,
aliases)` as pandas DataFrames. Registry rows require:

`registry_id`, `provider`, `provider_id`, `country_code`, `canonical_name`,
`latitude`, `longitude`, `unlocode`, `function_code`, `source_version`, and
`coordinate_resolution`.

Alias rows require:

`registry_id`, `provider`, `alias`, `alias_key`, and `alias_type`.

Provider integration occurs in `sea_mile.build.registry`. The source license
must permit the intended processing and distribution mode.

## Bundled registry refresh

`.github/workflows/refresh-bundled-data.yml` rebuilds the WPI + GeoNames
registry under `src/sea_mile/data/` (`scripts/build_bundled_registry.py`) on
a GitHub-hosted runner monthly, or on demand via `workflow_dispatch`. It opens
a PR against `main` only when `registry_content_hash` actually changes;
the manifest's `snapshot_label`/`path` fields shift with the run date even
when the underlying data doesn't, so a raw file diff is not used. Merging
that PR does not publish a release by itself — `release.yml` only runs on a
`v*` tag push, so bump the version as part of the merge if you want the
refreshed data to reach PyPI.

## Commits

Use an imperative subject. Explain externally observable behavior and the reason
for the change in the commit body.
