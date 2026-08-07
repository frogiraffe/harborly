from __future__ import annotations

import inspect
import sys

import pytest

from harborly import PassageRestriction, Port, PortCoordinateError, SeaRouter
from harborly.router import SeaRoute
from harborly.routing import RouteQualityFlag


def port(
    registry_id: str,
    name: str,
    latitude: float | None,
    longitude: float | None,
) -> Port:
    return Port(
        registry_id=registry_id,
        provider="TEST",
        provider_id=registry_id,
        country_code="ZZ",
        name=name,
        latitude=latitude,
        longitude=longitude,
        unlocode=None,
        function_code="port",
        source_version="test",
        coordinate_resolution="test",
    )


def test_router_returns_explicit_nautical_miles_and_geojson() -> None:
    origin = port("TEST:1", "Eastern Mediterranean", 36.8, 34.65)
    destination = port("TEST:2", "Piraeus", 37.94, 23.63)

    route = SeaRouter().route(origin, destination)
    feature = route.to_geojson_feature()

    assert route.distance_nmi >= route.great_circle_nmi - 0.5
    assert route.distance_nmi > 0
    assert route.engine == "searoute"
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "LineString"
    assert feature["properties"]["routing_units"] == "nautical_miles"


def test_router_memoizes_identical_pairs() -> None:
    origin = port("TEST:1", "Eastern Mediterranean", 36.8, 34.65)
    destination = port("TEST:2", "Piraeus", 37.94, 23.63)

    router = SeaRouter()
    first = router.route(origin, destination)
    second = router.route(origin, destination)

    assert first is second


def test_route_coordinates_needs_no_registry() -> None:
    route = SeaRouter().route_coordinates(36.8, 34.65, 37.94, 23.63)

    assert route.distance_nmi >= route.great_circle_nmi - 0.5
    assert route.origin.provider == "COORDINATE"


def test_distance_matrix_is_square_with_zero_diagonal() -> None:
    origin = port("TEST:1", "Eastern Mediterranean", 36.8, 34.65)
    destination = port("TEST:2", "Piraeus", 37.94, 23.63)

    matrix = SeaRouter().distance_matrix([origin, destination])

    assert len(matrix) == 2
    assert matrix[0][0] == 0.0
    assert matrix[1][1] == 0.0
    assert matrix[0][1] > 0
    assert matrix[0][1] == matrix[1][0]


def test_router_cache_reflects_config_change() -> None:
    origin = port("TEST:1", "Eastern Mediterranean", 36.8, 34.65)
    destination = port("TEST:2", "Piraeus", 37.94, 23.63)

    router = SeaRouter()
    first = router.route(origin, destination)
    router.restrictions = ()
    second = router.route(origin, destination)

    assert first is not second
    assert second.restrictions == ()


def test_router_rejects_missing_coordinates() -> None:
    origin = port("TEST:1", "Missing", None, None)
    destination = port("TEST:2", "Piraeus", 37.94, 23.63)

    with pytest.raises(PortCoordinateError, match="no conflict-free coordinate"):
        SeaRouter().route(origin, destination)


def test_route_without_routing_extra_gives_helpful_error(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "searoute", None)
    origin = port("TEST:1", "Eastern Mediterranean", 36.8, 34.65)
    destination = port("TEST:2", "Piraeus", 37.94, 23.63)

    with pytest.raises(ImportError, match="routing"):
        SeaRouter().route(origin, destination)


def test_router_rejects_out_of_range_coordinates() -> None:
    origin = port("TEST:1", "Invalid", 95.0, 34.65)
    destination = port("TEST:2", "Piraeus", 37.94, 23.63)

    with pytest.raises(PortCoordinateError, match="outside valid"):
        SeaRouter().route(origin, destination)


def test_passage_restriction_enum_integration() -> None:
    router = SeaRouter(
        restrictions=[PassageRestriction.SUEZ, "panama", PassageRestriction.KIEL]
    )
    assert router.restrictions == ("suez", "panama", "kiel")
    assert (
        inspect.signature(SeaRouter).parameters["restrictions"].annotation
        == "Iterable[str | PassageRestriction]"
    )


def _sequence_leg(origin: Port, destination: Port, distance_nmi: float) -> SeaRoute:
    return SeaRoute(
        origin=origin,
        destination=destination,
        distance_nmi=distance_nmi,
        great_circle_nmi=distance_nmi - 1.0,
        detour_ratio=1.1,
        quality_flag=RouteQualityFlag.OK,
        geometry={"type": "LineString", "coordinates": []},
        engine="fake",
        engine_version="1",
        algorithm="astar",
        backend="fake",
        restrictions=("suez",),
    )


def test_route_sequence_delegates_ordered_legs_and_propagates_first_error(
    monkeypatch,
) -> None:
    port_a = port("TEST:1", "Mersin", 36.8, 34.65)
    port_b = port("TEST:2", "Piraeus", 37.94, 23.63)
    port_c = port("TEST:3", "Istanbul", 41.0, 28.97)
    first = _sequence_leg(port_a, port_b, 10.0)
    second = _sequence_leg(port_b, port_c, 20.0)
    calls: list[tuple[Port, Port, float | None]] = []

    def fake_route(
        origin: Port, destination: Port, *, speed_knots: float | None = None
    ) -> SeaRoute:
        calls.append((origin, destination, speed_knots))
        return (first, second)[len(calls) - 1]

    router = SeaRouter(_routing_backend=object())
    monkeypatch.setattr(router, "route", fake_route)
    sequence = router.route_sequence([port_a, port_b, port_c], speed_knots=12.0)

    assert sequence.legs[0] is first
    assert sequence.legs[1] is second
    assert sequence.total_distance_nmi == 30.0
    assert calls == [(port_a, port_b, 12.0), (port_b, port_c, 12.0)]

    error = RuntimeError("second leg failed")
    calls.clear()

    def failing_route(
        origin: Port, destination: Port, *, speed_knots: float | None = None
    ) -> SeaRoute:
        calls.append((origin, destination, speed_knots))
        if len(calls) == 2:
            raise error
        return first

    monkeypatch.setattr(router, "route", failing_route)
    with pytest.raises(RuntimeError) as exc_info:
        router.route_sequence([port_a, port_b, port_c], speed_knots=12.0)

    assert exc_info.value is error
    assert calls == [(port_a, port_b, 12.0), (port_b, port_c, 12.0)]


def test_route_sequence_multi_leg() -> None:
    port_a = port("TEST:1", "Mersin", 36.8, 34.65)
    port_b = port("TEST:2", "Piraeus", 37.94, 23.63)
    port_c = port("TEST:3", "Istanbul", 41.0, 28.97)

    seq = SeaRouter().route_sequence([port_a, port_b, port_c])

    assert len(seq.legs) == 2
    assert seq.total_distance_nmi == seq.legs[0].distance_nmi + seq.legs[1].distance_nmi
    geojson = seq.to_geojson_feature_collection()
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 2


def test_vessel_speed_duration_calculation() -> None:
    port_a = port("TEST:1", "Mersin", 36.8, 34.65)
    port_b = port("TEST:2", "Piraeus", 37.94, 23.63)

    route = SeaRouter().route(port_a, port_b, speed_knots=14.0)

    assert route.speed_knots == 14.0
    assert route.duration_hours is not None
    assert route.duration_hours == round(route.distance_nmi / 14.0, 2)
    assert route.duration_days is not None
    assert route.duration_days == round(route.duration_hours / 24.0, 2)
    assert route.summary()["speed_knots"] == 14.0


@pytest.mark.parametrize(
    "speed_knots", [0.0, -1.0, float("nan"), float("inf"), -float("inf")]
)
def test_route_rejects_non_finite_or_non_positive_speed_before_routing(
    speed_knots: float,
) -> None:
    origin = port("TEST:1", "Mersin", 36.8, 34.65)
    destination = port("TEST:2", "Piraeus", 37.94, 23.63)

    with pytest.raises(ValueError, match="finite positive"):
        SeaRouter(_routing_backend=object()).route(
            origin, destination, speed_knots=speed_knots
        )


def test_route_coordinates_forwards_speed_to_route(monkeypatch) -> None:
    router = SeaRouter(_routing_backend=object())
    captured: dict[str, float | None] = {}

    def fake_route(origin, destination, *, speed_knots=None):
        captured["speed_knots"] = speed_knots
        return _sequence_leg(origin, destination, 10.0)

    monkeypatch.setattr(router, "route", fake_route)

    route = router.route_coordinates(36.8, 34.65, 37.94, 23.63, speed_knots=12.0)

    assert route.speed_knots is None
    assert captured == {"speed_knots": 12.0}
