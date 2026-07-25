"""SQLite-backed cache for deterministic routing backend results."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from sea_mile._routing_backend import BackendRoute, RoutingConfig

_SCHEMA_VERSION = 1


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
        origin: tuple[float, float],
        destination: tuple[float, float],
        config: RoutingConfig,
        engine: str,
        engine_version: str,
    ) -> str:
        """Build a stable, direction-sensitive key for effective route inputs."""

        payload = {
            "schema": _SCHEMA_VERSION,
            "origin": origin,
            "destination": destination,
            "config": config.to_dict(),
            "engine": engine,
            "engine_version": engine_version,
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
        geometry = json.loads(str(row[1]))
        if not isinstance(geometry, dict):
            return None
        return BackendRoute(distance_nmi=float(row[0]), geometry=geometry)

    def put(self, cache_key: str, result: BackendRoute) -> None:
        geometry_json = json.dumps(
            result.geometry, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        with self._connect() as connection:
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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection
