"""Public API for source-aware port search and approximate sea routing."""

from typing import TYPE_CHECKING

from .canonical import assign_canonical_ids
from .exceptions import (
    AmbiguousPortError,
    PortCoordinateError,
    PortNotFoundError,
    RegistryDataError,
    SeaMileError,
    SourceDataError,
)
from .matching import (
    BatchMatchResult,
    ConfidenceTier,
    ExactMatchDecision,
    MatchCandidate,
    MatchReason,
    MatchStatus,
    decide_exact_match,
)
from .normalization import canonical_key, normalize_display_text
from .ports import (
    NearbyPortGroup,
    NearbyPortResult,
    Port,
    PortGroup,
    PortRegistry,
    PortSearchResult,
)
from .quality import CoordinateCheck, great_circle_nmi, validate_coordinate
from .reference import parse_unlocode_coordinates, parse_wpi_dms
from .registry_build import build_reference_registry

if TYPE_CHECKING:
    from .router import SeaRoute, SeaRouter
    from .source_data import download_reference_data

# Lazily imported so search-only use does not load searoute, networkx, or httpx.
_LAZY_EXPORTS = {
    "SeaRoute": "sea_mile.router",
    "SeaRouter": "sea_mile.router",
    "download_reference_data": "sea_mile.source_data",
}


def __getattr__(name: str) -> object:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


__all__ = [
    "AmbiguousPortError",
    "BatchMatchResult",
    "ConfidenceTier",
    "CoordinateCheck",
    "ExactMatchDecision",
    "MatchCandidate",
    "MatchReason",
    "MatchStatus",
    "NearbyPortGroup",
    "NearbyPortResult",
    "Port",
    "PortCoordinateError",
    "PortGroup",
    "PortNotFoundError",
    "PortRegistry",
    "PortSearchResult",
    "RegistryDataError",
    "SeaMileError",
    "SeaRoute",
    "SeaRouter",
    "SourceDataError",
    "assign_canonical_ids",
    "build_reference_registry",
    "canonical_key",
    "decide_exact_match",
    "download_reference_data",
    "great_circle_nmi",
    "normalize_display_text",
    "parse_unlocode_coordinates",
    "parse_wpi_dms",
    "validate_coordinate",
]
