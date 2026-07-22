"""Route-quality rules independent of a routing engine."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class RouteAssessment:
    is_valid: bool
    flag: str
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
        return RouteAssessment(False, "invalid_route_distance", None)
    if not isfinite(great_circle_distance_nmi) or great_circle_distance_nmi < 0:
        return RouteAssessment(False, "invalid_great_circle_distance", None)
    if great_circle_distance_nmi == 0:
        if sea_distance_nmi <= lower_bound_tolerance_nmi:
            return RouteAssessment(True, "coincident_endpoints", None)
        return RouteAssessment(False, "nonzero_route_for_coincident_endpoints", None)
    detour_ratio = sea_distance_nmi / great_circle_distance_nmi
    if sea_distance_nmi + lower_bound_tolerance_nmi < great_circle_distance_nmi:
        return RouteAssessment(False, "below_great_circle_lower_bound", detour_ratio)
    if detour_ratio > high_detour_ratio:
        return RouteAssessment(True, "high_detour_ratio", detour_ratio)
    return RouteAssessment(True, "ok", detour_ratio)
