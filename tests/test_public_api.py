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


# --- 2.0 removals -----------------------------------------------------------
#
# Every setting below had two spellings: a policy object and a loose keyword
# ladder that predated it. Two ways to say the same thing means two things to
# document, two to validate, and a silent question about which wins. 2.0 keeps
# the policy objects and drops the ladders, with no transition shim.


def test_searouter_no_longer_takes_loose_retry_keywords() -> None:
    from sea_mile import RetryPolicy, SeaRouter

    with pytest.raises(TypeError):
        SeaRouter(retry_attempts=3)  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        SeaRouter(backoff_seconds=0.5)  # type: ignore[call-arg]

    assert SeaRouter(retry_policy=RetryPolicy(attempts=3)).retry_policy.attempts == 3


def test_searouter_no_longer_mirrors_the_retry_policy_as_attributes() -> None:
    from sea_mile import SeaRouter

    router = SeaRouter()

    assert not hasattr(router, "retry_attempts")
    assert not hasattr(router, "backoff_seconds")


def test_assess_route_length_no_longer_takes_loose_threshold_keywords() -> None:
    from sea_mile.routing import (
        RouteQualityFlag,
        RouteQualityPolicy,
        assess_route_length,
    )

    with pytest.raises(TypeError):
        assess_route_length(400, 300, high_detour_ratio=2.0)  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        assess_route_length(400, 300, lower_bound_tolerance_nmi=1.0)  # type: ignore[call-arg]

    assessment = assess_route_length(
        400, 300, policy=RouteQualityPolicy(high_detour_ratio=1.2)
    )
    assert assessment.flag is RouteQualityFlag.HIGH_DETOUR_RATIO
