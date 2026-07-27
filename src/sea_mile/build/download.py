"""Download versioned public reference snapshots without query disclosure."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import monotonic

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from sea_mile.exceptions import SourceDataError

WPI_URL = "https://msi.nga.mil/api/publications/world-port-index?output=csv"
# Kept as compatibility aliases for callers that imported the previously pinned
# release. Downloads now discover the current official release from
# UNLOCODE_RELEASES_URL instead of using these values.
UNLOCODE_RELEASE = "2025-1"
UNLOCODE_URL = (
    "https://opensource.unicc.org/un/unece/uncefact/vocab-locode/-/jobs/"
    "artifacts/2025-1/download?job=package-release"
)
UNLOCODE_RELEASES_URL = (
    "https://opensource.unicc.org/api/v4/projects/"
    "un%2Funece%2Funcefact%2Fvocab-locode/releases/permalink/latest"
)
_UNLOCODE_ARTIFACT_URL = (
    "https://opensource.unicc.org/un/unece/uncefact/vocab-locode/-/jobs/"
    "artifacts/{release}/download?job=package-release"
)
GEONAMES_URL = "https://download.geonames.org/export/dump/allCountries.zip"

_MIB = 1024 * 1024
_WPI_MAX_DOWNLOAD_BYTES = 64 * _MIB
_UNLOCODE_MAX_DOWNLOAD_BYTES = 256 * _MIB
_GEONAMES_MAX_DOWNLOAD_BYTES = 1024 * _MIB

_PROGRESS_STEP_BYTES = 8 * 1024 * 1024

# Below this size, splitting into ranges just adds connection overhead for no
# measurable gain; above it (GeoNames' ~400 MB archive is the only source that
# ever qualifies) a server-side per-connection bandwidth cap can make a single
# stream many times slower than the client's own connection, and several
# concurrent ranges each get their own share of the cap. GeoNames throttles
# each connection to ~1 MB/s under load, so eight of them turn a ~7-minute
# single-stream download into well under a minute; the aggregate keeps scaling
# with the connection count until the client's own link, not the per-connection
# cap, becomes the bound.
_PARALLEL_THRESHOLD_BYTES = 20 * _MIB
_PARALLEL_CONNECTIONS = 8

# Ranges are cut to this fixed size rather than into one range per connection,
# so there are many more chunks than workers. Workers pull the next chunk as
# soon as they finish one, so a fast connection keeps claiming work instead of
# sitting idle while one slow connection drains its oversized share. 16 MiB is
# large enough that per-request overhead stays negligible against GeoNames'
# ~1 MB/s throttled streams, yet small enough (~26 chunks for a 400 MB archive)
# to spread evenly across eight workers.
_PARALLEL_CHUNK_BYTES = 16 * _MIB

# httpx's own connect timeout only bounds the TCP handshake: the DNS lookup
# socket.create_connection() does first has no timeout at all, so a stalled
# resolver can hang past any client-side timeout. Racing the request on a
# daemon thread and giving up on it after this many seconds is the only way
# to bound that. It must be a raw daemon thread, not a ThreadPoolExecutor:
# the executor's atexit hook joins every worker it ever started, so
# "giving up" on a future left it running would still block interpreter exit
# until the stalled call finally returned. A daemon thread carries no such
# hook and is simply abandoned.
_CONNECT_DEADLINE_SECONDS = 15.0


class _RangeNotSupported(SourceDataError):
    """Signal that a server advertised ranges but ignored a range request."""


def _is_retryable_download_error(error: BaseException) -> bool:
    """Retry temporary network and HTTP failures, not permanent client errors."""

    if isinstance(error, (TimeoutError, httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return status in {408, 425, 429} or 500 <= status < 600
    return False


def _user_agent() -> str:
    try:
        return f"sea-mile/{version('sea-mile')} (local public reference download)"
    except PackageNotFoundError:
        return "sea-mile (local public reference download)"


def _report_progress(
    name: str, received: int, total: int | None, *, elapsed: float
) -> None:
    rate = received / elapsed if elapsed > 0 else 0.0
    speed = f"{rate / 1e6:,.1f} MB/s" if rate > 0 else "-- MB/s"
    if total:
        percent = min(received * 100 // total, 100)
        eta = f", eta {(total - received) / rate:,.0f}s" if rate > 0 else ""
        message = (
            f"\r{name}: {received / 1e6:,.0f} / {total / 1e6:,.0f} MB "
            f"({percent}%, {speed}{eta})"
        )
    else:
        message = f"\r{name}: {received / 1e6:,.0f} MB ({speed})"
    sys.stderr.write(message)
    sys.stderr.flush()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unlocode_artifact_url(release: str) -> str:
    return _UNLOCODE_ARTIFACT_URL.format(release=release)


def _discover_latest_unlocode_release(client: httpx.Client) -> str:
    """Return the newest official UN/LOCODE release tag from GitLab."""

    try:
        payload = _fetch_latest_unlocode_release(client)
    except (httpx.HTTPError, TimeoutError, ValueError) as error:
        raise SourceDataError(
            f"could not discover the latest UN/LOCODE release: {error}"
        ) from error

    release = payload.get("tag_name") if isinstance(payload, dict) else None
    if not isinstance(release, str) or re.fullmatch(r"\d{4}-[1-9]\d*", release) is None:
        raise SourceDataError(
            "could not discover the latest UN/LOCODE release: "
            "GitLab returned an invalid release tag"
        )
    return release


def _send_with_deadline(client: httpx.Client, url: str) -> httpx.Response:
    request = client.build_request("GET", url)
    response: httpx.Response | None = None
    error: BaseException | None = None
    done = threading.Event()

    def worker() -> None:
        nonlocal response, error
        try:
            response = client.send(request, stream=True)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            error = exc
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True).start()
    if not done.wait(timeout=_CONNECT_DEADLINE_SECONDS):
        raise TimeoutError(
            f"connecting to {url} took longer than "
            f"{_CONNECT_DEADLINE_SECONDS:.0f}s (DNS lookup or network "
            "unreachable); the connection attempt keeps running in the "
            "background and is abandoned, not cancelled"
        )
    if error is not None:
        raise error
    if response is None:
        raise SourceDataError("connection attempt completed without a response")
    return response


@retry(
    retry=retry_if_exception(_is_retryable_download_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    reraise=True,
)
def _fetch_latest_unlocode_release(client: httpx.Client) -> object:
    response = _send_with_deadline(client, UNLOCODE_RELEASES_URL)
    try:
        response.raise_for_status()
        response.read()
        return response.json()
    finally:
        response.close()


def _chunk_ranges(total: int, chunk_bytes: int) -> list[tuple[int, int]]:
    """Tile [0, total) into inclusive byte ranges of at most chunk_bytes each.

    The chunk count is driven by size alone, independent of how many connections
    will fetch them. That decoupling is what lets a fast connection claim more
    than its even share so no single slow connection gates the whole download.
    """
    ranges = []
    start = 0
    while start < total:
        end = min(start + chunk_bytes, total) - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def _download_sequential(
    response: httpx.Response,
    partial: Path,
    *,
    destination_name: str,
    total: int | None,
    max_bytes: int,
    show_progress: bool,
    start_time: float,
) -> int:
    received = 0
    next_report = 0
    with partial.open("wb") as handle:
        for chunk in response.iter_bytes():
            received += len(chunk)
            if received > max_bytes:
                raise SourceDataError(
                    f"{destination_name} exceeds the {max_bytes}-byte download limit"
                )
            handle.write(chunk)
            if show_progress and received >= next_report:
                _report_progress(
                    destination_name,
                    received,
                    total,
                    elapsed=monotonic() - start_time,
                )
                next_report = received + _PROGRESS_STEP_BYTES
    if show_progress:
        _report_progress(
            destination_name, received, total, elapsed=monotonic() - start_time
        )
        sys.stderr.write("\n")
    return received


def _download_parallel(
    client: httpx.Client,
    url: str,
    partial: Path,
    *,
    total: int,
    max_bytes: int,
    destination_name: str,
    show_progress: bool,
    start_time: float,
) -> None:
    with partial.open("wb") as handle:
        handle.truncate(total)

    ranges = _chunk_ranges(total, _PARALLEL_CHUNK_BYTES)
    next_chunk = 0
    received = 0
    next_report = 0
    lock = threading.Lock()
    errors: list[BaseException] = []

    def claim_next() -> tuple[int, int] | None:
        # Hand out chunks one at a time so a fast connection keeps pulling more
        # while a slow one is still on its first; stop early once any worker has
        # failed, so we do not keep fetching for a download that will be raised.
        nonlocal next_chunk
        with lock:
            if errors or next_chunk >= len(ranges):
                return None
            chunk_range = ranges[next_chunk]
            next_chunk += 1
            return chunk_range

    def worker() -> None:
        nonlocal received, next_report
        try:
            while (chunk_range := claim_next()) is not None:
                byte_start, byte_end = chunk_range
                request = client.build_request(
                    "GET", url, headers={"Range": f"bytes={byte_start}-{byte_end}"}
                )
                response = client.send(request, stream=True)
                try:
                    response.raise_for_status()
                    if response.status_code == 200:
                        raise _RangeNotSupported(
                            f"{destination_name} server ignored a byte-range request"
                        )
                    if response.status_code != 206:
                        raise SourceDataError(
                            f"{destination_name} returned HTTP "
                            f"{response.status_code} for a byte-range request"
                        )
                    content_range = response.headers.get("Content-Range", "")
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                    if match is None:
                        raise SourceDataError(
                            f"{destination_name} returned an invalid Content-Range"
                        )
                    actual_start, actual_end, actual_total = map(int, match.groups())
                    if (actual_start, actual_end, actual_total) != (
                        byte_start,
                        byte_end,
                        total,
                    ):
                        raise SourceDataError(
                            f"{destination_name} returned an unexpected Content-Range"
                        )
                    expected = byte_end - byte_start + 1
                    chunk_received = 0
                    with partial.open("r+b") as handle:
                        handle.seek(byte_start)
                        for chunk in response.iter_bytes():
                            with lock:
                                chunk_received += len(chunk)
                                if chunk_received > expected:
                                    raise SourceDataError(
                                        f"{destination_name} returned too many bytes "
                                        "for a requested range"
                                    )
                                if received + len(chunk) > max_bytes:
                                    raise SourceDataError(
                                        f"{destination_name} exceeds the "
                                        f"{max_bytes}-byte download limit"
                                    )
                                received += len(chunk)
                                if show_progress and received >= next_report:
                                    _report_progress(
                                        destination_name,
                                        received,
                                        total,
                                        elapsed=monotonic() - start_time,
                                    )
                                    next_report = received + _PROGRESS_STEP_BYTES
                            handle.write(chunk)
                    if chunk_received != expected:
                        raise SourceDataError(
                            f"{destination_name} returned {chunk_received} bytes for "
                            f"a {expected}-byte range"
                        )
                finally:
                    response.close()
        except BaseException as exc:  # noqa: BLE001 - collected and re-raised below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(_PARALLEL_CONNECTIONS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]
    if received != total:
        raise SourceDataError(
            f"{destination_name} returned {received} bytes; expected {total}"
        )
    if show_progress:
        _report_progress(
            destination_name, total, total, elapsed=monotonic() - start_time
        )
        sys.stderr.write("\n")


@retry(
    retry=retry_if_exception(_is_retryable_download_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    reraise=True,
)
def _download(
    client: httpx.Client,
    url: str,
    destination: Path,
    *,
    max_bytes: int,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    show_progress = sys.stderr.isatty()
    start = monotonic()
    if show_progress:
        sys.stderr.write(f"{destination.name}: connecting...")
        sys.stderr.flush()
    try:
        response = _send_with_deadline(client, url)
        try:
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            try:
                total = int(content_length) if content_length else None
            except ValueError:
                total = None
            if total is not None and total > max_bytes:
                raise SourceDataError(
                    f"{destination.name} exceeds the {max_bytes}-byte download limit"
                )

            if (
                total is not None
                and total >= _PARALLEL_THRESHOLD_BYTES
                and response.headers.get("Accept-Ranges", "").lower() == "bytes"
            ):
                response.close()
                try:
                    _download_parallel(
                        client,
                        url,
                        partial,
                        total=total,
                        max_bytes=max_bytes,
                        destination_name=destination.name,
                        show_progress=show_progress,
                        start_time=start,
                    )
                except _RangeNotSupported:
                    partial.unlink(missing_ok=True)
                    fallback = _send_with_deadline(client, url)
                    try:
                        fallback.raise_for_status()
                        fallback_length = fallback.headers.get("Content-Length")
                        try:
                            fallback_total = (
                                int(fallback_length) if fallback_length else None
                            )
                        except ValueError:
                            fallback_total = None
                        if fallback_total is not None and fallback_total > max_bytes:
                            raise SourceDataError(
                                f"{destination.name} exceeds the "
                                f"{max_bytes}-byte download limit"
                            )
                        _download_sequential(
                            fallback,
                            partial,
                            destination_name=destination.name,
                            total=fallback_total,
                            max_bytes=max_bytes,
                            show_progress=show_progress,
                            start_time=start,
                        )
                    finally:
                        fallback.close()
            else:
                _download_sequential(
                    response,
                    partial,
                    destination_name=destination.name,
                    total=total,
                    max_bytes=max_bytes,
                    show_progress=show_progress,
                    start_time=start,
                )
        finally:
            response.close()
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(destination)


def _newest_snapshot(raw_root: Path, provider: str, filename: str) -> Path | None:
    candidates = sorted((raw_root / provider).glob(f"*/{filename}"), reverse=True)
    return candidates[0] if candidates else None


def _newest_unlocode_snapshot(raw_root: Path) -> Path | None:
    candidates: list[tuple[tuple[int, int], Path]] = []
    for path in (raw_root / "unlocode").glob("*/unlocode-*-artifacts.zip"):
        release = path.parent.name
        match = re.fullmatch(r"(\d{4})-([1-9]\d*)", release)
        if match is not None and path.name == f"unlocode-{release}-artifacts.zip":
            candidates.append(((int(match[1]), int(match[2])), path))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


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
    geonames_path = _snapshot_target(
        raw_root, "geonames", "allCountries.zip", label, refresh, explicit_label
    )
    unlocode_path = None if refresh else _newest_unlocode_snapshot(raw_root)
    unlocode_release = unlocode_path.parent.name if unlocode_path is not None else None
    headers = {"User-Agent": _user_agent()}
    downloaded: set[Path] = set()
    needs_network = (
        refresh
        or not wpi_path.exists()
        or unlocode_path is None
        or not geonames_path.exists()
    )
    if needs_network:
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(10.0, read=30.0),
                headers=headers,
            ) as client:
                if unlocode_path is None:
                    unlocode_release = _discover_latest_unlocode_release(client)
                    unlocode_path = (
                        raw_root
                        / "unlocode"
                        / unlocode_release
                        / f"unlocode-{unlocode_release}-artifacts.zip"
                    )
                if unlocode_path is None or unlocode_release is None:
                    raise SourceDataError("no UN/LOCODE snapshot could be selected")
                unlocode_url = _unlocode_artifact_url(unlocode_release)
                downloads = [
                    (url, path, max_bytes)
                    for url, path, max_bytes in (
                        (WPI_URL, wpi_path, _WPI_MAX_DOWNLOAD_BYTES),
                        (
                            unlocode_url,
                            unlocode_path,
                            _UNLOCODE_MAX_DOWNLOAD_BYTES,
                        ),
                        (
                            GEONAMES_URL,
                            geonames_path,
                            _GEONAMES_MAX_DOWNLOAD_BYTES,
                        ),
                    )
                    if refresh or not path.exists()
                ]
                for url, path, max_bytes in downloads:
                    _download(client, url, path, max_bytes=max_bytes)
                downloaded = {path for _, path, _ in downloads}
        except (httpx.HTTPError, OSError, TimeoutError) as error:
            raise SourceDataError(
                f"public reference download failed: {error}"
            ) from error

    if unlocode_path is None or unlocode_release is None:
        raise SourceDataError("no UN/LOCODE snapshot could be selected")
    unlocode_url = _unlocode_artifact_url(unlocode_release)
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
                "url": unlocode_url,
                "release": unlocode_release,
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
