from __future__ import annotations

from importlib.metadata import version
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
@pytest.mark.parametrize("path", ["/v1/route", "/route"])
async def test_route_endpoint_returns_distance_and_geojson(
    registry: PortRegistry, path: str
) -> None:
    transport = httpx.ASGITransport(
        app=create_app(registry=registry, router=FakeRouter())
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            path,
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
    assert "no exact port match" in response.json()["error"]["message"]


@pytest.mark.anyio
async def test_the_deprecated_alias_answers_exactly_like_the_versioned_path(
    registry: PortRegistry,
) -> None:
    """The alias exists for old callers, so it must not have its own behaviour."""

    transport = httpx.ASGITransport(
        app=create_app(registry=registry, router=MissingRoutingRouter())
    )
    params = {"origin": "WPI:1", "destination": "WPI:2"}

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        versioned = await client.get("/v1/route", params=params)
        alias = await client.get("/route", params=params)

    assert versioned.status_code == alias.status_code == 503
    assert versioned.json() == alias.json()
    assert alias.json()["error"]["code"] == "routing_unavailable"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("alias", "successor"), [("/route", "/v1/route"), ("/healthz", "/v1/livez")]
)
async def test_a_deprecated_path_tells_its_caller_so(
    registry: PortRegistry, alias: str, successor: str
) -> None:
    """A deprecation only recorded in OpenAPI is invisible to the caller using it."""

    transport = httpx.ASGITransport(
        app=create_app(registry=registry, router=FakeRouter())
    )
    params = {"origin": "WPI:1", "destination": "WPI:2"}

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        deprecated = await client.get(alias, params=params)
        current = await client.get(successor, params=params)

    assert deprecated.headers["deprecation"] == "true"
    assert successor in deprecated.headers["link"]
    assert "deprecation" not in current.headers


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
        response = await client.get("/healthz")

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
        "/healthz",
        "/route",
        "/v1/livez",
        "/v1/readyz",
        "/v1/route",
    }
    assert schema["paths"]["/healthz"]["get"]["deprecated"] is True

    route = schema["paths"]["/v1/route"]["get"]
    assert route["tags"] == ["routing"]
    assert route.get("deprecated") is not True
    assert schema["paths"]["/route"]["get"]["deprecated"] is True
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
