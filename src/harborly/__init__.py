"""Public API for source-aware port search and approximate sea routing."""

from typing import TYPE_CHECKING

from ._routing_backend import BackendError, BackendErrorKind
from .canonical import CanonicalEvidence
from .exceptions import (
    AmbiguousPortError,
    HarborlyError,
    PortCoordinateError,
    PortNotFoundError,
    RegistryDataError,
    RoutingError,
    SourceDataError,
)
from .matching import (
    BatchMatchResult,
    ConfidenceTier,
    MatchPolicy,
    MatchReason,
    MatchStatus,
)
from .ports import Port, PortGroup, PortRegistry
from .routing import (
    CacheFailurePolicy,
    PassageRestriction,
    RetryPolicy,
    RouteQualityFlag,
    RouteQualityPolicy,
)

if TYPE_CHECKING:
    from .router import AsyncSeaRouter, SeaRoute, SeaRouter, SequenceSeaRoute

_LAZY_EXPORTS = {
    "AsyncSeaRouter": "harborly.router",
    "SeaRoute": "harborly.router",
    "SeaRouter": "harborly.router",
    "SequenceSeaRoute": "harborly.router",
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
    return sorted(set(__all__) | set(_LAZY_EXPORTS))


__all__ = [
    "AmbiguousPortError",
    "AsyncSeaRouter",
    "BackendError",
    "BackendErrorKind",
    "BatchMatchResult",
    "CacheFailurePolicy",
    "CanonicalEvidence",
    "ConfidenceTier",
    "MatchPolicy",
    "MatchReason",
    "MatchStatus",
    "PassageRestriction",
    "Port",
    "PortCoordinateError",
    "PortGroup",
    "PortNotFoundError",
    "PortRegistry",
    "RegistryDataError",
    "RetryPolicy",
    "RouteQualityFlag",
    "RouteQualityPolicy",
    "RoutingError",
    "HarborlyError",
    "SeaRoute",
    "SeaRouter",
    "SequenceSeaRoute",
    "SourceDataError",
]
