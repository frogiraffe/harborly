"""Timing helpers for the matching performance benchmark."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from benchmarks.matching_performance.workload import WorkloadRow
from harborly.ports import PortRegistry


@dataclass(frozen=True, slots=True)
class LatencyStats:
    count: int
    total_seconds: float
    median_ms: float
    p90_ms: float
    p95_ms: float
    throughput_rows_per_sec: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "total_seconds": self.total_seconds,
            "median_ms": self.median_ms,
            "p90_ms": self.p90_ms,
            "p95_ms": self.p95_ms,
            "throughput_rows_per_sec": self.throughput_rows_per_sec,
        }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1)))
    return sorted_values[index]


def time_rows(registry: PortRegistry, rows: list[WorkloadRow]) -> LatencyStats:
    """Call `match_names` once per row so per-row latency can be measured.

    `match_names` already loops over each name internally when called with a
    full batch (see `PortRegistry.match_names`), so calling it once per row
    adds only the fixed per-call overhead of the outer function itself, not a
    different code path. `time_bulk` below measures a single whole-batch call
    for comparison, to keep that assumption honest rather than assumed.
    """

    latencies_ms: list[float] = []
    start = time.perf_counter()
    for row in rows:
        row_start = time.perf_counter()
        registry.match_names([row.query], country_codes=[row.country_code])
        latencies_ms.append((time.perf_counter() - row_start) * 1000.0)
    total = time.perf_counter() - start

    sorted_ms = sorted(latencies_ms)
    return LatencyStats(
        count=len(rows),
        total_seconds=total,
        median_ms=statistics.median(sorted_ms) if sorted_ms else 0.0,
        p90_ms=_percentile(sorted_ms, 0.90),
        p95_ms=_percentile(sorted_ms, 0.95),
        throughput_rows_per_sec=(len(rows) / total) if total > 0 else 0.0,
    )


def time_bulk(registry: PortRegistry, rows: list[WorkloadRow]) -> LatencyStats:
    """Time a single whole-batch `match_names` call, as `match_dataframe`
    would issue it for one bulk CSV import."""

    start = time.perf_counter()
    registry.match_names(
        [row.query for row in rows],
        country_codes=[row.country_code for row in rows],
    )
    total = time.perf_counter() - start
    return LatencyStats(
        count=len(rows),
        total_seconds=total,
        median_ms=0.0,
        p90_ms=0.0,
        p95_ms=0.0,
        throughput_rows_per_sec=(len(rows) / total) if total > 0 else 0.0,
    )
