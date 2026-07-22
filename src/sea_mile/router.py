"""Public sea-route calculations between source-aware port records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sea_mile.exceptions import PortCoordinateError
from sea_mile.ports import Port, PortRegistry
from sea_mile.quality import great_circle_nmi, validate_coordinate
from sea_mile.routing import assess_route_length


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
    quality_flag: str
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
            "quality_flag": self.quality_flag,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "algorithm": self.algorithm,
            "backend": self.backend,
            "restrictions": self.restrictions,
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
    ) -> None:
        self.algorithm = algorithm
        self.backend = backend
        self.restrictions = restrictions
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
        try:
            import searoute
        except ImportError as error:
            raise ImportError(
                "sea routing needs the 'routing' extra "
                "(pip install 'sea-mile[routing]' or uv sync --extra routing)"
            ) from error
        self._require_coordinates(origin)
        self._require_coordinates(destination)
        assert origin.latitude is not None and origin.longitude is not None
        assert destination.latitude is not None and destination.longitude is not None
        great_circle = great_circle_nmi(
            origin.latitude,
            origin.longitude,
            destination.latitude,
            destination.longitude,
        )
        feature = searoute.searoute(
            [origin.longitude, origin.latitude],
            [destination.longitude, destination.latitude],
            units="naut",
            append_orig_dest=True,
            restrictions=list(restrictions),
            algorithm=algorithm,
            backend=backend,
        )
        distance = float(feature.properties["length"])
        assessment = assess_route_length(distance, great_circle)
        if not assessment.is_valid:
            raise PortCoordinateError(
                f"route failed plausibility check: {assessment.flag}"
            )
        return SeaRoute(
            origin=origin,
            destination=destination,
            distance_nmi=distance,
            great_circle_nmi=great_circle,
            detour_ratio=assessment.detour_ratio,
            quality_flag=assessment.flag,
            geometry=feature.geometry,
            engine="searoute",
            engine_version=searoute.__version__,
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
    def _require_coordinates(port: Port) -> None:
        if not port.has_coordinates:
            raise PortCoordinateError(
                f"port {port.registry_id} has no conflict-free coordinate"
            )
        check = validate_coordinate(port.latitude, port.longitude)
        if not check.is_valid:
            raise PortCoordinateError(
                f"port {port.registry_id} has an invalid coordinate: {check.reason}"
            )
