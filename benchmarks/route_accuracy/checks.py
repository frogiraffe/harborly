"""Facts a route must satisfy regardless of which engine produced it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benchmarks.route_accuracy.chokepoints import passages_used
from harborly.geo import great_circle_nmi


@dataclass(frozen=True, slots=True)
class RouteObservation:
    """One measured voyage."""

    name: str
    origin_name: str
    destination_name: str
    distance_nmi: float
    great_circle_nmi: float
    detour_ratio: float | None
    origin_snap_nmi: float
    destination_snap_nmi: float
    vertices: int
    passages: frozenset[str]
    expected_passages: frozenset[str]
    forbidden_passages: frozenset[str]

    @property
    def missing_passages(self) -> frozenset[str]:
        return self.expected_passages - self.passages

    @property
    def unexpected_passages(self) -> frozenset[str]:
        return self.forbidden_passages & self.passages

    @property
    def is_valid(self) -> bool:
        return not self.missing_passages and not self.unexpected_passages

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "origin": self.origin_name,
            "destination": self.destination_name,
            "distance_nmi": round(self.distance_nmi, 1),
            "great_circle_nmi": round(self.great_circle_nmi, 1),
            "detour_ratio": round(self.detour_ratio, 3)
            if self.detour_ratio is not None
            else None,
            "origin_snap_nmi": round(self.origin_snap_nmi, 2),
            "destination_snap_nmi": round(self.destination_snap_nmi, 2),
            "vertices": self.vertices,
            "passages": sorted(self.passages),
            "missing_passages": sorted(self.missing_passages),
            "unexpected_passages": sorted(self.unexpected_passages),
            "valid": self.is_valid,
        }


def snap_distances(coordinates: list[list[float]]) -> tuple[float, float]:
    """Return how far each endpoint sits from the graph node the route uses.

    The backend is called with ``append_orig_dest``, so the first vertex is the
    coordinate that was asked for and the second is the node the engine actually
    started from; the last two mirror that. A large snap means the route begins
    somewhere other than the port, which is the most likely source of error for a
    port whose coordinate sits up a river or inland.
    """

    if len(coordinates) < 4:
        return 0.0, 0.0
    origin = great_circle_nmi(
        coordinates[0][1], coordinates[0][0], coordinates[1][1], coordinates[1][0]
    )
    destination = great_circle_nmi(
        coordinates[-1][1], coordinates[-1][0], coordinates[-2][1], coordinates[-2][0]
    )
    return origin, destination


def observe(
    name: str,
    origin_name: str,
    destination_name: str,
    route: Any,
    *,
    expected_passages: frozenset[str],
    forbidden_passages: frozenset[str],
) -> RouteObservation:
    coordinates = route.geometry["coordinates"]
    origin_snap, destination_snap = snap_distances(coordinates)
    return RouteObservation(
        name=name,
        origin_name=origin_name,
        destination_name=destination_name,
        distance_nmi=route.distance_nmi,
        great_circle_nmi=route.great_circle_nmi,
        detour_ratio=route.detour_ratio,
        origin_snap_nmi=origin_snap,
        destination_snap_nmi=destination_snap,
        vertices=len(coordinates),
        passages=passages_used(coordinates),
        expected_passages=expected_passages,
        forbidden_passages=forbidden_passages,
    )


def triangle_violations(
    distances: dict[tuple[str, str], float], *, tolerance_nmi: float = 1.0
) -> list[tuple[str, str, str, float]]:
    """Return every ``A->C`` longer than ``A->B->C`` by more than the tolerance.

    A shortest-path engine cannot produce a direct route longer than a detour
    through a third point, so any violation is a graph or search defect.
    """

    places = sorted({name for pair in distances for name in pair})
    violations: list[tuple[str, str, str, float]] = []
    for first in places:
        for middle in places:
            for last in places:
                if len({first, middle, last}) < 3:
                    continue
                direct = distances.get((first, last))
                left = distances.get((first, middle))
                right = distances.get((middle, last))
                if direct is None or left is None or right is None:
                    continue
                excess = direct - (left + right)
                if excess > tolerance_nmi:
                    violations.append((first, middle, last, excess))
    return violations


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]
