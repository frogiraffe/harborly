from __future__ import annotations

import json
import sys

import pytest

from sea_mile._routing_backend import BackendRoute, RoutingConfig, SeaRouteBackend
from sea_mile.exceptions import RoutingError, RoutingErrorReason
from sea_mile.geo import great_circle_nmi
from sea_mile.router import SeaRouter
from sea_mile.routing import RouteQualityFlag

ORIGIN = (36.8, 34.65)
DESTINATION = (37.94, 23.63)
GEOMETRY = {"type": "LineString", "coordinates": [[34.65, 36.8], [23.63, 37.94]]}
_UNSET = object()


class FakeBackend:
    """A minimal in-memory backend that never touches searoute."""

    def __init__(
        self,
        *,
        name="fake",
        version="9.9",
        distance_nmi=None,
        geometry=_UNSET,
        error=None,
    ):
        self._name = name
        self._version = version
        self._distance = distance_nmi
        self._geometry = GEOMETRY if geometry is _UNSET else geometry
        self._error = error
        self.calls = []

    @property
    def name(self):
        return self._name

    @property
    def version(self):
        return self._version

    def route(self, origin, destination, config):
        self.calls.append((origin, destination, config))
        if self._error is not None:
            raise self._error
        distance = self._distance
        if distance is None:
            distance = great_circle_nmi(*origin, *destination) * 1.1
        return BackendRoute(distance_nmi=distance, geometry=self._geometry)


def test_router_routes_with_a_fake_backend_and_never_imports_searoute(monkeypatch):
    monkeypatch.setitem(sys.modules, "searoute", None)
    fake = FakeBackend()

    route = SeaRouter(_routing_backend=fake).route_coordinates(*ORIGIN, *DESTINATION)

    assert route.engine == "fake"
    assert route.quality_flag == RouteQualityFlag.OK
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == ORIGIN


def test_provenance_records_backend_name_and_version():
    route = SeaRouter(
        _routing_backend=FakeBackend(name="fake", version="1.2.3")
    ).route_coordinates(*ORIGIN, *DESTINATION)
    summary = route.summary()

    assert summary["engine"] == "fake"
    assert summary["engine_version"] == "1.2.3"
    assert summary["algorithm"] == "astar"
    assert summary["backend"] == "networkx"
    assert summary["restrictions"] == ["northwest"]


def test_effective_config_serializes_deterministically():
    config = RoutingConfig(
        algorithm="astar", graph_backend="networkx", restrictions=("northwest",)
    )

    assert config.to_dict() == config.to_dict()
    assert config.to_dict() == {
        "algorithm": "astar",
        "backend": "networkx",
        "restrictions": ["northwest"],
    }
    assert json.loads(json.dumps(config.to_dict())) == config.to_dict()


def test_same_fake_result_gives_deterministic_route_output():
    first = SeaRouter(
        _routing_backend=FakeBackend(distance_nmi=600.0)
    ).route_coordinates(*ORIGIN, *DESTINATION)
    second = SeaRouter(
        _routing_backend=FakeBackend(distance_nmi=600.0)
    ).route_coordinates(*ORIGIN, *DESTINATION)

    assert first.summary() == second.summary()
    assert json.loads(json.dumps(first.summary())) == first.summary()


def test_backend_failure_becomes_a_routing_error():
    router = SeaRouter(_routing_backend=FakeBackend(error=RuntimeError("boom")))

    with pytest.raises(RoutingError, match="failed") as caught:
        router.route_coordinates(*ORIGIN, *DESTINATION)

    assert caught.value.reason == RoutingErrorReason.BACKEND_CALL_FAILED


def test_malformed_backend_geometry_is_rejected():
    router = SeaRouter(_routing_backend=FakeBackend(distance_nmi=600.0, geometry=None))

    with pytest.raises(RoutingError, match="geometry") as caught:
        router.route_coordinates(*ORIGIN, *DESTINATION)

    assert caught.value.reason == RoutingErrorReason.MALFORMED_BACKEND_RESULT


def test_implausible_backend_distance_is_rejected():
    router = SeaRouter(_routing_backend=FakeBackend(distance_nmi=1.0))

    with pytest.raises(RoutingError, match="plausibility") as caught:
        router.route_coordinates(*ORIGIN, *DESTINATION)

    assert caught.value.reason == RoutingErrorReason.IMPLAUSIBLE_ROUTE


def test_routing_error_reasons_are_distinct_stable_strings():
    reasons = [
        RoutingErrorReason.BACKEND_CALL_FAILED,
        RoutingErrorReason.MALFORMED_BACKEND_RESULT,
        RoutingErrorReason.IMPLAUSIBLE_ROUTE,
    ]

    assert [str(reason) for reason in reasons] == [
        "backend_call_failed",
        "malformed_backend_result",
        "implausible_route",
    ]
    assert len(set(reasons)) == 3


def test_quality_assessment_stays_in_sea_mile_not_the_backend():
    great_circle = great_circle_nmi(*ORIGIN, *DESTINATION)
    route = SeaRouter(
        _routing_backend=FakeBackend(distance_nmi=great_circle * 4)
    ).route_coordinates(*ORIGIN, *DESTINATION)

    assert route.quality_flag == RouteQualityFlag.HIGH_DETOUR_RATIO
    assert route.detour_ratio == pytest.approx(4.0)


def test_default_backend_is_searoute():
    assert SeaRouteBackend().name == "searoute"
