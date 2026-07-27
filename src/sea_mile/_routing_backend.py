"""Internal routing backend protocol and searoute adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from sea_mile.coordinates import LatLon
from sea_mile.exceptions import RoutingError, RoutingErrorReason


class BackendErrorKind(StrEnum):
    NETWORK = "network"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


class BackendError(Exception):
    """Typed classification wrapper for routing backend errors."""

    def __init__(
        self,
        message: str,
        *,
        kind: BackendErrorKind,
        transient: bool,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.transient = transient


def classify_backend_error(error: Exception) -> BackendError:
    """Classify an arbitrary backend exception into a typed BackendError."""
    if isinstance(error, BackendError):
        return error

    import httpx

    # First pass: check if any exception in cause chain is transient
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, (TimeoutError, httpx.TimeoutException)):
            return BackendError(
                str(error), kind=BackendErrorKind.TIMEOUT, transient=True
            )
        if isinstance(current, (ConnectionError, httpx.TransportError)):
            return BackendError(
                str(error), kind=BackendErrorKind.NETWORK, transient=True
            )
        response = getattr(current, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code == 429:
            return BackendError(
                str(error), kind=BackendErrorKind.RATE_LIMIT, transient=True
            )
        if isinstance(status_code, int) and 500 <= status_code < 600:
            return BackendError(
                str(error), kind=BackendErrorKind.SERVER, transient=True
            )
        current = current.__cause__ or current.__context__

    # Second pass: check for invalid response formatting errors
    current = error
    while current is not None:
        if isinstance(current, (AttributeError, KeyError, TypeError, ValueError)):
            return BackendError(
                str(error), kind=BackendErrorKind.INVALID_RESPONSE, transient=False
            )
        current = current.__cause__ or current.__context__

    return BackendError(str(error), kind=BackendErrorKind.UNKNOWN, transient=False)


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    """The effective routing settings that can influence a route result."""

    algorithm: str
    graph_backend: str
    restrictions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "backend": self.graph_backend,
            "restrictions": list(self.restrictions),
        }


@dataclass(frozen=True, slots=True)
class BackendRoute:
    """A raw backend result, before sea-mile applies its quality assessment."""

    distance_nmi: float
    geometry: dict[str, Any]


class _RoutingBackend(Protocol):
    """The narrow routing interface SeaRouter needs. Internal, not public."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def symmetric(self) -> bool: ...

    def route(
        self,
        origin: LatLon,
        destination: LatLon,
        config: RoutingConfig,
    ) -> BackendRoute: ...


class SeaRouteBackend:
    """Default backend that routes with the searoute package."""

    @property
    def name(self) -> str:
        return "searoute"

    @property
    def version(self) -> str:
        return str(self._module().__version__)

    @property
    def symmetric(self) -> bool:
        """The bundled searoute graph produces direction-independent distances."""

        return True

    def route(
        self,
        origin: LatLon,
        destination: LatLon,
        config: RoutingConfig,
    ) -> BackendRoute:
        searoute = self._module()
        origin_xy = origin.to_lon_lat()
        destination_xy = destination.to_lon_lat()
        try:
            feature = searoute.searoute(
                origin_xy.as_list(),
                destination_xy.as_list(),
                units="naut",
                append_orig_dest=True,
                restrictions=list(config.restrictions),
                algorithm=config.algorithm,
                backend=config.graph_backend,
            )
        except Exception as error:
            raise RoutingError(
                f"the searoute backend failed to route: {error}",
                reason=RoutingErrorReason.BACKEND_CALL_FAILED,
            ) from error
        try:
            distance = float(feature.properties["length"])
            geometry = feature.geometry
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise RoutingError(
                f"the searoute backend returned an unusable route: {error}",
                reason=RoutingErrorReason.MALFORMED_BACKEND_RESULT,
            ) from error
        return BackendRoute(distance_nmi=distance, geometry=geometry)

    @staticmethod
    def _module() -> Any:
        try:
            import searoute
        except ImportError as error:
            raise ImportError(
                "sea routing needs the 'routing' extra "
                "(pip install 'sea-mile[routing]' or uv sync --extra routing)"
            ) from error
        return searoute
