from __future__ import annotations

import importlib.util

import pytest

from sea_mile.router import SeaRouter
from sea_mile.routing import RouteQualityFlag

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
