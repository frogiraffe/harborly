from __future__ import annotations

import warnings

import pytest

import sea_mile

_CORE = {
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
}


def test_all_is_exactly_the_core_surface() -> None:
    assert set(sea_mile.__all__) == _CORE


def test_core_names_resolve_without_a_deprecation_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        for name in sea_mile.__all__:
            assert getattr(sea_mile, name) is not None


def test_unknown_attribute_still_raises() -> None:
    with pytest.raises(AttributeError):
        _ = sea_mile.does_not_exist
