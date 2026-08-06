from __future__ import annotations

import warnings

import pytest

import harborly

_CORE = {
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
}


def test_all_is_exactly_the_core_surface() -> None:
    assert set(harborly.__all__) == _CORE


def test_core_names_resolve_without_a_deprecation_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        for name in harborly.__all__:
            assert getattr(harborly, name) is not None


def test_unknown_attribute_still_raises() -> None:
    with pytest.raises(AttributeError):
        _ = harborly.does_not_exist
