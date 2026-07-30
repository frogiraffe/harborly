# Release procedure

sea-mile releases are tag-driven. The release workflow accepts only a `v<version>`
tag whose commit is already contained in `origin/main` and whose value matches
`project.version`.

## Required checks

The protected `main` branch requires the Linux Python 3.11–3.14 test matrix,
Python 3.14 tests on macOS and Windows, dependency and source security scans, and
the package build job. A separate Python 3.11 job runs the complete suite with
the declared minimum direct dependencies. CI uses the committed lockfile and a
pinned uv version.

The build job:

1. Runs tests with branch coverage and fails below 88%.
2. Treats leaked-resource warnings as errors.
3. Builds the wheel and sdist with the commit timestamp as
   `SOURCE_DATE_EPOCH`.
4. Normalizes the sdist metadata and rebuilds both artifacts to verify identical
   SHA-256 content.
5. Runs Twine metadata validation.
6. Installs the core-only wheel and exercises bundled data and Pandera contracts.
7. Installs the API, routing, and map extras and exercises a route, HTML map, and
   health endpoint.
8. Generates a reproducible CycloneDX JSON SBOM from the isolated core-wheel
   environment.

## Publishing

When a version tag passes the reusable CI workflow, the publish job downloads
the exact wheel, sdist, and SBOM produced by the build job. It does not rebuild
the package. The job creates `SHA256SUMS`, records a GitHub build-provenance
attestation, publishes the wheel and sdist through PyPI Trusted Publishing, and
creates a GitHub Release containing all artifacts and metadata.

The `pypi` GitHub environment permits only `v*` tags and requires approval from
the repository maintainer. The maintainer should compare the release diff,
confirm the version and `CITATION.cff` date, move the relevant `CHANGELOG.md`
items out of `Unreleased`, and review source-data changes before approving.

## Post-publication verification

PyPI artifacts and tags are immutable: a broken release is fixed with a new
patch release, never by replacing the uploaded files. After the publish job
finishes, manually confirm on `https://pypi.org/project/sea-mile/`:

- the new version is the one displayed;
- the long description renders (it is `README.md` as of the published commit —
  confirm every link and image uses an absolute `https://github.com/...` URL,
  since PyPI resolves relative links against the project page, not the
  repository);
- the CI, PyPI, Python, and License badges render;
- the Homepage, Repository, and Issues project links resolve;
- `pip install sea-mile` succeeds in a clean virtual environment and
  `sea-mile info` runs.

If any of these fail, the tag and uploaded artifacts stay published as-is;
open an issue describing exactly what failed and ship the fix as the next
patch release.

## Local reproduction

```bash
uv sync --locked --all-extras --group audit --python 3.14
uv run pytest --cov=sea_mile -W error::ResourceWarning \
  -W error::pytest.PytestUnraisableExceptionWarning -q
export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)"
uv build
uv run python scripts/normalize_sdist.py dist/*.tar.gz
uv run twine check --strict dist/*
```

Build a second output directory with the same epoch and compare the artifact
hashes to reproduce CI's byte-identity check.
