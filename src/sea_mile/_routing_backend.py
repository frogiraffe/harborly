"""Internal routing backend boundary that isolates the searoute dependency.

Nothing here is part of the public API. SeaRouter depends on the narrow
`_RoutingBackend` interface so the searoute integration stays in one place and a
test can supply a fake backend. Do not export these names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sea_mile.exceptions import RoutingError, RoutingErrorReason


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

    def route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
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

    def route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        config: RoutingConfig,
    ) -> BackendRoute:
        searoute = self._module()
        try:
            feature = searoute.searoute(
                [origin[1], origin[0]],
                [destination[1], destination[0]],
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
