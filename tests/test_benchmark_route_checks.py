"""Pure logic behind the route benchmark, checked without a routing engine."""

from __future__ import annotations

from benchmarks.route_accuracy import PASSAGES_BY_NAME, passages_used
from benchmarks.route_accuracy.checks import (
    percentile,
    snap_distances,
    triangle_violations,
)


def test_a_vertex_inside_a_box_marks_that_passage() -> None:
    suez = PASSAGES_BY_NAME["suez_canal"]
    inside = [
        [(suez.min_longitude + suez.max_longitude) / 2],
        [(suez.min_latitude + suez.max_latitude) / 2],
    ]

    used = passages_used([[inside[0][0], inside[1][0]]])

    assert "suez_canal" in used


def test_a_route_that_misses_every_box_reports_no_passage() -> None:
    # Mid-Atlantic, far from any named waterway.
    assert passages_used([[-40.0, 30.0], [-35.0, 32.0]]) == frozenset()


def test_magellan_and_cape_horn_boxes_do_not_overlap() -> None:
    magellan = PASSAGES_BY_NAME["strait_of_magellan"]
    horn = PASSAGES_BY_NAME["cape_horn"]

    # A route through the strait must not read as rounding the cape.
    assert magellan.min_latitude > horn.max_latitude


def test_snap_distance_measures_the_gap_to_the_graph_node() -> None:
    # First vertex is the requested coordinate, second is the node used.
    # One minute of latitude is one nautical mile.
    coordinates = [
        [0.0, 0.0],
        [0.0, 1 / 60],
        [10.0, 10.0],
        [20.0, 20.0 + 2 / 60],
        [20.0, 20.0],
    ]

    origin, destination = snap_distances(coordinates)

    assert round(origin, 2) == 1.0
    assert round(destination, 2) == 2.0


def test_snap_distance_is_zero_for_a_geometry_too_short_to_have_nodes() -> None:
    assert snap_distances([[0.0, 0.0], [1.0, 1.0]]) == (0.0, 0.0)


def test_a_direct_route_longer_than_a_detour_is_a_violation() -> None:
    distances = {
        ("A", "B"): 100.0,
        ("B", "A"): 100.0,
        ("B", "C"): 100.0,
        ("C", "B"): 100.0,
        ("A", "C"): 500.0,
        ("C", "A"): 500.0,
    }

    violations = triangle_violations(distances)

    assert any(
        first == "A" and middle == "B" and last == "C"
        for first, middle, last, _ in violations
    )


def test_consistent_distances_report_no_violation() -> None:
    distances = {
        ("A", "B"): 100.0,
        ("B", "A"): 100.0,
        ("B", "C"): 100.0,
        ("C", "B"): 100.0,
        ("A", "C"): 150.0,
        ("C", "A"): 150.0,
    }

    assert triangle_violations(distances) == []


def test_percentile_picks_from_the_ordered_values() -> None:
    assert percentile([5.0, 1.0, 3.0], 0.5) == 3.0
    assert percentile([], 0.5) == 0.0
