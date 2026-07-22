from __future__ import annotations

import sys

import pytest

from sea_mile import Port, PortCoordinateError, SeaRouter


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
