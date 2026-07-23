"""Download versioned public reference snapshots without query disclosure."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from sea_mile.exceptions import SourceDataError

WPI_URL = "https://msi.nga.mil/api/publications/world-port-index?output=csv"
UNLOCODE_RELEASE = "2025-1"
UNLOCODE_URL = (
    "https://opensource.unicc.org/un/unece/uncefact/vocab-locode/-/jobs/"
    "artifacts/2025-1/download?job=package-release"
)
GEONAMES_URL = "https://download.geonames.org/export/dump/allCountries.zip"


# Progress prints to stderr, and only for a terminal, to keep pipes and logs clean.
_PROGRESS_STEP_BYTES = 8 * 1024 * 1024


def _report_progress(name: str, received: int, total: int | None) -> None:
    if total:
        percent = min(received * 100 // total, 100)
        message = (
            f"\r{name}: {received / 1e6:,.0f} / {total / 1e6:,.0f} MB ({percent}%)"
        )
    else:
        message = f"\r{name}: {received / 1e6:,.0f} MB"
    sys.stderr.write(message)
    sys.stderr.flush()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    reraise=True,
)
def _download(client: httpx.Client, url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    show_progress = sys.stderr.isatty()
    with client.stream("GET", url) as response:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        total = int(content_length) if content_length else None
        received = 0
        next_report = 0
        with partial.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
                received += len(chunk)
                if show_progress and received >= next_report:
                    _report_progress(destination.name, received, total)
                    next_report = received + _PROGRESS_STEP_BYTES
        if show_progress:
            _report_progress(destination.name, received, total)
            sys.stderr.write("\n")
    partial.replace(destination)


def _newest_snapshot(raw_root: Path, provider: str, filename: str) -> Path | None:
    candidates = sorted((raw_root / provider).glob(f"*/{filename}"), reverse=True)
    return candidates[0] if candidates else None


def _snapshot_target(
    raw_root: Path,
    provider: str,
    filename: str,
    label: str,
    refresh: bool,
    explicit_label: bool,
) -> Path:
    # Reuse the newest existing snapshot only when the caller neither forced a
    # refresh nor pinned a specific label.
    if not (refresh or explicit_label):
        existing = _newest_snapshot(raw_root, provider, filename)
        if existing is not None:
            return existing
    return raw_root / provider / label / filename


def _checksum(
    reference_root: Path,
    prior_sources: dict[str, object],
    source_key: str,
    path: Path,
    downloaded: set[Path],
) -> str:
    # Reuse the recorded checksum for a file that was not fetched this run and
    # still matches the manifest by path and size, to avoid rehashing large
    # archives on every run.
    if path not in downloaded:
        prior = prior_sources.get(source_key)
        if (
            isinstance(prior, dict)
            and prior.get("path") == path.relative_to(reference_root).as_posix()
            and prior.get("bytes") == path.stat().st_size
            and isinstance(prior.get("sha256"), str)
        ):
            return prior["sha256"]
    return sha256(path)


def download_reference_data(
    reference_root: str | Path,
    *,
    snapshot_label: str | None = None,
    refresh: bool = False,
) -> dict[str, object]:
    """Download the public sources locally and return their checksum manifest.

    An existing snapshot is reused unless refresh is true. This avoids
    refetching hundreds of megabytes when the local files are already present.
    """

    reference_root = Path(reference_root)
    retrieved_at = datetime.now(UTC)
    explicit_label = snapshot_label is not None
    label = snapshot_label or retrieved_at.date().isoformat()
    raw_root = reference_root / "raw"
    wpi_path = _snapshot_target(
        raw_root, "wpi", "UpdatedPub150.csv", label, refresh, explicit_label
    )
    unlocode_path = (
        raw_root
        / "unlocode"
        / UNLOCODE_RELEASE
        / f"unlocode-{UNLOCODE_RELEASE}-artifacts.zip"
    )
    geonames_path = _snapshot_target(
        raw_root, "geonames", "allCountries.zip", label, refresh, explicit_label
    )
    downloads = [
        (url, path)
        for url, path in (
            (WPI_URL, wpi_path),
            (UNLOCODE_URL, unlocode_path),
            (GEONAMES_URL, geonames_path),
        )
        if refresh or not path.exists()
    ]
    headers = {"User-Agent": "sea-mile/0.1 (local public reference download)"}
    if downloads:
        try:
            with httpx.Client(
                follow_redirects=True, timeout=180, headers=headers
            ) as client:
                for url, path in downloads:
                    _download(client, url, path)
        except (httpx.HTTPError, OSError) as error:
            raise SourceDataError(
                f"public reference download failed: {error}"
            ) from error

    downloaded = {path for _, path in downloads}
    prior_sources: dict[str, object] = {}
    manifest_path = reference_root / "manifest.json"
    if manifest_path.exists():
        try:
            prior_sources = json.loads(manifest_path.read_text()).get("sources", {})
        except (json.JSONDecodeError, OSError):
            prior_sources = {}

    manifest: dict[str, object] = {
        "retrieved_at_utc": retrieved_at.isoformat(),
        "sources": {
            "wpi": {
                "publisher": "National Geospatial-Intelligence Agency",
                "url": WPI_URL,
                "snapshot_label": wpi_path.parent.name,
                "path": wpi_path.relative_to(reference_root).as_posix(),
                "sha256": _checksum(
                    reference_root, prior_sources, "wpi", wpi_path, downloaded
                ),
                "bytes": wpi_path.stat().st_size,
            },
            "unlocode": {
                "publisher": "United Nations Economic Commission for Europe",
                "url": UNLOCODE_URL,
                "release": UNLOCODE_RELEASE,
                "path": unlocode_path.relative_to(reference_root).as_posix(),
                "sha256": _checksum(
                    reference_root,
                    prior_sources,
                    "unlocode",
                    unlocode_path,
                    downloaded,
                ),
                "bytes": unlocode_path.stat().st_size,
            },
            "geonames": {
                "publisher": "GeoNames",
                "url": GEONAMES_URL,
                "snapshot_label": geonames_path.parent.name,
                "license": "CC BY 4.0",
                "path": geonames_path.relative_to(reference_root).as_posix(),
                "sha256": _checksum(
                    reference_root,
                    prior_sources,
                    "geonames",
                    geonames_path,
                    downloaded,
                ),
                "bytes": geonames_path.stat().st_size,
            },
        },
    }
    reference_root.mkdir(parents=True, exist_ok=True)
    (reference_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


SOURCE_LOCK_VERSION = 1


def write_source_lock(
    reference_root: str | Path, *, lock_path: str | Path | None = None
) -> dict[str, object]:
    """Pin the downloaded source snapshots into a lockfile.

    The lock records each source's URL, snapshot label, size, and SHA-256 from the
    download manifest, so a build can be verified against it and repeated offline.
    """

    reference_root = Path(reference_root)
    manifest_path = reference_root / "manifest.json"
    if not manifest_path.exists():
        raise SourceDataError(
            f"no download manifest at {manifest_path}; run data download first"
        )
    manifest = json.loads(manifest_path.read_text())
    lock: dict[str, object] = {
        "lock_version": SOURCE_LOCK_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "retrieved_at_utc": manifest.get("retrieved_at_utc"),
        "sources": manifest.get("sources", {}),
    }
    target = Path(lock_path) if lock_path else reference_root / "sea-mile.lock.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return lock


def load_source_lock(lock_path: str | Path) -> dict[str, object]:
    """Read a source lockfile, raising SourceDataError when it is unusable."""

    lock_path = Path(lock_path)
    if not lock_path.exists():
        raise SourceDataError(f"lockfile not found: {lock_path}")
    try:
        return json.loads(lock_path.read_text())
    except json.JSONDecodeError as error:
        raise SourceDataError(f"lockfile is not valid JSON: {lock_path}") from error


def lock_mismatches(reference_root: str | Path, lock: dict[str, object]) -> list[str]:
    """Return one description per source that differs from the lock.

    A source is a mismatch when its local file is missing or when its SHA-256 no
    longer matches the value the lock pinned. An empty list means the local raw
    snapshots reproduce the locked sources exactly.
    """

    reference_root = Path(reference_root)
    sources = lock.get("sources")
    if not isinstance(sources, dict):
        return ["lockfile records no sources"]
    mismatches: list[str] = []
    for name, details in sources.items():
        if not isinstance(details, dict):
            continue
        path = reference_root / str(details.get("path"))
        expected = details.get("sha256")
        if not path.exists():
            mismatches.append(f"{name}: missing local file {details.get('path')}")
        elif isinstance(expected, str) and sha256(path) != expected:
            mismatches.append(f"{name}: sha256 differs from the lock")
    return mismatches
