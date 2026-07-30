"""Regression gate on route structure.

These assert facts about where a route goes, not how long it is. A voyage from
Shanghai to Rotterdam has to transit Malacca, Bab el-Mandeb, Suez and Gibraltar;
one from Rotterdam to Piraeus cannot use Suez. A graph or search change that
breaks those fails here rather than silently returning a plausible number.
"""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

from benchmarks.route_accuracy.checks import observe, percentile, triangle_violations
from sea_mile.router import SeaRouter

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("searoute") is None,
    reason="route accuracy needs the routing extra",
)

VOYAGES = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "route_accuracy"
    / "data"
    / "voyages.csv"
)

# Measured against searoute 1.6.0: median 3.18, p90 17.02, max 18.71.
MAXIMUM_SNAP_P90_NMI = 25.0


def _passage_set(cell: str) -> frozenset[str]:
    return frozenset(part for part in cell.split("|") if part)


@pytest.fixture(scope="module")
def observations():
    router = SeaRouter()
    with VOYAGES.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    results = []
    for row in rows:
        route = router.route_coordinates(
            float(row["origin_lat"]),
            float(row["origin_lon"]),
            float(row["destination_lat"]),
            float(row["destination_lon"]),
        )
        results.append(
            observe(
                row["name"],
                row["origin_name"],
                row["destination_name"],
                route,
                expected_passages=_passage_set(row["expected_passages"]),
                forbidden_passages=_passage_set(row["forbidden_passages"]),
            )
        )
    return results


def test_every_voyage_transits_the_passages_it_must(observations) -> None:
    missing = {
        observation.name: sorted(observation.missing_passages)
        for observation in observations
        if observation.missing_passages
    }

    assert missing == {}


def test_no_voyage_transits_a_passage_it_cannot(observations) -> None:
    unexpected = {
        observation.name: sorted(observation.unexpected_passages)
        for observation in observations
        if observation.unexpected_passages
    }

    assert unexpected == {}


def test_distances_obey_the_triangle_inequality(observations) -> None:
    distances: dict[tuple[str, str], float] = {}
    for observation in observations:
        distances[(observation.origin_name, observation.destination_name)] = (
            observation.distance_nmi
        )
        distances[(observation.destination_name, observation.origin_name)] = (
            observation.distance_nmi
        )

    assert triangle_violations(distances) == []


def test_ports_sit_close_to_the_graph_node_their_route_starts_from(
    observations,
) -> None:
    snaps = [observation.origin_snap_nmi for observation in observations]
    snaps += [observation.destination_snap_nmi for observation in observations]

    assert percentile(snaps, 0.9) <= MAXIMUM_SNAP_P90_NMI


def test_a_route_is_never_shorter_than_the_great_circle(observations) -> None:
    for observation in observations:
        assert observation.distance_nmi + 0.5 >= observation.great_circle_nmi, (
            observation.name
        )
