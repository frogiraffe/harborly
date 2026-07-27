import json
import sqlite3
from contextlib import closing
from typing import Any

import pytest

from sea_mile._routing_backend import BackendRoute, RoutingConfig
from sea_mile.coordinates import LatLon
from sea_mile.route_cache import RouteCache


@pytest.fixture
def cache(tmp_path):
    return RouteCache(tmp_path / "test.db")


def _cache_key(cache, graph_version=""):
    return cache.key(
        origin=LatLon(36.8, 34.65),
        destination=LatLon(37.94, 23.63),
        config=RoutingConfig(
            algorithm="astar", graph_backend="networkx", restrictions=("northwest",)
        ),
        engine="test",
        engine_version="1.0",
        graph_version=graph_version,
    )


def _insert_raw(cache, cache_key, distance, geometry_json):
    conn = sqlite3.connect(cache.path)
    conn.execute(
        "INSERT OR REPLACE INTO routes "
        "(cache_key, distance_nmi, geometry_json) VALUES (?, ?, ?)",
        (cache_key, distance, geometry_json),
    )
    conn.commit()
    conn.close()


def test_valid_entry_round_trip(cache):
    key = _cache_key(cache)
    route = BackendRoute(
        distance_nmi=100.5,
        geometry={"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]]},
    )
    cache.put(key, route)

    cached_route = cache.get(key)
    assert cached_route is not None
    assert cached_route.distance_nmi == 100.5
    assert cached_route.geometry == {
        "type": "LineString",
        "coordinates": [[1.0, 2.0], [3.0, 4.0]],
    }


def test_cache_closes_every_connection(tmp_path, monkeypatch):
    original_connect = sqlite3.connect
    inject_locked_wal = True

    class TrackingConnection(sqlite3.Connection):
        closed = False

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.statements: list[str] = []

        def execute(self, sql: str, parameters: Any = (), /):
            nonlocal inject_locked_wal
            self.statements.append(sql)
            if sql == "PRAGMA journal_mode=WAL" and inject_locked_wal:
                inject_locked_wal = False
                raise sqlite3.OperationalError("database is locked")
            return super().execute(sql, parameters)

        def close(self) -> None:
            self.closed = True
            super().close()

    connections: list[TrackingConnection] = []

    def tracked_connect(*args: Any, **kwargs: Any) -> TrackingConnection:
        kwargs["factory"] = TrackingConnection
        connection = original_connect(*args, **kwargs)
        assert isinstance(connection, TrackingConnection)
        connections.append(connection)
        return connection

    monkeypatch.setattr("sea_mile.route_cache.sqlite3.connect", tracked_connect)
    monkeypatch.setattr("sea_mile.route_cache.sleep", lambda _: None)

    cache = RouteCache(tmp_path / "tracked.db")
    key = _cache_key(cache)
    route = BackendRoute(
        distance_nmi=100.5,
        geometry={"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]]},
    )
    cache.put(key, route)
    assert cache.get(key) == route
    cache.delete(key)

    assert len(connections) == 4
    assert all(connection.closed for connection in connections)
    assert connections[0].statements.count("PRAGMA journal_mode=WAL") == 2
    for connection in connections:
        assert connection.statements.index("PRAGMA busy_timeout=30000") < (
            connection.statements.index("PRAGMA journal_mode=WAL")
        )


def test_corrupt_json_eviction(cache):
    key = _cache_key(cache)
    _insert_raw(
        cache,
        key,
        100.5,
        '{"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]',
    )

    assert cache.get(key) is None

    # Verify it's deleted
    conn = sqlite3.connect(cache.path)
    cursor = conn.execute("SELECT COUNT(*) FROM routes WHERE cache_key = ?", (key,))
    assert cursor.fetchone()[0] == 0
    conn.close()


def test_non_dict_geometry_eviction(cache):
    key = _cache_key(cache)
    _insert_raw(cache, key, 100.5, '"LineString"')

    assert cache.get(key) is None

    # Verify it's deleted
    conn = sqlite3.connect(cache.path)
    cursor = conn.execute("SELECT COUNT(*) FROM routes WHERE cache_key = ?", (key,))
    assert cursor.fetchone()[0] == 0
    conn.close()


def test_negative_distance_eviction(cache):
    key = _cache_key(cache)
    _insert_raw(
        cache,
        key,
        -10.0,
        '{"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]]}',
    )
    assert cache.get(key) is None


def test_infinity_distance_eviction(cache):
    key = _cache_key(cache)
    _insert_raw(
        cache,
        key,
        float("inf"),
        '{"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]]}',
    )
    assert cache.get(key) is None


def test_put_validation_rejects_invalid_distance(cache):
    key = _cache_key(cache)
    geometry = {
        "type": "LineString",
        "coordinates": [[1.0, 2.0], [3.0, 4.0]],
    }
    for distance in (-10.0, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite and non-negative"):
            cache.put(key, BackendRoute(distance_nmi=distance, geometry=geometry))


@pytest.mark.parametrize("distance", [0.0, 100.5])
def test_put_validation_accepts_valid_distance(cache, distance):
    key = _cache_key(cache)
    route = BackendRoute(
        distance_nmi=distance,
        geometry={"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]]},
    )

    cache.put(key, route)

    assert cache.get(key) == route


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "LineString", "coordinates": []},
        {"type": "LineString", "coordinates": [[0.0, 0.0]]},
        {
            "type": "LineString",
            "coordinates": [[float("nan"), 0.0], [1.0, 1.0]],
        },
        {
            "type": "LineString",
            "coordinates": [[float("inf"), 0.0], [1.0, 1.0]],
        },
    ],
)
def test_put_validation_rejects_invalid_geometry(cache, geometry):
    with pytest.raises(ValueError, match="LineString"):
        cache.put(_cache_key(cache), BackendRoute(distance_nmi=10.0, geometry=geometry))


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "LineString", "coordinates": []},
        {"type": "LineString", "coordinates": [[0.0, 0.0]]},
        {
            "type": "LineString",
            "coordinates": [[float("nan"), 0.0], [1.0, 1.0]],
        },
        {
            "type": "LineString",
            "coordinates": [[float("inf"), 0.0], [1.0, 1.0]],
        },
    ],
)
def test_get_evicts_invalid_geometry(cache, geometry):
    key = _cache_key(cache)
    _insert_raw(cache, key, 10.0, json.dumps(geometry))

    assert cache.get(key) is None

    with closing(sqlite3.connect(cache.path)) as connection, connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM routes WHERE cache_key = ?", (key,)
        ).fetchone()[0]
    assert remaining == 0


def test_put_validation_accepts_valid_geometry(cache):
    key = _cache_key(cache)
    route = BackendRoute(
        distance_nmi=10.0,
        geometry={"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
    )

    cache.put(key, route)

    assert cache.get(key) == route


def test_non_numeric_coordinates_in_geometry_eviction(cache):
    key = _cache_key(cache)
    _insert_raw(
        cache,
        key,
        100.5,
        '{"type": "LineString", "coordinates": [["a", "b"], [3.0, 4.0]]}',
    )
    assert cache.get(key) is None


def test_graph_version_in_cache_key(cache):
    key1 = _cache_key(cache, graph_version="1.0")
    key2 = _cache_key(cache, graph_version="2.0")
    assert key1 != key2


def test_graph_version_default(cache):
    key1 = _cache_key(cache)
    key2 = _cache_key(cache, graph_version="")
    assert key1 == key2


def test_cache_records_and_reports_database_schema(cache):
    info = cache.info()

    assert info.schema_version == 1
    assert info.entries == 0
    assert info.path == str(cache.path.resolve())
    assert info.database_bytes > 0


def test_legacy_unversioned_cache_is_adopted(tmp_path):
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE routes (
                cache_key TEXT PRIMARY KEY,
                distance_nmi REAL NOT NULL,
                geometry_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    cache = RouteCache(path)

    assert cache.info().schema_version == 1


def test_newer_cache_schema_is_rejected(tmp_path):
    path = tmp_path / "future.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA user_version = 2")

    with pytest.raises(ValueError, match="newer than supported"):
        RouteCache(path)


def test_cache_prune_clear_and_vacuum(cache):
    old_key = _cache_key(cache, graph_version="old")
    current_key = _cache_key(cache, graph_version="current")
    route = BackendRoute(
        distance_nmi=10.0,
        geometry={"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
    )
    cache.put(old_key, route)
    cache.put(current_key, route)
    with closing(sqlite3.connect(cache.path)) as connection, connection:
        connection.execute(
            "UPDATE routes SET created_at = datetime('now', '-120 days') "
            "WHERE cache_key = ?",
            (old_key,),
        )

    assert cache.prune(older_than_days=90) == 1
    assert cache.info().entries == 1
    cache.vacuum()
    assert cache.clear() == 1
    assert cache.info().entries == 0


@pytest.mark.parametrize("days", [0, -1, True])
def test_cache_prune_rejects_invalid_retention(cache, days):
    with pytest.raises(ValueError, match="positive integer"):
        cache.prune(older_than_days=days)
