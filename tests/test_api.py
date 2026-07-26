from __future__ import annotations

from typing import NoReturn

import httpx
import pytest

pytest.importorskip("fastapi", reason="tests the optional 'api' extra")

from test_ports import alias_frame, registry_frame  # noqa: E402

from sea_mile import Port, PortRegistry  # noqa: E402
from sea_mile.api import create_app  # noqa: E402
from sea_mile.router import SeaRoute  # noqa: E402
from sea_mile.routing import RouteQualityFlag  # noqa: E402


class FakeRouter:
    def route(self, origin: Port, destination: Port) -> SeaRoute:
        assert origin.latitude is not None
        assert origin.longitude is not None
        assert destination.latitude is not None
        assert destination.longitude is not None
        return SeaRoute(
            origin=origin,
            destination=destination,
            distance_nmi=412.5,
            great_circle_nmi=400.0,
            detour_ratio=1.03125,
            quality_flag=RouteQualityFlag.OK,
            geometry={
                "type": "LineString",
                "coordinates": [
                    [origin.longitude, origin.latitude],
                    [destination.longitude, destination.latitude],
                ],
            },
            engine="test",
            engine_version="1",
            algorithm="astar",
            backend="test",
            restrictions=(),
        )


class MissingRoutingRouter:
    def route(self, origin: Port, destination: Port) -> NoReturn:
        raise ImportError("routing needs the 'routing' extra")


@pytest.fixture
def registry() -> PortRegistry:
    return PortRegistry(registry_frame(), alias_frame())


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_route_endpoint_returns_distance_and_geojson(
    registry: PortRegistry,
) -> None:
    transport = httpx.ASGITransport(
        app=create_app(registry=registry, router=FakeRouter())
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/route",
            params={"origin": "WPI:1", "destination": "WPI:2"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["distance_nmi"] == 412.5
    assert payload["geojson"]["geometry"]["coordinates"] == [
        [34.65, 36.8],
        [23.63, 37.94],
    ]
    assert payload["geojson"]["properties"]["routing_units"] == "nautical_miles"


@pytest.mark.anyio
async def test_route_endpoint_reports_unknown_ports(
    registry: PortRegistry,
) -> None:
    transport = httpx.ASGITransport(
        app=create_app(registry=registry, router=FakeRouter())
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/route",
            params={"origin": "missing", "destination": "WPI:2"},
        )

    assert response.status_code == 404
    assert "no exact port match" in response.json()["detail"]


@pytest.mark.anyio
async def test_route_endpoint_reports_missing_routing_extra(
    registry: PortRegistry,
) -> None:
    transport = httpx.ASGITransport(
        app=create_app(registry=registry, router=MissingRoutingRouter())
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/route",
            params={"origin": "WPI:1", "destination": "WPI:2"},
        )

    assert response.status_code == 503
    assert "routing" in response.json()["detail"]
