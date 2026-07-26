"""Optional FastAPI application for bundled port routing."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

import uvicorn
from fastapi import FastAPI, HTTPException

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

    application = FastAPI(title="sea-mile", version="1")

    @application.get("/route")
    def get_route(
        origin: str,
        destination: str,
        origin_country: str | None = None,
        destination_country: str | None = None,
    ) -> dict[str, Any]:
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
        return {
            "distance_nmi": result.distance_nmi,
            "geojson": result.to_geojson_feature(),
        }

    return application


app = create_app()


def run_server(*, host: str, port: int) -> None:
    """Run the optional HTTP server until it is stopped."""

    uvicorn.run(app, host=host, port=port)
