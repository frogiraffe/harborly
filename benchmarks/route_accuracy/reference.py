"""Compare computed distances against published reference distances."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.route_accuracy.checks import percentile


@dataclass(frozen=True, slots=True)
class ReferencePair:
    origin_name: str
    origin: tuple[float, float]
    destination_name: str
    destination: tuple[float, float]
    reference_nmi: float
    source: str
    source_url: str


def load_reference_pairs(path: Path) -> list[ReferencePair]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    pairs = []
    for row in rows:
        if not row.get("reference_nmi"):
            continue
        if not row.get("source"):
            raise ValueError(
                f"reference distance for {row.get('origin_name')!r} -> "
                f"{row.get('destination_name')!r} has no source; a figure that "
                "cannot be checked must not be scored"
            )
        pairs.append(
            ReferencePair(
                origin_name=row["origin_name"],
                origin=(float(row["origin_lat"]), float(row["origin_lon"])),
                destination_name=row["destination_name"],
                destination=(
                    float(row["destination_lat"]),
                    float(row["destination_lon"]),
                ),
                reference_nmi=float(row["reference_nmi"]),
                source=row["source"],
                source_url=row.get("source_url", ""),
            )
        )
    return pairs


def score_against_reference(
    pairs: list[ReferencePair], computed_nmi: list[float]
) -> dict[str, Any]:
    """Return absolute and percentage error statistics, or an empty summary."""

    if not pairs:
        return {
            "pairs": 0,
            "note": (
                "no curated reference distances; see "
                "benchmarks/route_accuracy/data/README.md"
            ),
        }
    absolute = [
        abs(computed - pair.reference_nmi)
        for pair, computed in zip(pairs, computed_nmi, strict=True)
    ]
    percentage = [
        100.0 * error / pair.reference_nmi
        for pair, error in zip(pairs, absolute, strict=True)
        if pair.reference_nmi
    ]
    return {
        "pairs": len(pairs),
        "absolute_error_nmi": {
            "median": round(percentile(absolute, 0.5), 1),
            "p90": round(percentile(absolute, 0.9), 1),
            "max": round(max(absolute), 1),
        },
        "absolute_percentage_error": {
            "median": round(percentile(percentage, 0.5), 2),
            "p90": round(percentile(percentage, 0.9), 2),
            "max": round(max(percentage), 2),
        },
        "worst": [
            {
                "route": f"{pair.origin_name} -> {pair.destination_name}",
                "computed_nmi": round(computed, 1),
                "reference_nmi": pair.reference_nmi,
                "error_nmi": round(error, 1),
                "source": pair.source,
            }
            for pair, computed, error in sorted(
                zip(pairs, computed_nmi, absolute, strict=True),
                key=lambda item: item[2],
                reverse=True,
            )[:10]
        ],
    }
