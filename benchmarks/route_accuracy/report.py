"""Render the route benchmark payload as Markdown."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Route accuracy",
        "",
        "Structural checks only. These say whether a route goes where a voyage",
        "between two places has to go; they do not establish how close the",
        "distance is to a published reference.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Voyages | {payload['voyages']} |",
        f"| Passage failures | {len(payload['passage_failures'])} |",
        f"| Triangle violations | {len(payload['triangle_violations'])} |",
        f"| Snap median / p90 / max (nmi) | {payload['snap_nmi']['median']} / "
        f"{payload['snap_nmi']['p90']} / {payload['snap_nmi']['max']} |",
        f"| Detour median / p90 / max | {payload['detour_ratio']['median']} / "
        f"{payload['detour_ratio']['p90']} / {payload['detour_ratio']['max']} |",
        "",
        "Snap distance is how far a port coordinate sits from the graph node the",
        "route actually starts from. A large value means the reported voyage",
        "begins somewhere other than the port.",
        "",
        "## Reference distances",
        "",
    ]
    reference = payload["reference"]
    if reference.get("routing_failures"):
        lines += [
            f"{len(reference['routing_failures'])} curated pair(s) could not be "
            "routed at all and are excluded from the error statistics below "
            "(the failure itself is signal, e.g. an antimeridian-crossing "
            "geometry the backend rejects):",
            "",
        ]
        for failure in reference["routing_failures"]:
            lines.append(f"- `{failure['route']}`: {failure['error']}")
        lines.append("")
    if reference["pairs"]:
        lines += [
            f"{reference['pairs']} curated pairs.",
            "",
            "| Metric | Median | p90 | Max |",
            "| --- | --- | --- | --- |",
            f"| Absolute error (nmi) | {reference['absolute_error_nmi']['median']} | "
            f"{reference['absolute_error_nmi']['p90']} | "
            f"{reference['absolute_error_nmi']['max']} |",
            f"| Absolute percentage error | "
            f"{reference['absolute_percentage_error']['median']}% | "
            f"{reference['absolute_percentage_error']['p90']}% | "
            f"{reference['absolute_percentage_error']['max']}% |",
        ]
    else:
        lines += [
            "None curated, so **no claim is made about distance accuracy**. The",
            "checks above establish that routes go the right way, not that they",
            "report the right length. See",
            "`benchmarks/route_accuracy/data/README.md`.",
        ]
    lines += [
        "",
        "## Voyages",
        "",
        "| Voyage | Distance | Detour | Snap o/d | Passages | OK |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for observation in payload["observations"]:
        passages = ", ".join(observation["passages"]) or "—"
        mark = "yes" if observation["valid"] else "**no**"
        lines.append(
            f"| {observation['name']} | {observation['distance_nmi']} | "
            f"{observation['detour_ratio']} | {observation['origin_snap_nmi']}/"
            f"{observation['destination_snap_nmi']} | {passages} | {mark} |"
        )

    failures = [
        observation
        for observation in payload["observations"]
        if not observation["valid"]
    ]
    if failures:
        lines += ["", "## Passage failures", ""]
        for observation in failures:
            if observation["missing_passages"]:
                lines.append(
                    f"- `{observation['name']}` never entered "
                    f"{', '.join(observation['missing_passages'])}"
                )
            if observation["unexpected_passages"]:
                lines.append(
                    f"- `{observation['name']}` entered "
                    f"{', '.join(observation['unexpected_passages'])}, which a "
                    "voyage between these places cannot use"
                )

    if payload["triangle_violations"]:
        lines += [
            "",
            "## Triangle inequality violations",
            "",
            "| Direct | Via | Excess (nmi) |",
            "| --- | --- | --- |",
        ]
        for violation in payload["triangle_violations"]:
            lines.append(
                f"| {violation['direct']} | {violation['via']} | "
                f"{violation['excess_nmi']} |"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
