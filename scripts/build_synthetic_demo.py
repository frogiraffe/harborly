"""Build a small demo GeoJSON file, with fixed example routes."""

from __future__ import annotations

import json
from pathlib import Path

import searoute

from sea_mile.geo import great_circle_nmi
from sea_mile.routing import assess_route_length

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "examples" / "synthetic" / "synthetic_routes.geojson"
# Loaded via a <script> tag so the demo also works when index.html is opened
# directly (file://), where fetch() of a local file is blocked by CORS.
INLINE_OUTPUT_PATH = OUTPUT_PATH.parent / (OUTPUT_PATH.name + ".js")

# Fixed example points. Not a real port record.
EXAMPLE_ROUTES = (
    ("EX-001", "EX-O-WMED", [1.0, 39.0], "EX-D-EMED", [32.0, 34.5]),
    ("EX-002", "EX-O-WMED", [1.0, 39.0], "EX-D-ADRI", [17.5, 41.5]),
    ("EX-003", "EX-O-ATL", [-8.0, 43.0], "EX-D-NSEA", [3.0, 53.0]),
    ("EX-004", "EX-O-ATL", [-8.0, 43.0], "EX-D-EMED", [32.0, 34.5]),
    ("EX-005", "EX-O-AEGE", [25.5, 38.5], "EX-D-ADRI", [17.5, 41.5]),
    ("EX-006", "EX-O-AEGE", [25.5, 38.5], "EX-D-EMED", [32.0, 34.5]),
)


def main() -> None:
    features: list[dict] = []
    for route_id, origin_id, origin, destination_id, destination in EXAMPLE_ROUTES:
        feature = searoute.searoute(
            origin,
            destination,
            units="naut",
            append_orig_dest=True,
            restrictions=["northwest"],
            algorithm="astar",
            backend="networkx",
        )
        great_circle = great_circle_nmi(
            origin[1], origin[0], destination[1], destination[0]
        )
        sea_distance = float(feature.properties["length"])
        assessment = assess_route_length(sea_distance, great_circle)
        features.append(
            {
                "type": "Feature",
                "id": route_id,
                "properties": {
                    "route_id": route_id,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "data_scope": "example",
                    "distance_nmi": round(sea_distance, 3),
                    "great_circle_nmi": round(great_circle, 3),
                    "detour_ratio": round(assessment.detour_ratio, 4)
                    if assessment.detour_ratio is not None
                    else None,
                    "quality_flag": assessment.flag,
                    "routing_engine": f"searoute {searoute.__version__}",
                    "routing_units": "nautical_miles",
                    "navigation_warning": "Example route; not for navigation.",
                },
                "geometry": feature.geometry,
            }
        )

    collection = {
        "type": "FeatureCollection",
        "name": "sea-mile synthetic demo",
        "description": "Six fixed example routes. Not real port data.",
        "features": features,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    INLINE_OUTPUT_PATH.write_text(
        "window.SYNTHETIC_ROUTES = "
        + json.dumps(collection, ensure_ascii=False, indent=2)
        + ";\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH.relative_to(PROJECT_ROOT)),
                "inline_output": str(INLINE_OUTPUT_PATH.relative_to(PROJECT_ROOT)),
                "features": len(features),
                "all_routes_valid": all(
                    feature["properties"]["quality_flag"] in {"ok", "high_detour_ratio"}
                    for feature in features
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
