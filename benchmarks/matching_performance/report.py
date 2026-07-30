"""Render the matching performance payload as a readable Markdown report."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _row(label: str, stats: dict[str, Any]) -> str:
    return (
        f"| {label} | {stats['count']} | {stats['median_ms']:.3f} | "
        f"{stats['p90_ms']:.3f} | {stats['p95_ms']:.3f} | "
        f"{stats['throughput_rows_per_sec']:.1f} |"
    )


def write_report(path: Path, payload: dict[str, Any]) -> None:
    env = payload["environment"]
    registry = payload["registry"]
    lines = [
        "# Matching performance (bulk CSV workloads)",
        "",
        "Profiles `PortRegistry.match_names` (the same call `match_dataframe`",
        "makes per column) under bulk-CSV-shaped workloads. This measures",
        "latency and throughput only; it does not score matching correctness",
        "(see `matching_accuracy` for that) and this run made no code changes.",
        "",
        "## Environment",
        "",
        f"- Python `{env['python_version']}` on `{env['platform']}`",
        f"- CPU count: {env['cpu_count']}",
        "- Dependency versions: "
        + ", ".join(
            f"{name} {version}" for name, version in env["dependency_versions"].items()
        ),
        f"- Registry: {registry['rows']} rows, "
        f"loaded in {registry['load_seconds']:.3f}s",
        f"- Seed `{payload['seed']}`, "
        f"{payload['rows_per_bucket']} sampled rows per bucket",
        "",
        "## Per-row latency and throughput, by bucket",
        "",
        "`cold` is the first pass through a freshly loaded registry (empty",
        "`lru_cache`). `warm_pass_1`/`warm_pass_2` repeat the identical",
        "queries through the same registry instance, so every call is a cache",
        "hit by the second pass.",
        "",
        "| Bucket / pass | Rows | Median (ms) | p90 (ms) | p95 (ms) "
        "| Throughput (rows/s) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for bucket_name, bucket in payload["buckets"].items():
        lines.append(_row(f"{bucket_name} / cold", bucket["cold"]))
        lines.append(_row(f"{bucket_name} / warm_pass_1", bucket["warm_pass_1"]))
        lines.append(_row(f"{bucket_name} / warm_pass_2", bucket["warm_pass_2"]))

    lines += [
        "",
        "## Bulk single-call throughput (as `match_dataframe` would issue it)",
        "",
        "One `match_names(list_of_all_rows)` call per bucket, cold registry,",
        "compared against the sum of the per-row `cold` pass above to check",
        "that per-row timing did not itself distort the throughput number.",
        "",
        "| Bucket | Rows | Bulk throughput (rows/s) "
        "| Per-row-loop cold throughput (rows/s) |",
        "| --- | --- | --- | --- |",
    ]
    for bucket_name, bucket in payload["buckets"].items():
        lines.append(
            f"| {bucket_name} | {bucket['bulk']['count']} | "
            f"{bucket['bulk']['throughput_rows_per_sec']:.1f} | "
            f"{bucket['cold']['throughput_rows_per_sec']:.1f} |"
        )

    lines += [
        "",
        "## Dominant cost: cProfile over a cold mixed-bucket pass",
        "",
        f"Top {payload['profile_row_limit']} functions by cumulative time, "
        f"profiling {payload['profile_rows']} rows from the `mixed` bucket "
        "through a freshly loaded registry:",
        "",
        "```",
        payload["profile_top_cumulative"].rstrip(),
        "```",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
