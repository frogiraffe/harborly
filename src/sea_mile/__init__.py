"""Public API for source-aware port search and approximate sea routing."""

import warnings
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

# Core, lazily imported so search-only use does not load searoute, networkx, or httpx.
_LAZY_EXPORTS = {
    "SeaRoute": "sea_mile.router",
    "SeaRouter": "sea_mile.router",
}

# Names that left the top-level namespace in 0.7. They still import from here for one
# release, with a warning, and stay available from the modules named below.
_DEPRECATED_EXPORTS = {
    "CoordinateCheck": "sea_mile.geo",
    "ExactMatchDecision": "sea_mile.matching",
    "MatchCandidate": "sea_mile.matching",
    "NearbyPortGroup": "sea_mile.ports",
    "NearbyPortResult": "sea_mile.ports",
    "PortSearchResult": "sea_mile.ports",
    "assign_canonical_ids": "sea_mile.canonical",
    "build_reference_registry": "sea_mile.build",
    "canonical_key": "sea_mile.text",
    "decide_exact_match": "sea_mile.matching",
    "download_reference_data": "sea_mile.build",
    "great_circle_nmi": "sea_mile.geo",
    "normalize_display_text": "sea_mile.text",
    "parse_unlocode_coordinates": "sea_mile.sources",
    "parse_wpi_dms": "sea_mile.sources",
    "validate_coordinate": "sea_mile.geo",
}


def __getattr__(name: str) -> object:
    from importlib import import_module

    module_name = _LAZY_EXPORTS.get(name)
    if module_name is not None:
        value = getattr(import_module(module_name), name)
        globals()[name] = value
        return value

    module_name = _DEPRECATED_EXPORTS.get(name)
    if module_name is not None:
        warnings.warn(
            f"sea_mile.{name} is deprecated at the top level. "
            f"Import it from {module_name} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(import_module(module_name), name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*__all__, *_LAZY_EXPORTS, *_DEPRECATED_EXPORTS])


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
