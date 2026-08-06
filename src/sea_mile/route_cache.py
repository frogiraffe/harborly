"""SQLite-backed cache for deterministic routing backend results."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from time import monotonic, sleep
from typing import TypeGuard, cast

from sea_mile._routing_backend import BackendRoute, RoutingConfig
from sea_mile.coordinates import LatLon
from sea_mile.geo import line_string_coordinates

_CACHE_KEY_SCHEMA_VERSION = 1
_DATABASE_SCHEMA_VERSION = 1
_BUSY_TIMEOUT_MS = 30_000
_WAL_RETRY_SECONDS = 0.05
_ROUTE_COLUMNS = {
    "cache_key",
    "distance_nmi",
    "geometry_json",
    "created_at",
}


@dataclass(frozen=True, slots=True)
class CacheInfo:
    """Operational metadata for one persistent route cache."""

    path: str
    schema_version: int
    entries: int
    oldest_created_at: str | None
    newest_created_at: str | None
    database_bytes: int
    wal_bytes: int

    def to_dict(self) -> dict[str, str | int | None]:
        """Return a JSON-serializable representation."""

        return cast(dict[str, str | int | None], asdict(self))


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    )


def _is_valid_cache_distance(distance: object) -> bool:
    if not _is_finite_number(distance):
        return False
    return distance >= 0.0


def _is_valid_cache_geometry(geometry: object) -> bool:
    try:
        line_string_coordinates(geometry)
    except ValueError:
        return False
    return True


def _enable_wal(connection: sqlite3.Connection) -> None:
    """Enable WAL while tolerating another process performing the same setup."""

    deadline = monotonic() + (_BUSY_TIMEOUT_MS / 1_000)
    while True:
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as error:
            remaining = deadline - monotonic()
            if "locked" not in str(error).lower() or remaining <= 0:
                raise
            sleep(min(_WAL_RETRY_SECONDS, remaining))


class RouteCache:
    """Persist raw backend results across router instances and processes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > _DATABASE_SCHEMA_VERSION:
                raise ValueError(
                    "route cache schema "
                    f"{version} is newer than supported schema "
                    f"{_DATABASE_SCHEMA_VERSION}"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS routes (
                    cache_key TEXT PRIMARY KEY,
                    distance_nmi REAL NOT NULL,
                    geometry_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(routes)").fetchall()
            }
            if columns != _ROUTE_COLUMNS:
                raise ValueError(
                    "route cache has an unsupported routes table; create a new "
                    "cache file or remove the incompatible cache"
                )
            if version < _DATABASE_SCHEMA_VERSION:
                connection.execute(f"PRAGMA user_version = {_DATABASE_SCHEMA_VERSION}")

    def key(
        self,
        *,
        origin: LatLon,
        destination: LatLon,
        config: RoutingConfig,
        engine: str,
        engine_version: str,
        graph_version: str = "",
    ) -> str:
        """Build a stable, direction-sensitive key for effective route inputs."""

        payload = {
            "schema": _CACHE_KEY_SCHEMA_VERSION,
            "origin": (origin.latitude, origin.longitude),
            "destination": (destination.latitude, destination.longitude),
            "config": config.to_dict(),
            "engine": engine,
            "engine_version": engine_version,
            "graph_version": graph_version,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def get(self, cache_key: str) -> BackendRoute | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT distance_nmi, geometry_json FROM routes WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        try:
            geometry = json.loads(str(row[1]))
        except (json.JSONDecodeError, TypeError):
            self.delete(cache_key)
            return None
        try:
            distance = float(row[0])
        except (TypeError, ValueError):
            self.delete(cache_key)
            return None

        if not _is_valid_cache_distance(distance) or not _is_valid_cache_geometry(
            geometry
        ):
            self.delete(cache_key)
            return None

        return BackendRoute(distance_nmi=distance, geometry=geometry)

    def put(self, cache_key: str, result: BackendRoute) -> None:
        if not _is_valid_cache_distance(result.distance_nmi):
            raise ValueError("cached route distance must be finite and non-negative")
        if not _is_valid_cache_geometry(result.geometry):
            raise ValueError(
                "cached route geometry must be a LineString with at least two "
                "finite coordinate pairs"
            )

        geometry_json = json.dumps(
            result.geometry, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO routes (cache_key, distance_nmi, geometry_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        distance_nmi = excluded.distance_nmi,
                        geometry_json = excluded.geometry_json,
                        created_at = CURRENT_TIMESTAMP
                    """,
                    (cache_key, result.distance_nmi, geometry_json),
                )
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def delete(self, cache_key: str) -> None:
        """Remove a cached result that fails current validation rules."""

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM routes WHERE cache_key = ?",
                (cache_key,),
            )

    def info(self) -> CacheInfo:
        """Return entry counts, timestamps, schema version, and file sizes."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*),
                    MIN(created_at),
                    MAX(created_at)
                FROM routes
                """
            ).fetchone()
            schema_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
        wal_path = Path(f"{self.path}-wal")
        return CacheInfo(
            path=str(self.path.resolve()),
            schema_version=schema_version,
            entries=int(row[0]),
            oldest_created_at=str(row[1]) if row[1] is not None else None,
            newest_created_at=str(row[2]) if row[2] is not None else None,
            database_bytes=self.path.stat().st_size if self.path.exists() else 0,
            wal_bytes=wal_path.stat().st_size if wal_path.exists() else 0,
        )

    def prune(self, *, older_than_days: int) -> int:
        """Delete entries older than a positive number of days."""

        if isinstance(older_than_days, bool) or older_than_days < 1:
            raise ValueError("older_than_days must be a positive integer")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "DELETE FROM routes WHERE created_at < datetime('now', ?)",
                    (f"-{older_than_days} days",),
                )
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
                return max(0, cursor.rowcount)

    def clear(self) -> int:
        """Delete every cached route and return the number removed."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute("DELETE FROM routes")
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
                return max(0, cursor.rowcount)

    def vacuum(self) -> None:
        """Reclaim free pages after explicit maintenance."""

        with self._connect() as connection:
            connection.execute("VACUUM")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=30.0,
            isolation_level=None,
        )
        try:
            connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            _enable_wal(connection)
            connection.execute("PRAGMA synchronous=NORMAL")
            yield connection
        finally:
            connection.close()
