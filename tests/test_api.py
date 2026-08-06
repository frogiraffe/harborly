from __future__ import annotations

from importlib.metadata import version

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
            "/v1/route",
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
            "/v1/route",
            params={"origin": "missing", "destination": "WPI:2"},
        )

    assert response.status_code == 404
    assert "no exact port match" in response.json()["error"]["message"]


@pytest.mark.anyio
async def test_root_redirects_to_interactive_docs(registry: PortRegistry) -> None:
    transport = httpx.ASGITransport(
        app=create_app(registry=registry, router=FakeRouter())
    )

    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get("/")

    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


@pytest.mark.anyio
async def test_health_endpoint_reports_package_version(registry: PortRegistry) -> None:
    transport = httpx.ASGITransport(
        app=create_app(registry=registry, router=FakeRouter())
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/livez")

    assert response.status_code == 200
    assert response.json() == {
        "service": "sea-mile",
        "status": "ok",
        "version": version("sea-mile"),
    }


def test_openapi_documents_route_contract_and_errors(registry: PortRegistry) -> None:
    schema = create_app(registry=registry, router=FakeRouter()).openapi()

    assert schema["info"]["title"] == "sea-mile API"
    assert schema["info"]["version"] == version("sea-mile")
    assert set(schema["paths"]) == {
        "/v1/livez",
        "/v1/readyz",
        "/v1/route",
    }

    route = schema["paths"]["/v1/route"]["get"]
    assert route["tags"] == ["routing"]
    assert route.get("deprecated") is not True
    assert route["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RouteResponse"
    }
    assert {"404", "409", "422", "500", "502", "503"} <= set(route["responses"])
    assert route["responses"]["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert {"RouteResponse", "RouteFeatureResponse", "ErrorResponse"} <= set(
        schema["components"]["schemas"]
    )
