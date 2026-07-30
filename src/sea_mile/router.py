"""Public sea-route calculations between source-aware port records."""

from __future__ import annotations

import logging
import multiprocessing
import os
import secrets
import time
from collections import deque
from collections.abc import Iterable, Sequence
from concurrent.futures import Future, ProcessPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from pathlib import Path
from typing import Any

from sea_mile._circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerPolicy,
    _CircuitState,
)
from sea_mile._routing_backend import (
    BackendRoute,
    RoutingConfig,
    SeaRouteBackend,
    _RoutingBackend,
    classify_backend_error,
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
from sea_mile.routing import (
    CacheFailurePolicy,
    ReadinessCheck,
    RetryPolicy,
    RouteQualityFlag,
    RouteQualityPolicy,
    assess_route_length,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_MATRIX_WORKER_LIMIT = 4
_MATRIX_BATCH_SIZE = 32
_MATRIX_PENDING_BATCHES_PER_WORKER = 2


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


_worker_router: SeaRouter | None = None


def _worker_initializer(
    algorithm: str,
    backend: str,
    restrictions: tuple[str, ...],
    cache_path: str | None,
    retry_policy: RetryPolicy,
    quality_policy: RouteQualityPolicy | None,
    circuit_breaker_policy: CircuitBreakerPolicy | None,
    routing_backend: _RoutingBackend | None,
) -> None:
    """Pre-import dependencies and initialize a worker-local router instance.

    Called once per worker process before any tasks execute.
    """
    global _worker_router
    import sea_mile._routing_backend  # noqa: F401, PLC0415

    _worker_router = SeaRouter(
        algorithm=algorithm,
        backend=backend,
        restrictions=restrictions,
        cache_path=cache_path,
        retry_policy=retry_policy,
        quality_policy=quality_policy,
        circuit_breaker_policy=circuit_breaker_policy,
        _routing_backend=routing_backend,
    )


def _matrix_route(
    task: tuple[int, int, Port, Port],
) -> tuple[int, int, float]:
    """Calculate one matrix edge using the worker-local router instance."""

    row, column, origin, destination = task
    if _worker_router is None:
        raise RuntimeError("worker router instance was not initialized")
    return row, column, _worker_router.route(origin, destination).distance_nmi


def _matrix_route_batch(
    tasks: tuple[tuple[int, int, Port, Port], ...],
) -> list[tuple[int, int, float]]:
    """Calculate a bounded batch of matrix edges in one worker call."""

    return [_matrix_route(task) for task in tasks]


def _matrix_pairs(size: int, *, symmetric: bool) -> Iterable[tuple[int, int]]:
    """Yield matrix indices without retaining the quadratic pair collection."""

    if symmetric:
        return ((row, column) for row in range(size) for column in range(row + 1, size))
    return (
        (row, column) for row in range(size) for column in range(size) if row != column
    )


def _matrix_task_batches(
    ports: Sequence[Port],
    pairs: Iterable[tuple[int, int]],
    *,
    batch_size: int,
) -> Iterable[tuple[tuple[int, int, Port, Port], ...]]:
    """Yield fixed-size task batches while keeping only one batch in memory."""

    batch: list[tuple[int, int, Port, Port]] = []
    for row, column in pairs:
        batch.append((row, column, ports[row], ports[column]))
        if len(batch) == batch_size:
            yield tuple(batch)
            batch.clear()
    if batch:
        yield tuple(batch)


def _is_transient_backend_error(error: BaseException) -> bool:
    """Recognize timeout, transport, and rate-limit failures through wrappers."""

    if isinstance(error, Exception):
        return classify_backend_error(error).transient
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
        retry_policy: RetryPolicy | None = None,
        quality_policy: RouteQualityPolicy | None = None,
        circuit_breaker_policy: CircuitBreakerPolicy | None = None,
        cache_failure_policy: CacheFailurePolicy = CacheFailurePolicy.STRICT,
        _routing_backend: _RoutingBackend | None = None,
    ) -> None:
        self._retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self.algorithm = algorithm
        self.backend = backend
        self.restrictions = restrictions
        self._circuit_breaker = (
            CircuitBreaker(circuit_breaker_policy)
            if circuit_breaker_policy is not None
            else None
        )
        self._backend: _RoutingBackend = (
            _routing_backend if _routing_backend is not None else SeaRouteBackend()
        )
        self._quality_policy = quality_policy
        self._persistent_cache = RouteCache(cache_path) if cache_path else None
        self._cache_failure_policy = cache_failure_policy
        # Memoized per instance, keyed on the ports and the config, so a
        # repeated pair in a batch skips recomputation.
        self._route_cached = lru_cache(maxsize=4096)(self._route_uncached)

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    def route(self, origin: Port, destination: Port) -> SeaRoute:
        return self._route_cached(
            origin, destination, self.algorithm, self.backend, self.restrictions
        )

    def check_ready(self) -> tuple[ReadinessCheck, ...]:
        """Probe what a route call needs, without computing one.

        Routing itself is far too expensive to run on every readiness poll, so
        this touches the dependencies that actually go missing: the backend
        import and the persistent cache.
        """

        return (self._backend_readiness(), self._cache_readiness())

    def _backend_readiness(self) -> ReadinessCheck:
        try:
            # The bundled backend imports searoute lazily, so reading the
            # version is what surfaces a missing 'routing' extra.
            version = self._backend.version
        except Exception as error:  # noqa: BLE001 - any failure means unusable
            return ReadinessCheck(
                "routing_backend", False, f"{self._backend.name} is unusable: {error}"
            )
        return ReadinessCheck(
            "routing_backend", True, f"{self._backend.name} {version}"
        )

    def _cache_readiness(self) -> ReadinessCheck:
        cache = self._persistent_cache
        if cache is None:
            return ReadinessCheck("route_cache", True, "not configured")
        try:
            cache.get("readiness-probe")
        except Exception as error:  # noqa: BLE001 - any failure means unusable
            # Readiness has to agree with what a request would actually do.
            # Under BEST_EFFORT this cache costs speed, not correctness, so
            # reporting not-ready would retire a server that still works.
            degraded = self._cache_failure_policy is CacheFailurePolicy.BEST_EFFORT
            reaction = "requests continue without it" if degraded else "requests fail"
            return ReadinessCheck(
                "route_cache", degraded, f"unusable ({error}); {reaction}"
            )
        return ReadinessCheck("route_cache", True, "readable")

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
            assessment = assess_route_length(
                result.distance_nmi,
                great_circle,
                policy=self._quality_policy,
            )
            if not assessment.is_valid:
                raise RoutingError(
                    f"route failed the plausibility check: {assessment.flag}",
                    reason=RoutingErrorReason.IMPLAUSIBLE_ROUTE,
                )
        except Exception:
            if from_cache and cache_key is not None:
                if self._persistent_cache is None:
                    raise RuntimeError("persistent cache not initialized") from None
                try:
                    self._persistent_cache.delete(cache_key)
                except Exception as error:
                    # Under BEST_EFFORT this returns, and the bare `raise`
                    # below re-raises the routing failure the caller asked
                    # about instead of the eviction that followed it.
                    self._handle_cache_failure("delete", error)
            raise
        if cache_key is not None and not from_cache:
            if self._persistent_cache is None:
                raise RuntimeError("persistent cache not initialized")
            try:
                self._persistent_cache.put(cache_key, result)
            except Exception as error:
                self._handle_cache_failure("write", error)
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
            graph_version=str(
                getattr(self._backend, "graph_version", self._backend.version)
            ),
        )
        try:
            cached = cache.get(cache_key)
        except Exception as error:
            self._handle_cache_failure("read", error)
            cached = None
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

    def _handle_cache_failure(self, action: str, error: Exception) -> None:
        """Apply the cache failure policy. Returns only if the caller may go on."""

        if self._cache_failure_policy is CacheFailurePolicy.STRICT:
            raise self._cache_access_error(action, error) from error
        _LOGGER.warning(
            "route cache %s failed, continuing without the cache: %s", action, error
        )

    def _call_backend_with_retry(
        self,
        origin: LatLon,
        destination: LatLon,
        config: RoutingConfig,
    ) -> BackendRoute:
        policy = self._retry_policy
        deadline = (
            None
            if policy.overall_timeout_seconds is None
            else time.monotonic() + policy.overall_timeout_seconds
        )
        for attempt in range(policy.attempts):
            if self._circuit_breaker is not None:
                self._circuit_breaker.check()
            try:
                res = self._backend.route(origin, destination, config)
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_success()
                return res
            except Exception as error:
                classified = classify_backend_error(error)
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure(classified.transient)
                    if self._circuit_breaker.state == _CircuitState.OPEN:
                        raise RoutingError(
                            f"circuit breaker open during retry loop: {error}",
                            reason=RoutingErrorReason.CIRCUIT_BREAKER_OPEN,
                        ) from error
                final_attempt = attempt + 1 == policy.attempts
                if final_attempt or not classified.transient:
                    raise
                base_wait = min(
                    policy.base_backoff_seconds * (2**attempt),
                    policy.max_backoff_seconds,
                )
                jittered = base_wait * (
                    (1.0 - policy.jitter_ratio)
                    + 2.0 * policy.jitter_ratio * secrets.SystemRandom().random()
                )
                if deadline is not None and jittered >= deadline - time.monotonic():
                    # Sleeping anyway would only hold the caller's worker for a
                    # retry we already know cannot start inside the budget.
                    raise RoutingError(
                        f"routing gave up after {attempt + 1} attempt(s): the "
                        f"{policy.overall_timeout_seconds}s budget cannot hold "
                        f"another {jittered:.2f}s backoff; last error: {error}",
                        reason=RoutingErrorReason.TIMEOUT_BUDGET_EXHAUSTED,
                    ) from error
                time.sleep(jittered)
        raise RuntimeError("retry loop exhausted without returning or raising")

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

        ``max_workers=1`` is available for debuggers, constrained runtimes, and
        custom routing backends that cannot be serialized across processes.
        Raises :exc:`ValueError` if ``max_workers > 1`` and the configured routing
        backend cannot be serialized. Every worker opens its own WAL-enabled SQLite
        connection when a persistent cache is configured. The returned square matrix
        necessarily uses O(n²) memory; use :meth:`iter_distance_edges` when a dense
        matrix is not required.
        """

        size = len(ports)
        matrix = [[0.0] * size for _ in range(size)]
        symmetric = bool(getattr(self._backend, "symmetric", False))
        for row, column, distance in self.iter_distance_edges(
            ports, max_workers=max_workers
        ):
            matrix[row][column] = distance
            if symmetric:
                matrix[column][row] = distance
        return matrix

    def iter_distance_edges(
        self,
        ports: Sequence[Port],
        *,
        max_workers: int | None = None,
    ) -> Iterable[tuple[int, int, float]]:
        """Yield pairwise route edges with bounded process-pool backpressure.

        Symmetric backends yield each unordered pair once. Directional backends
        yield both directions. At most two fixed-size batches per worker are
        submitted at a time, and results are yielded in deterministic pair order.
        """

        if max_workers is not None and max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        size = len(ports)
        symmetric = bool(getattr(self._backend, "symmetric", False))
        edge_count = size * (size - 1) // 2 if symmetric else size * (size - 1)
        if edge_count == 0:
            return
        workers = max_workers
        if workers is None:
            workers = min(
                edge_count,
                os.cpu_count() or 1,
                _DEFAULT_MATRIX_WORKER_LIMIT,
            )
        pairs = _matrix_pairs(size, symmetric=symmetric)
        if workers == 1:
            for row, column in pairs:
                yield (
                    row,
                    column,
                    self.route(ports[row], ports[column]).distance_nmi,
                )
            return

        try:
            multiprocessing.reduction.ForkingPickler.dumps(self._backend)
        except Exception:
            raise ValueError(
                "routing backend must be serializable when max_workers is "
                "greater than one"
            ) from None
        cache_path = (
            str(self._persistent_cache.path)
            if self._persistent_cache is not None
            else None
        )
        initargs = (
            self.algorithm,
            self.backend,
            self.restrictions,
            cache_path,
            self.retry_policy,
            self._quality_policy,
            self._circuit_breaker.policy if self._circuit_breaker else None,
            self._backend,
        )
        batches = iter(
            _matrix_task_batches(ports, pairs, batch_size=_MATRIX_BATCH_SIZE)
        )
        max_pending = workers * _MATRIX_PENDING_BATCHES_PER_WORKER
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_worker_initializer,
            initargs=initargs,
        ) as executor:
            pending: deque[Future[list[tuple[int, int, float]]]] = deque()
            for _ in range(max_pending):
                try:
                    pending.append(executor.submit(_matrix_route_batch, next(batches)))
                except StopIteration:
                    break
            while pending:
                yield from pending.popleft().result()
                with suppress(StopIteration):
                    pending.append(executor.submit(_matrix_route_batch, next(batches)))

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
