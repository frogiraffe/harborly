"""Public sea-route calculations between source-aware port records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sea_mile._routing_backend import (
    RoutingConfig,
    SeaRouteBackend,
    _RoutingBackend,
)
from sea_mile.exceptions import (
    PortCoordinateError,
    RoutingError,
    RoutingErrorReason,
    SeaMileError,
)
from sea_mile.geo import great_circle_nmi, validate_coordinate
from sea_mile.ports import Port, PortRegistry
from sea_mile.routing import RouteQualityFlag, assess_route_length


def _coordinate_port(label: str, latitude: float, longitude: float) -> Port:
    return Port(
        registry_id=f"COORD:{label}",
        provider="COORDINATE",
        provider_id=label,
        country_code="",
        name=label,
        latitude=latitude,
        longitude=longitude,
        unlocode=None,
        function_code=None,
        source_version="coordinate",
        coordinate_resolution=None,
    )


@dataclass(frozen=True, slots=True)
class SeaRoute:
    """A reproducible approximate route on searoute's maritime graph."""

    origin: Port
    destination: Port
    distance_nmi: float
    great_circle_nmi: float
    detour_ratio: float | None
    quality_flag: RouteQualityFlag
    geometry: dict[str, Any]
    engine: str
    engine_version: str
    algorithm: str
    backend: str
    restrictions: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        return {
            "origin": self.origin.to_dict(),
            "destination": self.destination.to_dict(),
            "distance_nmi": self.distance_nmi,
            "great_circle_nmi": self.great_circle_nmi,
            "detour_ratio": self.detour_ratio,
            "quality_flag": str(self.quality_flag),
            "engine": self.engine,
            "engine_version": self.engine_version,
            "algorithm": self.algorithm,
            "backend": self.backend,
            "restrictions": list(self.restrictions),
        }

    def to_geojson_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "properties": {
                **self.summary(),
                "routing_units": "nautical_miles",
                "navigation_warning": "Approximate graph route; not for navigation.",
            },
            "geometry": self.geometry,
        }


class SeaRouter:
    """Calculate explicit nautical-mile routes between registry ports."""

    def __init__(
        self,
        *,
        algorithm: str = "astar",
        backend: str = "networkx",
        restrictions: tuple[str, ...] = ("northwest",),
        _routing_backend: _RoutingBackend | None = None,
    ) -> None:
        self.algorithm = algorithm
        self.backend = backend
        self.restrictions = restrictions
        self._backend: _RoutingBackend = (
            _routing_backend if _routing_backend is not None else SeaRouteBackend()
        )
        # Memoized per instance, keyed on the ports and the config, so a
        # repeated pair in a batch skips recomputation.
        self._route_cached = lru_cache(maxsize=4096)(self._route_uncached)

    def route(self, origin: Port, destination: Port) -> SeaRoute:
        return self._route_cached(
            origin, destination, self.algorithm, self.backend, self.restrictions
        )

    def _route_uncached(
        self,
        origin: Port,
        destination: Port,
        algorithm: str,
        backend: str,
        restrictions: tuple[str, ...],
    ) -> SeaRoute:
        origin_coordinates = self._coordinates(origin)
        destination_coordinates = self._coordinates(destination)
        great_circle = great_circle_nmi(*origin_coordinates, *destination_coordinates)
        config = RoutingConfig(
            algorithm=algorithm,
            graph_backend=backend,
            restrictions=restrictions,
        )
        try:
            result = self._backend.route(
                origin_coordinates,
                destination_coordinates,
                config,
            )
        except (SeaMileError, ImportError):
            raise
        except Exception as error:
            raise RoutingError(
                f"routing backend {self._backend.name!r} failed: {error}",
                reason=RoutingErrorReason.BACKEND_CALL_FAILED,
            ) from error
        if not isinstance(result.geometry, dict):
            raise RoutingError(
                f"routing backend {self._backend.name!r} returned an unusable geometry",
                reason=RoutingErrorReason.MALFORMED_BACKEND_RESULT,
            )
        assessment = assess_route_length(result.distance_nmi, great_circle)
        if not assessment.is_valid:
            raise RoutingError(
                f"route failed the plausibility check: {assessment.flag}",
                reason=RoutingErrorReason.IMPLAUSIBLE_ROUTE,
            )
        return SeaRoute(
            origin=origin,
            destination=destination,
            distance_nmi=result.distance_nmi,
            great_circle_nmi=great_circle,
            detour_ratio=assessment.detour_ratio,
            quality_flag=assessment.flag,
            geometry=result.geometry,
            engine=self._backend.name,
            engine_version=self._backend.version,
            algorithm=algorithm,
            backend=backend,
            restrictions=restrictions,
        )

    def route_ids(
        self,
        registry: PortRegistry,
        origin_id: str,
        destination_id: str,
    ) -> SeaRoute:
        return self.route(registry.get(origin_id), registry.get(destination_id))

    def route_coordinates(
        self,
        origin_latitude: float,
        origin_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
    ) -> SeaRoute:
        """Route between two raw coordinates, without a registry lookup."""

        return self.route(
            _coordinate_port("origin", origin_latitude, origin_longitude),
            _coordinate_port(
                "destination", destination_latitude, destination_longitude
            ),
        )

    def route_many(self, pairs: Sequence[tuple[Port, Port]]) -> list[SeaRoute]:
        """Route every origin and destination pair."""

        return [self.route(origin, destination) for origin, destination in pairs]

    def distance_matrix(self, ports: Sequence[Port]) -> list[list[float]]:
        """Return the pairwise sea distance, in nautical miles, for the ports."""

        size = len(ports)
        matrix = [[0.0] * size for _ in range(size)]
        for row in range(size):
            for column in range(row + 1, size):
                distance = self.route(ports[row], ports[column]).distance_nmi
                matrix[row][column] = distance
                matrix[column][row] = distance
        return matrix

    @staticmethod
    def _coordinates(port: Port) -> tuple[float, float]:
        latitude = port.latitude
        longitude = port.longitude
        if latitude is None or longitude is None:
            raise PortCoordinateError(
                f"port {port.registry_id} has no conflict-free coordinate"
            )
        check = validate_coordinate(latitude, longitude)
        if not check.is_valid:
            raise PortCoordinateError(
                f"port {port.registry_id} has an invalid coordinate: {check.reason}"
            )
        return float(latitude), float(longitude)
