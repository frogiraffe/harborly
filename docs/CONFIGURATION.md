# Configuration

Harborly has no required application configuration. The CLI uses its bundled
port registry by default; optional environment variables only change a data
directory or make a source-distribution normalization command reproducible.

## Environment variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `HARBORLY_DATA_DIR` | Optional | See below | Directory containing the processed registry and alias Parquet pair. It selects the CLI registry unless `--data-dir` is supplied. |
| `SOURCE_DATE_EPOCH` | Conditional | None | Unix timestamp used by `scripts/normalize_sdist.py` when `--epoch` is not supplied. |

Set an alternate processed registry for CLI commands:

```bash
export HARBORLY_DATA_DIR=/path/to/processed
harborly info
```

For deterministic source-distribution normalization, provide either an
explicit argument or the environment variable:

```bash
SOURCE_DATE_EPOCH=0 python scripts/normalize_sdist.py dist/harborly-*.tar.gz
```

## Config file format

Harborly does not load `.env`, YAML, JSON, or TOML configuration files at
runtime. Project metadata, dependencies, and tool settings are declared in
`pyproject.toml`; they are package and development configuration, not runtime
application settings.

## Required vs optional settings

`HARBORLY_DATA_DIR` is optional. A command-line `--data-dir` takes precedence
when supplied. The selected directory must contain the processed registry
artifacts expected by `PortRegistry.from_directory`.

`SOURCE_DATE_EPOCH` is required only for `scripts/normalize_sdist.py` when
that script is run without `--epoch`; otherwise it exits with
`--epoch or SOURCE_DATE_EPOCH is required`.

## Defaults

When neither `--data-dir` nor `HARBORLY_DATA_DIR` is set, the CLI resolves its
registry directory in this order:

1. `data/reference/processed` beneath the current working directory, if it exists.
2. The registry bundled in the installed `harborly` package.

`scripts/normalize_sdist.py` has no timestamp default. Pass `--epoch` to avoid
depending on `SOURCE_DATE_EPOCH`.

## Per-environment overrides

No development, staging, or production-specific configuration files are
defined in the repository. Set `HARBORLY_DATA_DIR` in the shell or process
environment for any deployment that needs a registry other than the bundled
one. For local experimentation, prefer `--data-dir` when the override should
apply to only one command.
