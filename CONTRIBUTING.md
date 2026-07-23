# Contributing

Thanks for your interest in sea-mile. This is a small, focused library, and the goal is
to keep it trustworthy rather than large. Bug reports, failing cases from real data, and
documentation fixes are especially welcome.

## Development setup

sea-mile uses [uv](https://docs.astral.sh/uv/).

```bash
uv sync --dev --extra analysis --extra fast --extra tui --extra routing
```

## Before you open a pull request

Run the full gate. CI runs the same checks on Linux, macOS, and Windows.

```bash
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run mypy src
uv run pytest -q
uv build
```

Add or update a test for any behavior change, and a `CHANGELOG.md` entry under
`[Unreleased]`. Keep the public surface documented. `tests/test_docs_current.py` fails
when a command or a public export is undocumented.

## What to keep in mind

- **No silent fallback.** An ambiguous or uncertain result is never presented as certain.
  A failure raises a typed error with a stable code.
- **Determinism.** The same inputs produce the same output in the same order.
- **Machine output is `--json`.** Human-readable text is for people. Automation reads the
  versioned envelope.
- **The public API is frozen at 1.0.** See [Stability policy](docs/STABILITY.md). A change
  to a public name needs a deprecation, not a rename in place.

## Adding a source provider

A provider is a parser under `sea_mile.sources` that reads a local snapshot and returns a
pair of pandas DataFrames, `(records, aliases)`, in the shape the registry expects. A
record row carries `registry_id`, `provider`, `provider_id`, `country_code`,
`canonical_name`, `latitude`, `longitude`, `unlocode`, `function_code`, `source_version`,
and `coordinate_resolution`. An alias row carries `registry_id`, `provider`, `alias`,
`alias_key`, and `alias_type`. Wire the parser into `sea_mile.build.registry`, which
assigns canonical identities across providers. Open an issue first so we can agree on the
source and its license before the work.

## Commits

Write a short, plain commit subject in the imperative and a body that explains why.
