from __future__ import annotations

import importlib.util

import pytest

from harborly.ports import Port
from harborly.router import SeaRouter
from harborly.routing import RouteQualityFlag

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("searoute") is None,
    reason="routing regression needs the routing extra",
)

# name, (origin lat, lon), (destination lat, lon). Real sea routes, checked with
# tolerances and structural invariants rather than exact distances, so the suite
# survives a routing-engine update.
ROUTES = [
    ("piraeus_to_mersin", (37.94, 23.63), (36.80, 34.65)),
    ("rotterdam_to_lisbon", (51.95, 4.14), (38.70, -9.10)),
    ("singapore_to_colombo", (1.26, 103.83), (6.95, 79.85)),
]


@pytest.mark.parametrize(("name", "origin", "destination"), ROUTES)
def test_route_respects_physical_invariants(name, origin, destination) -> None:
    route = SeaRouter().route_coordinates(
        origin[0], origin[1], destination[0], destination[1]
    )

    # A sea route is never materially shorter than the great-circle lower bound.
    assert route.distance_nmi + 0.5 >= route.great_circle_nmi, name
    assert route.distance_nmi > 0
    assert route.detour_ratio is not None
    assert route.detour_ratio >= 0.99
    assert route.quality_flag in {
        RouteQualityFlag.OK,
        RouteQualityFlag.HIGH_DETOUR_RATIO,
    }
    assert route.geometry["type"] == "LineString"
    assert len(route.geometry["coordinates"]) >= 2


def test_routing_is_deterministic() -> None:
    first = SeaRouter().route_coordinates(37.94, 23.63, 36.80, 34.65)
    second = SeaRouter().route_coordinates(37.94, 23.63, 36.80, 34.65)

    assert first.distance_nmi == second.distance_nmi
    assert first.geometry == second.geometry


def test_default_backend_matrix_matches_single_and_spawn_workers() -> None:
    ports = [
        Port(
            registry_id="TEST:PIRAEUS",
            provider="TEST",
            provider_id="PIRAEUS",
            country_code="GR",
            name="Piraeus",
            latitude=37.94,
            longitude=23.63,
            unlocode="GRPIR",
            function_code="port",
            source_version="test",
            coordinate_resolution="test",
        ),
        Port(
            registry_id="TEST:MERSIN",
            provider="TEST",
            provider_id="MERSIN",
            country_code="TR",
            name="Mersin",
            latitude=36.80,
            longitude=34.65,
            unlocode="TRMER",
            function_code="port",
            source_version="test",
            coordinate_resolution="test",
        ),
    ]

    single_worker = SeaRouter().distance_matrix(ports, max_workers=1)
    spawn_workers = SeaRouter().distance_matrix(ports, max_workers=2)

    assert spawn_workers == single_worker
