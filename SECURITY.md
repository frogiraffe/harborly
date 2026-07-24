# Security

## Reporting vulnerabilities

Use GitHub private vulnerability reporting from the repository Security tab.
Do not disclose a suspected vulnerability in a public issue or pull request
before a fix is available.

Include:

- the affected sea-mile version;
- operating system and Python version;
- installed optional dependencies;
- the smallest reproducible input or command;
- observed impact.

## Security boundaries

sea-mile downloads and parses external CSV, ZIP, JSON, GeoJSON, and Parquet
data. Relevant vulnerability classes include malformed-input denial of service,
resource exhaustion, archive/parser defects, dependency compromise, path
handling errors, and upstream data tampering.

Source lockfiles provide snapshot integrity after the first download. A recorded
SHA-256 digest does not authenticate the upstream server or establish that the
initial snapshot was trustworthy.

Release artifacts are published through GitHub Actions and PyPI Trusted
Publishing. Workflow actions are pinned to commit SHAs.
