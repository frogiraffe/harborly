"""Profile `PortRegistry.match_names` under realistic bulk CSV workloads.

Measures per-row latency (median/p90/p95) and throughput across four bucket
shapes -- exact-only, fuzzy-typo, country-less fallback, and a shuffled mixed
batch -- each cold (fresh registry) and warm (repeated queries against the
same registry, so the `lru_cache` in `PortRegistry._search_cached` is hot).
A cProfile pass over a cold mixed-bucket sample identifies the dominant cost.

This script only measures; it does not change matching behavior or attempt
any optimization. See `benchmark-results/matching_performance.md` for the
resulting numbers.
"""

from __future__ import annotations

import argparse
import cProfile
import importlib.metadata
import json
import os
import platform
import pstats
import time
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from benchmarks.matching_performance.report import write_report
from benchmarks.matching_performance.timing import time_bulk, time_rows
from benchmarks.matching_performance.workload import (
    WorkloadRow,
    build_country_less,
    build_exact_only,
    build_fuzzy_typo,
    build_mixed,
)
from harborly._registry_data import bundled_data_directory
from harborly.ports import PortRegistry

_PROFILE_ROW_LIMIT = 25


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="benchmarks.matching_performance")
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument(
        "--rows",
        type=int,
        default=500,
        help="rows sampled per bucket (exact_only, fuzzy_typo, country_less)",
    )
    parser.add_argument(
        "--profile-rows",
        type=int,
        default=300,
        help="rows from the mixed bucket to run under cProfile",
    )
    parser.add_argument("--out", type=Path, default=Path("benchmark-results"))
    return parser.parse_args()


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("pandas", "numpy", "rapidfuzz", "pyarrow", "pandera"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def _profile_cold_mixed(rows: list[WorkloadRow], *, row_limit: int) -> str:
    fresh_registry = PortRegistry.bundled()
    profiler = cProfile.Profile()
    profiler.enable()
    for row in rows:
        fresh_registry.match_names([row.query], country_codes=[row.country_code])
    profiler.disable()

    buffer = StringIO()
    stats = pstats.Stats(profiler, stream=buffer)
    stats.sort_stats("cumulative")
    stats.print_stats(row_limit)
    return buffer.getvalue()


def main() -> int:
    args = _parse_args()

    load_start = time.perf_counter()
    PortRegistry.bundled()
    registry_load_seconds = time.perf_counter() - load_start
    frame = pd.read_parquet(bundled_data_directory() / "port_registry.parquet")

    exact_only = build_exact_only(frame, seed=args.seed, size=args.rows)
    fuzzy_typo = build_fuzzy_typo(frame, seed=args.seed + 1, size=args.rows)
    country_less = build_country_less(frame, seed=args.seed + 2, size=args.rows)
    mixed = build_mixed(exact_only, fuzzy_typo, country_less, seed=args.seed + 3)

    buckets: dict[str, list[WorkloadRow]] = {
        "exact_only": exact_only,
        "fuzzy_typo": fuzzy_typo,
        "country_less": country_less,
        "mixed": mixed,
    }

    bucket_results: dict[str, dict[str, Any]] = {}
    for name, rows in buckets.items():
        if not rows:
            continue
        cold_registry = PortRegistry.bundled()
        cold = time_rows(cold_registry, rows)
        warm_pass_1 = time_rows(cold_registry, rows)
        warm_pass_2 = time_rows(cold_registry, rows)
        bulk = time_bulk(PortRegistry.bundled(), rows)
        bucket_results[name] = {
            "rows": len(rows),
            "cold": cold.as_dict(),
            "warm_pass_1": warm_pass_1.as_dict(),
            "warm_pass_2": warm_pass_2.as_dict(),
            "bulk": bulk.as_dict(),
        }

    profile_sample = mixed[: min(len(mixed), args.profile_rows)]
    profile_text = (
        _profile_cold_mixed(profile_sample, row_limit=_PROFILE_ROW_LIMIT)
        if profile_sample
        else ""
    )

    payload = {
        "seed": args.seed,
        "rows_per_bucket": args.rows,
        "profile_rows": len(profile_sample),
        "profile_row_limit": _PROFILE_ROW_LIMIT,
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "dependency_versions": _dependency_versions(),
        },
        "registry": {
            "rows": len(frame),
            "load_seconds": registry_load_seconds,
        },
        "buckets": bucket_results,
        "profile_top_cumulative": profile_text,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "matching_performance.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    write_report(args.out / "matching_performance.md", payload)
    _print_summary(bucket_results)
    return 0


def _print_summary(bucket_results: dict[str, dict[str, Any]]) -> None:
    for name, bucket in bucket_results.items():
        cold = bucket["cold"]
        warm = bucket["warm_pass_2"]
        print(
            f"{name:14s} cold median={cold['median_ms']:.3f}ms "
            f"p90={cold['p90_ms']:.3f}ms "
            f"throughput={cold['throughput_rows_per_sec']:.1f}/s "
            f"| warm median={warm['median_ms']:.3f}ms "
            f"throughput={warm['throughput_rows_per_sec']:.1f}/s"
        )


if __name__ == "__main__":
    raise SystemExit(main())
