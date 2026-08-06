"""Optional FastAPI application for bundled port routing."""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any, Literal, Protocol

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from sea_mile.exceptions import (
    AmbiguousPortError,
    PortCoordinateError,
    PortNotFoundError,
    RoutingError,
    RoutingErrorReason,
    SeaMileError,
)
from sea_mile.ports import Port, PortRegistry
from sea_mile.router import SeaRoute, SeaRouter
from sea_mile.routing import ReadinessCheck


class _RouteService(Protocol):
    def route(self, origin: Port, destination: Port) -> SeaRoute: ...


class HealthResponse(BaseModel):
    """Liveness response for local process supervision."""

    service: Literal["sea-mile"]
    status: Literal["ok"]
    version: str


class ReadinessCheckResponse(BaseModel):
    """One dependency probe reported by the readiness endpoint."""

    name: str
    passed: bool
    detail: str


class ReadinessResponse(BaseModel):
    """Whether this process can currently serve a route request."""

    service: Literal["sea-mile"]
    status: Literal["ready", "not_ready"]
    version: str
    checks: list[ReadinessCheckResponse]


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


ERROR_SCHEMA_VERSION: Literal["1"] = "1"
_RETRY_AFTER_SECONDS = "5"

# Failure modes worth another attempt. Everything else names a condition that
# will hold again for an identical request, so a client retrying it only adds
# load.
_RETRYABLE_ROUTING_REASONS = frozenset(
    {
        RoutingErrorReason.BACKEND_CALL_FAILED,
        RoutingErrorReason.CIRCUIT_BREAKER_OPEN,
        RoutingErrorReason.TIMEOUT_BUDGET_EXHAUSTED,
    }
)

# Reasons that describe this service declining to serve rather than an upstream
# answering badly, so they report 503 instead of 502.
_UNAVAILABLE_ROUTING_REASONS = frozenset(
    {
        RoutingErrorReason.CIRCUIT_BREAKER_OPEN,
        RoutingErrorReason.TIMEOUT_BUDGET_EXHAUSTED,
    }
)


class ErrorBody(BaseModel):
    """The machine-readable half of an error response."""

    code: str = Field(description="Stable token identifying the failure")
    message: str = Field(description="Human-readable explanation; may change")
    retryable: bool = Field(
        description="Whether an identical request could succeed later"
    )
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """API error carrying a code a client can branch on."""

    schema_version: Literal["1"] = ERROR_SCHEMA_VERSION
    error: ErrorBody


class UnprocessableResponse(BaseModel):
    """Application or FastAPI query-validation error."""

    schema_version: Literal["1"] = ERROR_SCHEMA_VERSION
    error: ErrorBody


_ROUTE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Port not found"},
    409: {"model": ErrorResponse, "description": "Port identity is ambiguous"},
    422: {
        "model": UnprocessableResponse,
        "description": "Invalid query parameters or port coordinates",
    },
    500: {"model": ErrorResponse, "description": "Unexpected sea-mile failure"},
    502: {"model": ErrorResponse, "description": "Routing backend failed"},
    503: {
        "model": ErrorResponse,
        "description": "Routing is unavailable or the circuit breaker is open",
    },
}


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            details=details or {},
        )
    )
    headers = {"Retry-After": _RETRY_AFTER_SECONDS} if retryable else None
    return JSONResponse(
        status_code=status_code, content=body.model_dump(), headers=headers
    )


def _install_error_handlers(application: FastAPI) -> None:
    """Translate domain failures into the error contract in one place.

    Each exception already knows its own `code`, so the endpoints do not repeat
    a try/except ladder and a new endpoint inherits the contract.
    """

    @application.exception_handler(PortNotFoundError)
    async def _port_not_found(_: Request, error: PortNotFoundError) -> JSONResponse:
        return _error_response(404, error.code, str(error))

    @application.exception_handler(AmbiguousPortError)
    async def _ambiguous_port(_: Request, error: AmbiguousPortError) -> JSONResponse:
        return _error_response(409, error.code, str(error))

    @application.exception_handler(PortCoordinateError)
    async def _bad_coordinate(_: Request, error: PortCoordinateError) -> JSONResponse:
        return _error_response(422, error.code, str(error))

    @application.exception_handler(RoutingError)
    async def _routing_failed(_: Request, error: RoutingError) -> JSONResponse:
        retryable = error.reason in _RETRYABLE_ROUTING_REASONS
        status = 503 if error.reason in _UNAVAILABLE_ROUTING_REASONS else 502
        return _error_response(
            status,
            error.code,
            str(error),
            retryable=retryable,
            details={"reason": str(error.reason)},
        )

    @application.exception_handler(ImportError)
    async def _routing_unavailable(_: Request, error: ImportError) -> JSONResponse:
        return _error_response(503, "routing_unavailable", str(error))

    @application.exception_handler(SeaMileError)
    async def _other_domain_error(_: Request, error: SeaMileError) -> JSONResponse:
        return _error_response(500, error.code, str(error))

    @application.exception_handler(RequestValidationError)
    async def _invalid_request(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            422,
            "invalid_request",
            "the request parameters are not valid",
            details={"errors": jsonable_encoder(error.errors())},
        )


def _readiness_checks(
    registry: PortRegistry | None, router: _RouteService | None
) -> list[ReadinessCheck]:
    """Probe exactly what this application would use to answer a route request."""

    checks: list[ReadinessCheck] = []
    try:
        active_registry = registry if registry is not None else _bundled_registry()
    except Exception as error:  # noqa: BLE001 - any failure means unusable
        checks.append(ReadinessCheck("port_registry", False, str(error)))
    else:
        checks.append(
            ReadinessCheck("port_registry", True, f"{len(active_registry)} records")
        )

    try:
        active_router = router if router is not None else _sea_router()
    except Exception as error:  # noqa: BLE001 - any failure means unusable
        checks.append(ReadinessCheck("routing_backend", False, str(error)))
        return checks

    probe = getattr(active_router, "check_ready", None)
    if probe is None:
        # An injected service that does not offer a probe. Claiming it is
        # healthy would be a guess, so say what was and was not established.
        checks.append(
            ReadinessCheck("routing_backend", True, "injected service; not probed")
        )
        return checks
    checks.extend(probe())
    return checks


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

    _install_error_handlers(application)

    @application.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    def livez() -> HealthResponse:
        """Report that the process is up, saying nothing about its dependencies."""

        return HealthResponse(
            service="sea-mile", status="ok", version=_package_version()
        )

    application.get(
        "/v1/livez",
        response_model=HealthResponse,
        tags=["operations"],
        summary="Check service liveness",
    )(livez)

    @application.get(
        "/v1/readyz",
        response_model=ReadinessResponse,
        tags=["operations"],
        summary="Check whether dependencies can serve a request",
        responses={
            503: {
                "model": ReadinessResponse,
                "description": "At least one dependency is unusable",
            }
        },
    )
    def readyz() -> JSONResponse:
        checks = _readiness_checks(registry, router)
        ready = all(check.passed for check in checks)
        body = ReadinessResponse(
            service="sea-mile",
            status="ready" if ready else "not_ready",
            version=_package_version(),
            checks=[
                ReadinessCheckResponse(
                    name=check.name, passed=check.passed, detail=check.detail
                )
                for check in checks
            ],
        )
        return JSONResponse(
            status_code=200 if ready else 503, content=body.model_dump()
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
        origin_port = active_registry.resolve(origin, country_code=origin_country)
        destination_port = active_registry.resolve(
            destination, country_code=destination_country
        )
        result = active_router.route(origin_port, destination_port)
        return RouteResponse(
            distance_nmi=result.distance_nmi,
            geojson=RouteFeatureResponse(**result.to_geojson_feature()),
        )

    # The unversioned path stays as a deprecated alias so existing callers keep
    # working; it is removed in 2.0.
    application.get(
        "/v1/route",
        response_model=RouteResponse,
        tags=["routing"],
        summary="Calculate an approximate sea route",
        responses=_ROUTE_ERROR_RESPONSES,
    )(get_route)

    return application


app = create_app()


def run_server(*, host: str, port: int) -> None:
    """Run the optional HTTP server until it is stopped."""

    uvicorn.run(app, host=host, port=port)
