"""Run the matching accuracy benchmark against the bundled registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from benchmarks.matching_accuracy.cases import build_cases, mine_hard_negatives
from benchmarks.matching_accuracy.metrics import (
    OFFICIAL_PROVIDERS,
    MatchingMetrics,
    score,
)
from benchmarks.matching_accuracy.report import write_report
from sea_mile._registry_data import bundled_data_directory
from sea_mile.ports import PortRegistry


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="benchmarks.matching_accuracy")
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument(
        "--sample-size",
        type=int,
        default=400,
        help="registry records to perturb; each yields several queries",
    )
    parser.add_argument("--out", type=Path, default=Path("benchmark-results"))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    registry = PortRegistry.bundled()
    frame = pd.read_parquet(bundled_data_directory() / "port_registry.parquet")

    cases = build_cases(frame, seed=args.seed, sample_size=args.sample_size)
    cases.extend(mine_hard_negatives(frame))
    if not cases:
        raise SystemExit("no benchmark cases were generated")

    results = registry.match_names(
        [case.query for case in cases],
        country_codes=[case.country_code for case in cases],
    )
    canonical_by_registry_id = dict(
        zip(frame["registry_id"], frame["canonical_id"], strict=True)
    )
    official_canonical_ids = frozenset(
        frame.loc[frame["provider"].isin(OFFICIAL_PROVIDERS), "canonical_id"]
    )
    located = frame[frame["latitude"].notna() & frame["longitude"].notna()]
    coordinates_by_registry_id = {
        str(row.registry_id): (float(row.latitude), float(row.longitude))
        for row in located.itertuples()
    }
    metrics = score(
        cases,
        results,
        canonical_by_registry_id,
        official_canonical_ids,
        coordinates_by_registry_id=coordinates_by_registry_id,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {
        "seed": args.seed,
        "sample_size": args.sample_size,
        "registry_rows": len(frame),
        "metrics": metrics.as_dict(),
    }
    (args.out / "matching_accuracy.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    write_report(args.out / "matching_accuracy.md", payload)
    _print_summary(metrics)
    return 0


def _print_summary(metrics: MatchingMetrics) -> None:
    print(f"cases                      {metrics.total}")
    print(f"auto-resolved precision    {metrics.auto_resolved_precision:.4f}")
    print(f"auto-resolve rate          {metrics.auto_resolve_rate:.4f}")
    print(f"review rate                {metrics.review_rate:.4f}")
    print(f"unresolved rate            {metrics.unresolved_rate:.4f}")
    print(f"candidate recall           {metrics.candidate_recall:.4f}")
    print(
        f"official candidate recall  {metrics.official_candidate_recall:.4f} "
        f"(over {metrics.official_candidate_cases} cases with an official record)"
    )
    print(
        f"hard negatives             {metrics.hard_negatives} "
        f"({metrics.hard_negative_auto_resolved} auto-resolved)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
