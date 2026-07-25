"""Public sea-route calculations between source-aware port records."""

from __future__ import annotations

import multiprocessing
import os
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from pathlib import Path
from typing import Any

import httpx

from sea_mile._routing_backend import (
    BackendRoute,
    RoutingConfig,
    SeaRouteBackend,
    _RoutingBackend,
)
from sea_mile.coordinates import LatLon
from sea_mile.exceptions import (
    PortCoordinateError,
    RoutingError,
    RoutingErrorReason,
    SeaMileError,
)
from sea_mile.geo import great_circle_nmi, validate_coordinate
from sea_mile.ports import Port, PortRegistry
from sea_mile.route_cache import RouteCache
from sea_mile.routing import RouteQualityFlag, assess_route_length

_DEFAULT_RETRY_ATTEMPTS = 4
_DEFAULT_BACKOFF_SECONDS = 0.25
_MAX_RETRY_ATTEMPTS = 8
_MAX_BACKOFF_SECONDS = 8.0


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


def _matrix_route(
    task: tuple[
        int,
        int,
        Port,
        Port,
        str,
        str,
        tuple[str, ...],
        str | None,
        _RoutingBackend,
        int,
        float,
    ],
) -> tuple[int, int, float]:
    """Calculate one matrix edge in an isolated worker process."""

    (
        row,
        column,
        origin,
        destination,
        algorithm,
        backend,
        restrictions,
        cache_path,
        routing_backend,
        retry_attempts,
        backoff_seconds,
    ) = task
    router = SeaRouter(
        algorithm=algorithm,
        backend=backend,
        restrictions=restrictions,
        cache_path=cache_path,
        retry_attempts=retry_attempts,
        backoff_seconds=backoff_seconds,
        _routing_backend=routing_backend,
    )
    return row, column, router.route(origin, destination).distance_nmi


def _is_transient_backend_error(error: BaseException) -> bool:
    """Recognize timeout, transport, and rate-limit failures through wrappers."""

    current: BaseException | None = error
    while current is not None:
        if isinstance(
            current,
            (
                TimeoutError,
                ConnectionError,
                httpx.TimeoutException,
                httpx.TransportError,
            ),
        ):
            return True
        response = getattr(current, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code == 429 or (
            isinstance(status_code, int) and 500 <= status_code < 600
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


class SeaRouter:
    """Calculate explicit nautical-mile routes between registry ports."""

    def __init__(
        self,
        *,
        algorithm: str = "astar",
        backend: str = "networkx",
        restrictions: tuple[str, ...] = ("northwest",),
        cache_path: str | Path | None = None,
        retry_attempts: int = _DEFAULT_RETRY_ATTEMPTS,
        backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS,
        _routing_backend: _RoutingBackend | None = None,
    ) -> None:
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be at least 1")
        if retry_attempts > _MAX_RETRY_ATTEMPTS:
            raise ValueError(f"retry_attempts cannot exceed {_MAX_RETRY_ATTEMPTS}")
        if not isfinite(backoff_seconds) or not 0 <= backoff_seconds <= (
            _MAX_BACKOFF_SECONDS
        ):
            raise ValueError(
                "backoff_seconds must be finite and between 0 and "
                f"{_MAX_BACKOFF_SECONDS:g}"
            )
        self.algorithm = algorithm
        self.backend = backend
        self.restrictions = restrictions
        self.retry_attempts = retry_attempts
        self.backoff_seconds = backoff_seconds
        self._backend: _RoutingBackend = (
            _routing_backend if _routing_backend is not None else SeaRouteBackend()
        )
        self._persistent_cache = RouteCache(cache_path) if cache_path else None
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
        great_circle = great_circle_nmi(
            *origin_coordinates.as_tuple(), *destination_coordinates.as_tuple()
        )
        config = RoutingConfig(
            algorithm=algorithm,
            graph_backend=backend,
            restrictions=restrictions,
        )
        try:
            result, cache_key, from_cache = self._backend_result(
                origin_coordinates, destination_coordinates, config
            )
        except (SeaMileError, ImportError):
            raise
        except Exception as error:
            raise RoutingError(
                f"routing backend {self._backend.name!r} failed: {error}",
                reason=RoutingErrorReason.BACKEND_CALL_FAILED,
            ) from error
        try:
            self._validate_geometry(result.geometry)
            assessment = assess_route_length(result.distance_nmi, great_circle)
            if not assessment.is_valid:
                raise RoutingError(
                    f"route failed the plausibility check: {assessment.flag}",
                    reason=RoutingErrorReason.IMPLAUSIBLE_ROUTE,
                )
        except Exception:
            if from_cache and cache_key is not None:
                assert self._persistent_cache is not None
                try:
                    self._persistent_cache.delete(cache_key)
                except Exception as error:
                    raise self._cache_access_error("delete", error) from error
            raise
        if cache_key is not None and not from_cache:
            assert self._persistent_cache is not None
            try:
                self._persistent_cache.put(cache_key, result)
            except Exception as error:
                raise self._cache_access_error("write", error) from error
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

    def _backend_result(
        self,
        origin: LatLon,
        destination: LatLon,
        config: RoutingConfig,
    ) -> tuple[BackendRoute, str | None, bool]:
        cache = self._persistent_cache
        if cache is None:
            return (
                self._call_backend_with_retry(origin, destination, config),
                None,
                False,
            )
        cache_key = cache.key(
            origin=origin,
            destination=destination,
            config=config,
            engine=self._backend.name,
            engine_version=self._backend.version,
        )
        try:
            cached = cache.get(cache_key)
        except Exception as error:
            raise self._cache_access_error("read", error) from error
        if cached is not None:
            return cached, cache_key, True
        return (
            self._call_backend_with_retry(origin, destination, config),
            cache_key,
            False,
        )

    def _validate_geometry(self, geometry: object) -> None:
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise self._malformed_geometry_error()
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            raise self._malformed_geometry_error()
        for point in coordinates:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise self._malformed_geometry_error()
            try:
                longitude = float(point[0])
                latitude = float(point[1])
            except (TypeError, ValueError) as error:
                raise self._malformed_geometry_error() from error
            if (
                not isfinite(latitude)
                or not isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
            ):
                raise self._malformed_geometry_error()

    def _malformed_geometry_error(self) -> RoutingError:
        return RoutingError(
            f"routing backend {self._backend.name!r} returned an unusable geometry",
            reason=RoutingErrorReason.MALFORMED_BACKEND_RESULT,
        )

    @staticmethod
    def _cache_access_error(action: str, error: Exception) -> RoutingError:
        return RoutingError(
            f"route cache {action} failed: {error}",
            reason=RoutingErrorReason.CACHE_ACCESS_FAILED,
        )

    def _call_backend_with_retry(
        self,
        origin: LatLon,
        destination: LatLon,
        config: RoutingConfig,
    ) -> BackendRoute:
        for attempt in range(self.retry_attempts):
            try:
                return self._backend.route(origin, destination, config)
            except Exception as error:
                final_attempt = attempt + 1 == self.retry_attempts
                if final_attempt or not _is_transient_backend_error(error):
                    raise
                time.sleep(
                    min(
                        self.backoff_seconds * (2**attempt),
                        _MAX_BACKOFF_SECONDS,
                    )
                )
        raise AssertionError("retry loop exhausted without returning or raising")

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

    def distance_matrix(
        self,
        ports: Sequence[Port],
        *,
        max_workers: int | None = None,
    ) -> list[list[float]]:
        """Return a process-parallel pairwise sea-distance matrix.

        ``max_workers=1`` is available for debuggers and constrained runtimes.
        Every worker opens its own WAL-enabled SQLite connection when a
        persistent cache is configured.
        """

        size = len(ports)
        matrix = [[0.0] * size for _ in range(size)]
        symmetric = bool(getattr(self._backend, "symmetric", False))
        if symmetric:
            pairs = [
                (row, column) for row in range(size) for column in range(row + 1, size)
            ]
        else:
            pairs = [
                (row, column)
                for row in range(size)
                for column in range(size)
                if row != column
            ]
        if not pairs:
            return matrix
        workers = max_workers
        if workers is None:
            workers = min(len(pairs), os.cpu_count() or 1)
        if workers < 1:
            raise ValueError("max_workers must be at least 1")
        results: Iterable[tuple[int, int, float]]
        if workers == 1:
            results = (
                (row, column, self.route(ports[row], ports[column]).distance_nmi)
                for row, column in pairs
            )
        else:
            cache_path = (
                str(self._persistent_cache.path)
                if self._persistent_cache is not None
                else None
            )
            tasks = (
                (
                    row,
                    column,
                    ports[row],
                    ports[column],
                    self.algorithm,
                    self.backend,
                    self.restrictions,
                    cache_path,
                    self._backend,
                    self.retry_attempts,
                    self.backoff_seconds,
                )
                for row, column in pairs
            )
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context("spawn"),
            ) as executor:
                results = list(executor.map(_matrix_route, tasks))
        for row, column, distance in results:
            matrix[row][column] = distance
            if symmetric:
                matrix[column][row] = distance
        return matrix

    @staticmethod
    def _coordinates(port: Port) -> LatLon:
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
        return LatLon(latitude=float(latitude), longitude=float(longitude))
