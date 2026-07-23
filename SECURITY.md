# Security policy

## Supported versions

Security fixes land on the latest released minor version. Once 1.0 is out, the 1.x line
receives fixes. Pre-1.0 releases are not maintained after 1.0.

## Reporting a vulnerability

Please report a suspected vulnerability privately. Use GitHub's private vulnerability
reporting on this repository (the Security tab, "Report a vulnerability") rather than a
public issue. Include the version, the platform, and the steps to reproduce. You can
expect an acknowledgement within a few days.

Please do not open a public issue or pull request for a security problem until a fix is
released.

## Scope

sea-mile ships code only. It downloads public reference data to your machine at build
time and redistributes none of it. Two points follow from that.

- **Data integrity, not authentication.** The lockfile records a SHA-256 for each
  downloaded snapshot. That value proves a later build used the same bytes. It does not
  authenticate the first download against a compromised upstream. Treat a source as
  trusted at the moment you first fetch it.
- **Untrusted input.** Port names and CSV rows you match are data, not code. If you feed
  sea-mile a large or malformed file, it should fail with a clear error, not crash the
  host or run anything. Report a case where it does not.

## Release artifacts

Releases are built and published to PyPI through GitHub Actions with PyPI Trusted
Publishing, so a release is tied to a tagged commit in this repository and carries
provenance. Every Action in the workflow is pinned to a commit SHA.
