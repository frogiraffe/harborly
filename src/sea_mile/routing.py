"""Route-quality rules independent of a routing engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


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
    lower_bound_tolerance_nmi: float = 0.5,
    high_detour_ratio: float = 3.0,
) -> RouteAssessment:
    """Check a sea-route result against basic physical plausibility rules."""

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
