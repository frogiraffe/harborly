# Testing

## Test framework and setup

The suite uses [pytest](https://docs.pytest.org/) `>=9.1.1`, with `pytest-cov` `>=7.0.0` for coverage and Hypothesis for property-based tests. Install the locked development environment, including the optional features exercised by the suite:

```bash
uv sync --locked --all-extras --python 3.14
```

The project supports Python `>=3.11`; CI runs the main suite on Python 3.11 through 3.14. Pytest adds the repository root to its import path through the configuration in `pyproject.toml`.

## Running tests

Run the same full-suite command used by the primary CI job:

```bash
uv run pytest --cov=harborly -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning -q -rs
```

Run one test module while working on a focused change:

```bash
uv run pytest tests/test_routing.py -q
```

Run one named test:

```bash
uv run pytest tests/test_routing.py::RouteAssessmentTests::test_route_cannot_be_materially_shorter_than_great_circle -q
```

No watch-mode command is configured.

## Writing new tests

Place tests in `tests/` using the `test_*.py` naming convention and pytest `test_*` functions. Keep test data close to its consumers: the repository stores reusable CSV fixtures under `tests/golden/`, while module-level helpers and pytest fixtures are defined in the test modules that use them. For example, API tests use local `@pytest.fixture` functions and `@pytest.mark.anyio`; property tests use Hypothesis `@given` strategies in `tests/test_properties.py`.

Add a focused regression test to the matching module when possible. Tests that depend on an optional feature should skip clearly when its extra is absent, as the API tests do with `pytest.importorskip("fastapi")`.

## Coverage requirements

Coverage is collected from the `harborly` package with branch measurement enabled. The build fails when overall coverage falls below 88%.

| Type | Threshold |
| --- | --- |
| Overall coverage | 88% minimum |
| Branches | Measured; no separate threshold |
| Lines, functions, statements | No individual threshold configured |

## CI integration

The [`CI` workflow](../.github/workflows/ci.yml) runs on pushes and pull requests targeting `main`, and can also be dispatched or called by another workflow. Its `test` job installs the locked environment with every optional extra, runs formatting and lint checks, then runs the full pytest command above on Ubuntu with Python 3.11–3.14, plus macOS and Windows with Python 3.14. The `minimum-dependencies` job separately runs `.venv-min/bin/pytest -q` against the declared minimum dependencies on Python 3.11.
