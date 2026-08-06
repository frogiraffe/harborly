"""Run the structural route accuracy benchmark."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from benchmarks.route_accuracy.checks import (
    RouteObservation,
    observe,
    percentile,
    triangle_violations,
)
from benchmarks.route_accuracy.reference import (
    ReferencePair,
    load_reference_pairs,
    score_against_reference,
)
from benchmarks.route_accuracy.report import write_report
from harborly.exceptions import RoutingError
from harborly.router import SeaRouter

DATA = Path(__file__).resolve().parent / "data"


def _passage_set(cell: str) -> frozenset[str]:
    return frozenset(part for part in cell.split("|") if part)


def _load_voyages() -> list[dict[str, str]]:
    with (DATA / "voyages.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="benchmarks.route_accuracy")
    parser.add_argument("--out", type=Path, default=Path("benchmark-results"))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    router = SeaRouter()
    voyages = _load_voyages()

    observations: list[RouteObservation] = []
    distances: dict[tuple[str, str], float] = {}
    for voyage in voyages:
        origin = (float(voyage["origin_lat"]), float(voyage["origin_lon"]))
        destination = (
            float(voyage["destination_lat"]),
            float(voyage["destination_lon"]),
        )
        route = router.route_coordinates(*origin, *destination)
        observations.append(
            observe(
                voyage["name"],
                voyage["origin_name"],
                voyage["destination_name"],
                route,
                expected_passages=_passage_set(voyage["expected_passages"]),
                forbidden_passages=_passage_set(voyage["forbidden_passages"]),
            )
        )
        distances[(voyage["origin_name"], voyage["destination_name"])] = (
            route.distance_nmi
        )
        distances[(voyage["destination_name"], voyage["origin_name"])] = (
            route.distance_nmi
        )

    snaps = [observation.origin_snap_nmi for observation in observations] + [
        observation.destination_snap_nmi for observation in observations
    ]
    detours = [
        observation.detour_ratio
        for observation in observations
        if observation.detour_ratio is not None
    ]
    violations = triangle_violations(distances)

    all_reference_pairs = load_reference_pairs(DATA / "reference_distances.csv")
    reference_pairs: list[ReferencePair] = []
    reference_distances: list[float] = []
    reference_routing_failures: list[dict[str, str]] = []
    for pair in all_reference_pairs:
        try:
            route = router.route_coordinates(*pair.origin, *pair.destination)
        except RoutingError as error:
            # A curated pair the router genuinely cannot route (e.g. an
            # antimeridian-crossing geometry the backend rejects) is itself
            # useful signal, not a reason to crash the whole benchmark run.
            reference_routing_failures.append(
                {
                    "route": f"{pair.origin_name} -> {pair.destination_name}",
                    "error": str(error),
                }
            )
            continue
        reference_pairs.append(pair)
        reference_distances.append(route.distance_nmi)
    reference = score_against_reference(reference_pairs, reference_distances)
    reference["routing_failures"] = reference_routing_failures

    payload = {
        "voyages": len(observations),
        "reference": reference,
        "passage_failures": [
            observation.name for observation in observations if not observation.is_valid
        ],
        "snap_nmi": {
            "median": round(percentile(snaps, 0.5), 2),
            "p90": round(percentile(snaps, 0.9), 2),
            "max": round(max(snaps), 2) if snaps else 0.0,
        },
        "detour_ratio": {
            "median": round(percentile(detours, 0.5), 3),
            "p90": round(percentile(detours, 0.9), 3),
            "max": round(max(detours), 3) if detours else 0.0,
        },
        "triangle_violations": [
            {
                "direct": f"{first} -> {last}",
                "via": middle,
                "excess_nmi": round(excess, 1),
            }
            for first, middle, last, excess in violations
        ],
        "observations": [observation.as_dict() for observation in observations],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "route_accuracy.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    write_report(args.out / "route_accuracy.md", payload)

    print(f"voyages                 {payload['voyages']}")
    print(f"passage failures        {len(payload['passage_failures'])}")
    print(f"triangle violations     {len(payload['triangle_violations'])}")
    print(
        f"snap nmi                median {payload['snap_nmi']['median']} "
        f"p90 {payload['snap_nmi']['p90']} max {payload['snap_nmi']['max']}"
    )
    print(
        f"detour ratio            median {payload['detour_ratio']['median']} "
        f"p90 {payload['detour_ratio']['p90']} max {payload['detour_ratio']['max']}"
    )
    if reference["routing_failures"]:
        print(f"reference routing failures  {len(reference['routing_failures'])}")
        for failure in reference["routing_failures"]:
            print(f"  FAILED {failure['route']}: {failure['error']}")
    if reference["pairs"]:
        print(
            f"reference pairs         {reference['pairs']}   median APE "
            f"{reference['absolute_percentage_error']['median']}%   p90 "
            f"{reference['absolute_percentage_error']['p90']}%"
        )
    else:
        print("reference pairs         0 (none curated; distances unvalidated)")
    for name in payload["passage_failures"]:
        print(f"  FAILED {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
