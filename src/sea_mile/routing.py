"""Route-quality rules independent of a routing engine."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Any

MAX_RETRY_ATTEMPTS = 8
_MAX_BACKOFF_SECONDS = 8.0
_UNSET: Any = object()


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Canonical configuration for backend retry attempts and backoff."""

    attempts: int = 4
    base_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 8.0
    jitter_ratio: float = 0.5
    overall_timeout_seconds: float | None = None
    """Wall-clock budget for the whole retry ladder, or None for no budget.

    This bounds *scheduling*, not execution: the loop refuses to start a wait
    or an attempt once the budget cannot hold it, but a backend call already
    running cannot be interrupted, so a single slow attempt can still overrun.
    Enforcing a per-attempt deadline needs a backend that accepts one.
    """

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("retry_attempts must be at least 1")
        if self.attempts > MAX_RETRY_ATTEMPTS:
            raise ValueError(f"retry_attempts cannot exceed {MAX_RETRY_ATTEMPTS}")
        if not isfinite(self.base_backoff_seconds) or self.base_backoff_seconds < 0:
            raise ValueError("backoff_seconds must be finite and non-negative")
        if not isfinite(self.max_backoff_seconds) or self.max_backoff_seconds < 0:
            raise ValueError("max_backoff_seconds must be finite and non-negative")
        if self.base_backoff_seconds > self.max_backoff_seconds:
            raise ValueError(
                "base_backoff_seconds cannot be greater than max_backoff_seconds"
            )
        if not isfinite(self.jitter_ratio) or not 0.0 <= self.jitter_ratio <= 1.0:
            raise ValueError("jitter_ratio must be finite and between 0.0 and 1.0")
        if self.overall_timeout_seconds is not None and (
            not isfinite(self.overall_timeout_seconds)
            or self.overall_timeout_seconds <= 0
        ):
            raise ValueError("overall_timeout_seconds must be finite and positive")


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    """One dependency probe: what was checked, whether it works, and why."""

    name: str
    passed: bool
    detail: str


class CacheFailurePolicy(StrEnum):
    """What a failing persistent route cache should cost the caller.

    Every entry the cache holds can be recomputed, so a cache failure need not
    be a routing failure. Which answer is right depends on the caller, so it is
    stated rather than assumed.
    """

    STRICT = "strict"
    """Surface any cache failure as a RoutingError. The default: an SDK caller
    asking for a cached result should hear that the cache is broken."""

    BEST_EFFORT = "best_effort"
    """Log cache failures and answer from a fresh computation. For a service
    that would rather be slow than unavailable."""


@dataclass(frozen=True, slots=True)
class RouteQualityPolicy:
    """Centralized configuration for route quality thresholds."""

    lower_bound_tolerance_nmi: float = 0.5
    high_detour_ratio: float = 3.0


class RouteQualityFlag(StrEnum):
    OK = "ok"
    HIGH_DETOUR_RATIO = "high_detour_ratio"
    COINCIDENT_ENDPOINTS = "coincident_endpoints"
    BELOW_GREAT_CIRCLE_LOWER_BOUND = "below_great_circle_lower_bound"
    NONZERO_ROUTE_FOR_COINCIDENT_ENDPOINTS = "nonzero_route_for_coincident_endpoints"
    INVALID_ROUTE_DISTANCE = "invalid_route_distance"
    INVALID_GREAT_CIRCLE_DISTANCE = "invalid_great_circle_distance"


@dataclass(frozen=True, slots=True)
class RouteAssessment:
    is_valid: bool
    flag: RouteQualityFlag
    detour_ratio: float | None


def assess_route_length(
    sea_distance_nmi: float,
    great_circle_distance_nmi: float,
    *,
    policy: RouteQualityPolicy | None = None,
    lower_bound_tolerance_nmi: float = _UNSET,
    high_detour_ratio: float = _UNSET,
) -> RouteAssessment:
    """Check a sea-route result against basic physical plausibility rules.

    *lower_bound_tolerance_nmi* and *high_detour_ratio* are deprecated; pass a
    *policy* instead. When *policy* is given, its thresholds take precedence
    over the deprecated keywords.
    """

    if lower_bound_tolerance_nmi is not _UNSET or high_detour_ratio is not _UNSET:
        warnings.warn(
            "assess_route_length(lower_bound_tolerance_nmi=..., "
            "high_detour_ratio=...) is deprecated and will be removed in the"
            " next major version; pass policy=RouteQualityPolicy(...) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    active = policy if policy is not None else RouteQualityPolicy()
    if lower_bound_tolerance_nmi is _UNSET or policy is not None:
        lower_bound_tolerance_nmi = active.lower_bound_tolerance_nmi
    if high_detour_ratio is _UNSET or policy is not None:
        high_detour_ratio = active.high_detour_ratio

    if not isfinite(sea_distance_nmi) or sea_distance_nmi < 0:
        return RouteAssessment(False, RouteQualityFlag.INVALID_ROUTE_DISTANCE, None)
    if not isfinite(great_circle_distance_nmi) or great_circle_distance_nmi < 0:
        return RouteAssessment(
            False, RouteQualityFlag.INVALID_GREAT_CIRCLE_DISTANCE, None
        )
    if great_circle_distance_nmi == 0:
        if sea_distance_nmi <= lower_bound_tolerance_nmi:
            return RouteAssessment(True, RouteQualityFlag.COINCIDENT_ENDPOINTS, None)
        return RouteAssessment(
            False, RouteQualityFlag.NONZERO_ROUTE_FOR_COINCIDENT_ENDPOINTS, None
        )
    detour_ratio = sea_distance_nmi / great_circle_distance_nmi
    if sea_distance_nmi + lower_bound_tolerance_nmi < great_circle_distance_nmi:
        return RouteAssessment(
            False, RouteQualityFlag.BELOW_GREAT_CIRCLE_LOWER_BOUND, detour_ratio
        )
    if detour_ratio > high_detour_ratio:
        return RouteAssessment(True, RouteQualityFlag.HIGH_DETOUR_RATIO, detour_ratio)
    return RouteAssessment(True, RouteQualityFlag.OK, detour_ratio)
