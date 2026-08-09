# Development

## Local setup

Fork the repository on GitHub, then clone your fork and install the locked development environment. The project supports Python `>=3.11` and uses [uv](https://docs.astral.sh/uv/) for environments and dependencies.

```bash
git clone git@github.com:YOUR-USERNAME/harborly.git
cd harborly
uv sync --locked --dev --all-extras
uv run harborly info
```

No local environment file or additional service is required for the standard test suite. Install the audit group before running the security and package-metadata checks:

```bash
uv sync --locked --all-extras --group audit
```

## Build commands

The project defines developer commands directly through `uv`; it has no separate task runner configuration.

| Command | Description |
| --- | --- |
| `uv sync --locked --dev --all-extras` | Create or update the development environment with every optional feature. |
| `uv sync --locked --all-extras --group audit` | Add the audit tools used by the security and release checks. |
| `uv run ruff format --check src tests scripts` | Check Python formatting without modifying files. |
| `uv run ruff check src tests scripts` | Run Ruff lint rules. |
| `uv run mypy src` | Type-check the package source. |
| `uv run python scripts/check_docs.py` | Check repository documentation prose. |
| `uv run pytest -q` | Run the test suite. |
| `uv run bandit -r src scripts` | Scan source and scripts for security issues. |
| `uv run pip-audit` | Audit installed dependencies. |
| `uv build` | Build the source distribution and wheel into `dist/`. |
| `uv run twine check --strict dist/*` | Validate built package metadata. |

## Code style

- **Ruff** is configured in [`pyproject.toml`](../pyproject.toml). It checks errors, pyflakes, warnings, import ordering, Python upgrades, bugbear, and simplification rules; run the format and lint commands above before opening a pull request.
- **mypy** is configured in [`pyproject.toml`](../pyproject.toml) with untyped-definition checking, redundant-cast warnings, and no implicit optional values. Run `uv run mypy src`.
- CI runs Ruff on `src`, `tests`, and `scripts`; documentation, type, and test checks run on Ubuntu with Python 3.14.

## Branch conventions

No branch naming convention is documented. Keep branches focused on one change and use an imperative commit subject; explain externally observable behavior and the reason for the change in the commit body.

## Dependency policy

`pyproject.toml` declares the supported minimum versions of direct dependencies, while `uv.lock` records the reproducible development and release environment. Keep the two roles distinct: do not raise a published minimum merely to match the lockfile.

- Avoid upper bounds unless a verified incompatibility cannot be handled in code.
- Raise a minimum only with evidence that the old version cannot support the implementation or a supported Python version.
- Lower a minimum only after the `minimum-dependencies` CI job passes; it resolves the declared direct floors on Python 3.11 with every optional extra.
- Dependabot groups weekly Python and GitHub Actions updates. Merge them only after the locked CI matrix passes.

## Benchmarks

Benchmarks produce environment-specific measurements, not performance guarantees. Run them when changing registry construction, search, nearest-port queries, matching, or distance-matrix behavior; include the command and environment with any reported result.

```bash
uv run python scripts/benchmark.py 40000 --matrix-size 250
uv run python -m benchmarks.matching_performance --rows 300 --profile-rows 200 --out benchmark-results
```

The synthetic benchmark can compare the scan path with SciPy's spatial index through `--no-kdtree`. The matching benchmark writes JSON and Markdown reports to the selected output directory.

## Bundled data refresh

The monthly `refresh-bundled-data` workflow downloads WPI and GeoNames snapshots into `data/reference`, rebuilds `src/harborly/data/`, and opens or updates a pull request only when `registry_content_hash` changes. Snapshot labels, paths, and hashes alone are not a content change.

To reproduce the refresh locally:

```bash
uv run harborly data download --reference-root data/reference --refresh
uv run python scripts/build_bundled_registry.py data/reference
```

Review the generated data and attribution before merging. Merging a refresh does not publish a release; releases start from a `v*` tag.

## Release gates

Use SemVer: patch releases cover compatible fixes, maintenance, and registry refreshes; minor releases add compatible public surface; major releases remove or incompatibly change it. Before creating a release tag, run the audit environment and local release checks:

```bash
uv sync --locked --all-extras --group audit --python 3.14
uv run pytest --cov=harborly -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning -q
export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)"
uv build
uv run python scripts/normalize_sdist.py dist/*.tar.gz
uv run twine check --strict dist/*
```

Push a tag named `v<project.version>` from a commit already in `main`. The release workflow reruns CI, verifies that tag/version relationship, publishes the CI-built artifacts to PyPI, and creates a GitHub Release. After publication, verify the package can be installed in a clean environment and that `harborly info` works; correct release problems in a new patch release.

## Pull request process

- Open pull requests against `main`; CI runs for pushes and pull requests targeting that branch.
- Summarize what changed and why, then list the concrete changes.
- Add and run tests for behavior changes.
- Run the Ruff format and lint checks, mypy, and `uv run python scripts/check_docs.py`.
- Keep public names and commands documented; public API, CLI, or JSON-output
  changes must follow the [public compatibility contract](../CONTRIBUTING.md#public-compatibility-contract).
