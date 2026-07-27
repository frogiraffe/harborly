"""SQLite-backed cache for deterministic routing backend results."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from math import isfinite
from pathlib import Path
from typing import TypeGuard

from sea_mile._routing_backend import BackendRoute, RoutingConfig
from sea_mile.coordinates import LatLon

_SCHEMA_VERSION = 1


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
    if not isinstance(geometry, dict):
        return False
    if geometry.get("type") != "LineString":
        return False
    coords = geometry.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return False
    for pt in coords:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            return False
        if not (_is_finite_number(pt[0]) and _is_finite_number(pt[1])):
            return False
    return True


class RouteCache:
    """Persist raw backend results across router instances and processes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
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
            "schema": _SCHEMA_VERSION,
            "origin": origin.as_tuple(),
            "destination": destination.as_tuple(),
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

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=30.0,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("PRAGMA synchronous=NORMAL")
            yield connection
        finally:
            connection.close()

    def __enter__(self) -> RouteCache:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass
