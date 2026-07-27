"""Optional FastAPI application for bundled port routing."""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any, Literal, Protocol

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from sea_mile.exceptions import (
    AmbiguousPortError,
    PortCoordinateError,
    PortNotFoundError,
    RoutingError,
)
from sea_mile.ports import Port, PortRegistry
from sea_mile.router import SeaRoute, SeaRouter


class _RouteService(Protocol):
    def route(self, origin: Port, destination: Port) -> SeaRoute: ...


class HealthResponse(BaseModel):
    """Liveness response for local process supervision."""

    service: Literal["sea-mile"]
    status: Literal["ok"]
    version: str


class PortResponse(BaseModel):
    """Provider-specific port record returned as route provenance."""

    registry_id: str
    provider: str
    provider_id: str
    country_code: str
    name: str
    latitude: float | None
    longitude: float | None
    unlocode: str | None
    function_code: str | None
    source_version: str
    coordinate_resolution: str | None
    variant_count: int
    coordinate_conflict: bool
    canonical_id: str


class RoutePropertiesResponse(BaseModel):
    """Metadata attached to the GeoJSON route feature."""

    origin: PortResponse
    destination: PortResponse
    distance_nmi: float
    great_circle_nmi: float
    detour_ratio: float | None
    quality_flag: str
    engine: str
    engine_version: str
    algorithm: str
    backend: str
    restrictions: list[str]
    routing_units: Literal["nautical_miles"]
    navigation_warning: str


class LineStringResponse(BaseModel):
    """GeoJSON LineString in longitude-latitude order."""

    type: Literal["LineString"]
    coordinates: list[tuple[float, float]]


class RouteFeatureResponse(BaseModel):
    """GeoJSON feature containing the route and its provenance."""

    type: Literal["Feature"]
    properties: RoutePropertiesResponse
    geometry: LineStringResponse


class RouteResponse(BaseModel):
    """Successful route response."""

    distance_nmi: float = Field(
        description="Approximate route length in nautical miles"
    )
    geojson: RouteFeatureResponse


class ErrorResponse(BaseModel):
    """API error with a human-readable explanation."""

    detail: str


class UnprocessableResponse(BaseModel):
    """Application or FastAPI query-validation error."""

    detail: str | list[dict[str, Any]]


def _package_version() -> str:
    try:
        return version("sea-mile")
    except PackageNotFoundError:
        return "0.0.0"


@lru_cache(maxsize=1)
def _bundled_registry() -> PortRegistry:
    return PortRegistry.bundled()


@lru_cache(maxsize=1)
def _sea_router() -> SeaRouter:
    return SeaRouter()


def create_app(
    *,
    registry: PortRegistry | None = None,
    router: _RouteService | None = None,
) -> FastAPI:
    """Create the HTTP application, with injectable services for isolated tests."""

    application = FastAPI(
        title="sea-mile API",
        version=_package_version(),
        description=(
            "Resolve bundled port identities and calculate approximate analytical "
            "sea routes. Routes are not suitable for navigation."
        ),
        openapi_tags=[
            {"name": "operations", "description": "Service liveness."},
            {"name": "routing", "description": "Approximate analytical sea routes."},
        ],
    )

    @application.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    @application.get(
        "/healthz",
        response_model=HealthResponse,
        tags=["operations"],
        summary="Check service liveness",
    )
    def healthz() -> HealthResponse:
        return HealthResponse(
            service="sea-mile", status="ok", version=_package_version()
        )

    @application.get(
        "/route",
        response_model=RouteResponse,
        tags=["routing"],
        summary="Calculate an approximate sea route",
        responses={
            404: {"model": ErrorResponse, "description": "Port not found"},
            409: {"model": ErrorResponse, "description": "Port identity is ambiguous"},
            422: {
                "model": UnprocessableResponse,
                "description": "Invalid query parameters or port coordinates",
            },
            502: {"model": ErrorResponse, "description": "Routing backend failed"},
            503: {
                "model": ErrorResponse,
                "description": "Routing extra is unavailable",
            },
        },
    )
    def get_route(
        origin: Annotated[
            str,
            Query(
                description="Origin registry ID, UN/LOCODE, or exact port alias",
                examples=["TRMER"],
                min_length=1,
            ),
        ],
        destination: Annotated[
            str,
            Query(
                description="Destination registry ID, UN/LOCODE, or exact port alias",
                examples=["GRPIR"],
                min_length=1,
            ),
        ],
        origin_country: Annotated[
            str | None,
            Query(
                description="Optional ISO 3166-1 alpha-2 country filter for the origin",
                examples=["TR"],
                min_length=2,
                max_length=2,
            ),
        ] = None,
        destination_country: Annotated[
            str | None,
            Query(
                description=(
                    "Optional ISO 3166-1 alpha-2 country filter for the destination"
                ),
                examples=["GR"],
                min_length=2,
                max_length=2,
            ),
        ] = None,
    ) -> RouteResponse:
        active_registry = registry if registry is not None else _bundled_registry()
        active_router = router if router is not None else _sea_router()
        try:
            origin_port = active_registry.resolve(origin, country_code=origin_country)
            destination_port = active_registry.resolve(
                destination, country_code=destination_country
            )
            result = active_router.route(origin_port, destination_port)
        except PortNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except AmbiguousPortError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (PortCoordinateError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ImportError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except RoutingError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return RouteResponse(
            distance_nmi=result.distance_nmi,
            geojson=RouteFeatureResponse(**result.to_geojson_feature()),
        )

    return application


app = create_app()


def run_server(*, host: str, port: int) -> None:
    """Run the optional HTTP server until it is stopped."""

    uvicorn.run(app, host=host, port=port)
