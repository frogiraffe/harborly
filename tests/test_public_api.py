from __future__ import annotations

import warnings

import pytest

import sea_mile

_CORE = {
    "AmbiguousPortError",
    "BackendError",
    "BackendErrorKind",
    "BatchMatchResult",
    "CacheFailurePolicy",
    "CanonicalEvidence",
    "ConfidenceTier",
    "MatchPolicy",
    "MatchReason",
    "MatchStatus",
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


# --- deprecated keyword ladders ----------------------------------------------
#
# Each setting below has two spellings: a policy object and a loose keyword
# ladder that predated it. The ladders are deprecated and scheduled for
# removal in the next major version; see docs/API_COMPATIBILITY.md.


def test_searouter_retry_keywords_warn_but_still_work() -> None:
    from sea_mile import RetryPolicy, SeaRouter

    with pytest.warns(DeprecationWarning):
        router = SeaRouter(retry_attempts=3)
    assert router.retry_policy.attempts == 3

    with pytest.warns(DeprecationWarning):
        router = SeaRouter(backoff_seconds=0.5)
    assert router.retry_policy.base_backoff_seconds == 0.5

    assert SeaRouter(retry_policy=RetryPolicy(attempts=3)).retry_policy.attempts == 3


def test_searouter_retry_attribute_mirrors_warn_but_still_work() -> None:
    from sea_mile import SeaRouter

    router = SeaRouter(retry_policy=None)

    with pytest.warns(DeprecationWarning):
        assert router.retry_attempts == router.retry_policy.attempts

    with pytest.warns(DeprecationWarning):
        assert router.backoff_seconds == router.retry_policy.base_backoff_seconds


def test_assess_route_length_threshold_keywords_warn_but_still_work() -> None:
    from sea_mile.routing import (
        RouteQualityFlag,
        RouteQualityPolicy,
        assess_route_length,
    )

    with pytest.warns(DeprecationWarning):
        assessment = assess_route_length(400, 300, high_detour_ratio=1.2)
    assert assessment.flag is RouteQualityFlag.HIGH_DETOUR_RATIO

    with pytest.warns(DeprecationWarning):
        assess_route_length(400, 300, lower_bound_tolerance_nmi=1.0)

    assessment = assess_route_length(
        400, 300, policy=RouteQualityPolicy(high_detour_ratio=1.2)
    )
    assert assessment.flag is RouteQualityFlag.HIGH_DETOUR_RATIO
