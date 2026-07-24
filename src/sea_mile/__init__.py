"""Public API for source-aware port search and approximate sea routing."""

from typing import TYPE_CHECKING

from .exceptions import (
    AmbiguousPortError,
    PortCoordinateError,
    PortNotFoundError,
    RegistryDataError,
    RoutingError,
    SeaMileError,
    SourceDataError,
)
from .matching import (
    BatchMatchResult,
    ConfidenceTier,
    MatchReason,
    MatchStatus,
)
from .ports import Port, PortGroup, PortRegistry
from .routing import RouteQualityFlag

if TYPE_CHECKING:
    from .router import SeaRoute, SeaRouter

_LAZY_EXPORTS = {
    "SeaRoute": "sea_mile.router",
    "SeaRouter": "sea_mile.router",
}


def __getattr__(name: str) -> object:
    from importlib import import_module

    module_name = _LAZY_EXPORTS.get(name)
    if module_name is not None:
        value = getattr(import_module(module_name), name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*__all__, *_LAZY_EXPORTS])


__all__ = [
    "AmbiguousPortError",
    "BatchMatchResult",
    "ConfidenceTier",
    "MatchReason",
    "MatchStatus",
    "Port",
    "PortCoordinateError",
    "PortGroup",
    "PortNotFoundError",
    "PortRegistry",
    "RegistryDataError",
    "RouteQualityFlag",
    "RoutingError",
    "SeaMileError",
    "SeaRoute",
    "SeaRouter",
    "SourceDataError",
]
