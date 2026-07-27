from __future__ import annotations

import json
import multiprocessing
import sqlite3
from types import SimpleNamespace

import pandas as pd
import pandera.errors
import pytest

from sea_mile._routing_backend import BackendRoute, RoutingConfig, SeaRouteBackend
from sea_mile.coordinates import LatLon
from sea_mile.data_contracts import (
    validate_distance_matrix,
    validate_review_decisions,
    validate_review_frame,
)
from sea_mile.geo import great_circle_nmi
from sea_mile.ports import Port
from sea_mile.route_cache import RouteCache
from sea_mile.router import SeaRouter


class DeterministicBackend:
    name = "deterministic"
    version = "1"
    symmetric = True

    def route(
        self, origin: LatLon, destination: LatLon, config: RoutingConfig
    ) -> BackendRoute:
        distance = great_circle_nmi(*origin, *destination) * 1.1
        return BackendRoute(
            distance_nmi=distance,
            geometry={
                "type": "LineString",
                "coordinates": [
                    origin.to_lon_lat().as_list(),
                    destination.to_lon_lat().as_list(),
                ],
            },
        )


class FlakyBackend(DeterministicBackend):
    def __init__(self) -> None:
        self.calls = 0

    def route(
        self, origin: LatLon, destination: LatLon, config: RoutingConfig
    ) -> BackendRoute:
        self.calls += 1
        if self.calls < 3:
            raise TimeoutError("temporary timeout")
        return super().route(origin, destination, config)


class AsymmetricBackend(DeterministicBackend):
    symmetric = False

    def route(
        self, origin: LatLon, destination: LatLon, config: RoutingConfig
    ) -> BackendRoute:
        result = super().route(origin, destination, config)
        direction_adjustment = max(destination.latitude - origin.latitude, 0.0)
        return BackendRoute(
            distance_nmi=result.distance_nmi + direction_adjustment,
            geometry=result.geometry,
        )


class UnpicklableBackend(DeterministicBackend):
    def __getstate__(self) -> dict[str, object]:
        raise TypeError("test backend cannot be serialized")


def _port(identifier: str, latitude: float, longitude: float) -> Port:
    return Port(
        registry_id=identifier,
        provider="TEST",
        provider_id=identifier,
        country_code="ZZ",
        name=identifier,
        latitude=latitude,
        longitude=longitude,
        unlocode=None,
        function_code="port",
        source_version="test",
        coordinate_resolution="test",
    )


def _cache_writer(payload: tuple[str, int]) -> None:
    path, value = payload
    cache = RouteCache(path)
    config = RoutingConfig("astar", "networkx", ("northwest",))
    origin = LatLon(10.0 + value / 1000, 20.0)
    destination = LatLon(11.0, 21.0 + value / 1000)
    key = cache.key(
        origin=origin,
        destination=destination,
        config=config,
        engine="test",
        engine_version="1",
    )
    cache.put(
        key,
        BackendRoute(
            distance_nmi=float(value),
            geometry={
                "type": "LineString",
                "coordinates": [
                    origin.to_lon_lat().as_list(),
                    destination.to_lon_lat().as_list(),
                ],
            },
        ),
    )


def test_searoute_boundary_converts_lat_lon_to_lon_lat(monkeypatch) -> None:
    calls: list[tuple[list[float], list[float]]] = []

    def route(origin, destination, **kwargs):
        calls.append((origin, destination))
        return SimpleNamespace(
            properties={"length": 10.0},
            geometry={"type": "LineString", "coordinates": [origin, destination]},
        )

    module = SimpleNamespace(__version__="test", searoute=route)
    monkeypatch.setattr(SeaRouteBackend, "_module", staticmethod(lambda: module))

    SeaRouteBackend().route(
        LatLon(latitude=36.8, longitude=34.65),
        LatLon(latitude=37.94, longitude=23.63),
        RoutingConfig("astar", "networkx", ("northwest",)),
    )

    assert calls == [([34.65, 36.8], [23.63, 37.94])]


def test_transient_backend_errors_use_exponential_backoff(monkeypatch) -> None:
    backend = FlakyBackend()
    sleeps: list[float] = []
    monkeypatch.setattr("sea_mile.router.time.sleep", sleeps.append)

    result = SeaRouter(
        _routing_backend=backend,
        retry_attempts=4,
        backoff_seconds=0.1,
    ).route(_port("A", 36.8, 34.65), _port("B", 37.94, 23.63))

    assert result.distance_nmi > 0
    assert backend.calls == 3
    assert len(sleeps) == 2
    assert 0.05 <= sleeps[0] <= 0.15
    assert 0.1 <= sleeps[1] <= 0.3


@pytest.mark.parametrize(
    ("attempts", "backoff"),
    [
        (9, 0.25),
        (4, float("inf")),
        (4, float("nan")),
        (4, 8.01),
    ],
)
def test_retry_configuration_has_hard_upper_bounds(attempts, backoff) -> None:
    with pytest.raises(ValueError):
        SeaRouter(
            _routing_backend=DeterministicBackend(),
            retry_attempts=attempts,
            backoff_seconds=backoff,
        )


def test_distance_matrix_uses_process_workers_and_remains_symmetric(tmp_path) -> None:
    ports = [
        _port("A", 36.8, 34.65),
        _port("B", 37.94, 23.63),
        _port("C", 41.0, 29.0),
        _port("D", 38.4, 27.1),
    ]
    matrix = SeaRouter(
        cache_path=tmp_path / "routes.sqlite3",
        _routing_backend=DeterministicBackend(),
    ).distance_matrix(ports, max_workers=2)

    validate_distance_matrix([port.registry_id for port in ports], matrix)
    assert all(
        matrix[row][column] == matrix[column][row]
        for row in range(4)
        for column in range(4)
    )


def test_distance_matrix_calculates_both_directions_for_asymmetric_backend() -> None:
    low = _port("LOW", 10.0, 20.0)
    high = _port("HIGH", 12.0, 21.0)

    matrix = SeaRouter(_routing_backend=AsymmetricBackend()).distance_matrix(
        [low, high], max_workers=1
    )

    assert matrix[0][1] > matrix[1][0]
    validate_distance_matrix(["LOW", "HIGH"], matrix)


def test_sqlite_cache_handles_concurrent_process_writers(tmp_path) -> None:
    cache_path = tmp_path / "routes.sqlite3"
    context = multiprocessing.get_context("spawn")
    with context.Pool(4) as pool:
        pool.map(_cache_writer, [(str(cache_path), value) for value in range(24)])

    with sqlite3.connect(cache_path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        rows = connection.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
        geometries = connection.execute("SELECT geometry_json FROM routes").fetchall()
    assert journal_mode == "wal"
    assert rows == 24
    assert all(isinstance(json.loads(value), dict) for (value,) in geometries)


def test_review_contract_rejects_invalid_rows() -> None:
    valid = pd.DataFrame(
        [
            {
                "row_id": "1",
                "input_name": "Mersin",
                "input_country": "TR",
                "status": "review_required",
                "reason_code": "multiple_identities",
                "candidate_registry_id": "WPI:1",
                "candidate_provider": "NGA_WPI",
                "candidate_name": "Mersin",
                "candidate_country_code": "TR",
                "candidate_latitude": 36.8,
                "candidate_longitude": 34.65,
                "candidate_unlocode": "TRMER",
            }
        ]
    )
    validate_review_frame(valid)

    with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
        validate_review_frame(valid.assign(candidate_latitude=91.0))
    with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
        validate_review_frame(valid.assign(unexpected="no"))
    with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
        validate_review_decisions(
            pd.DataFrame([{"row_id": "", "chosen_registry_id": "WPI:1"}])
        )
    with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
        validate_review_decisions(
            pd.DataFrame([{"row_id": 1024, "chosen_registry_id": 77}])
        )
    with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
        validate_review_decisions(
            pd.DataFrame([{"row_id": "   ", "chosen_registry_id": "WPI:1"}])
        )


def test_review_contract_preserves_leading_zero_ids() -> None:
    frame = pd.DataFrame([{"row_id": "01024", "chosen_registry_id": "WPI:00077"}])

    validated = validate_review_decisions(frame)

    assert validated.iloc[0].to_dict() == {
        "row_id": "01024",
        "chosen_registry_id": "WPI:00077",
    }


def test_review_contract_allows_an_unresolved_row_without_candidates() -> None:
    frame = pd.DataFrame(
        [
            {
                "row_id": "1",
                "input_name": "Atlantis",
                "input_country": "",
                "status": "unresolved",
                "reason_code": "no_candidate",
                "candidate_registry_id": None,
                "candidate_provider": None,
                "candidate_name": None,
                "candidate_country_code": None,
                "candidate_latitude": None,
                "candidate_longitude": None,
                "candidate_unlocode": None,
            }
        ]
    )

    assert validate_review_frame(frame).iloc[0]["row_id"] == "1"


def test_distance_matrix_custom_backend_multiprocessing_regression() -> None:
    ports = [
        _port("A", 36.8, 34.65),
        _port("B", 37.94, 23.63),
    ]
    router_sym = SeaRouter(_routing_backend=DeterministicBackend())
    matrix_sym_w1 = router_sym.distance_matrix(ports, max_workers=1)
    matrix_sym_w2 = router_sym.distance_matrix(ports, max_workers=2)
    assert matrix_sym_w1 == matrix_sym_w2
    assert matrix_sym_w2[0][1] < 585.0

    router_asym = SeaRouter(_routing_backend=AsymmetricBackend())
    matrix_asym_w1 = router_asym.distance_matrix(ports, max_workers=1)
    matrix_asym_w2 = router_asym.distance_matrix(ports, max_workers=2)
    assert matrix_asym_w1 == matrix_asym_w2
    assert matrix_asym_w2[0][1] != matrix_asym_w2[1][0]


def test_distance_matrix_unpicklable_backend() -> None:
    ports = [
        _port("A", 36.8, 34.65),
        _port("B", 37.94, 23.63),
    ]
    router = SeaRouter(_routing_backend=UnpicklableBackend())
    matrix_w1 = router.distance_matrix(ports, max_workers=1)
    assert matrix_w1[0][1] > 0.0

    with pytest.raises(
        ValueError,
        match=(
            "routing backend must be serializable when max_workers is greater than one"
        ),
    ) as caught:
        router.distance_matrix(ports, max_workers=2)

    assert caught.value.__cause__ is None
