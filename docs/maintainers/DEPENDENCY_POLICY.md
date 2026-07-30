# Dependency policy

`pyproject.toml` declares the oldest direct versions supported by the project.
The lockfile records the reproducible development and release environment; it
does not replace the public lower-bound contract.

## CI coverage

The regular matrix installs `uv.lock` and tests Python 3.11–3.14 on Linux plus
Python 3.14 on macOS and Windows. This catches current dependency and
interpreter changes.

A separate Python 3.11 job uses uv's `lowest-direct` resolution and installs
all extras. It runs the full suite against the declared direct floors while
allowing transitive dependencies to resolve normally. This makes every lower
bound executable rather than aspirational.

## Current floors

The numerical and tabular floors are deliberately older than the lockfile:

- NumPy 1.26.4 and pandas 2.2.3 cover the array, nullable-value, and DataFrame
  operations used by the registry.
- PyArrow 17.0.0 covers Parquet registry reads and deterministic writes.
- Pandera 0.26.1 provides the `pandera.pandas` schema API used by public data
  contracts.
- RapidFuzz 3.9.7 covers `process.extract` and `fuzz.WRatio`.
- Tenacity 8.2.3 covers the retry primitives used by source downloads.
- HTTPX 0.28.1 covers streaming clients and ASGI test transport.

The development floor for Hypothesis is 6.92.7 because Pandera's strategies
extra requires at least that version. Optional-extra floors are exercised in
the same minimum-dependency job.

## Upper bounds and updates

Arbitrary upper bounds are avoided because they can prevent security and
compatibility fixes. A dependency receives an upper bound only when a verified
incompatibility cannot be handled in code. Dependabot opens grouped weekly
updates for Python and GitHub Actions dependencies; the full locked matrix must
pass before merge.

Raising a public minimum requires evidence that the older floor cannot support
the implementation or a supported interpreter. Lowering a floor requires the
minimum-dependency job to pass.
