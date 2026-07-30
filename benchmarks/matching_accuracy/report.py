"""Render the benchmark payload as a readable Markdown report."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def write_report(path: Path, payload: dict[str, Any]) -> None:
    metrics = payload["metrics"]
    lines = [
        "# Matching accuracy",
        "",
        f"Seed `{payload['seed']}`, {payload['sample_size']} sampled records, "
        f"{payload['registry_rows']} registry rows.",
        "",
        "Queries are perturbed names of known records. The expected answer is the",
        "record's `canonical_id`, so resolving to any provider holding that place",
        "counts as correct.",
        "",
        "## Headline",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Cases | {metrics['total']} |",
        f"| Auto-resolved precision | {metrics['auto_resolved_precision']:.4f} |",
        f"| Auto-resolve rate | {metrics['auto_resolve_rate']:.4f} |",
        f"| Review rate | {metrics['review_rate']:.4f} |",
        f"| Unresolved rate | {metrics['unresolved_rate']:.4f} |",
        f"| Candidate recall | {metrics['candidate_recall']:.4f} |",
        f"| Official candidate recall | {metrics['official_candidate_recall']:.4f} |",
        "",
        "`auto_wrong` is the count that matters most: a confident wrong answer.",
        f"It is currently **{metrics['auto_wrong']}**.",
        "",
        "## Hard negatives",
        "",
        "Records sharing a country and name but lying further apart than the",
        "coordinate agreement radius. No single answer is correct, so any",
        "auto-resolution here is a defect.",
        "",
        f"- mined: {metrics['hard_negatives']}",
        f"- auto-resolved: **{metrics['hard_negative_auto_resolved']}**",
        "",
        "## By perturbation",
        "",
        "| Variant | Cases | Auto | Correct | Review | Unresolved | Recall |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for variant, score in metrics["by_variant"].items():
        lines.append(
            f"| {variant} | {score['total']} | {score['auto_resolved']} | "
            f"{score['auto_correct']} | {score['review_required']} | "
            f"{score['unresolved']} | {score['candidate_recall']:.4f} |"
        )

    if metrics["worst_countries"]:
        lines += [
            "",
            "## Weakest countries by candidate recall",
            "",
            "| Country | Candidate recall |",
            "| --- | --- |",
        ]
        for entry in metrics["worst_countries"]:
            lines.append(
                f"| {entry['country_code']} | {entry['candidate_recall']:.4f} |"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
