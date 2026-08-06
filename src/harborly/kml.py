"""KML export utilities for sea routes and waypoint sequences."""

from __future__ import annotations

import html
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harborly.router import SeaRoute, SequenceSeaRoute


def _extract_lines(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Return a list of coordinate lists from a GeoJSON geometry.

    Returns a list of line-lists so callers can preserve MultiLineString
    segment boundaries and emit proper KML <MultiGeometry> when needed.
    """
    gtype = geometry.get("type", "")
    # Guard against explicit None coordinates (OGC allows an absent 'coordinates')
    raw_coords = geometry.get("coordinates") or []

    if gtype == "LineString":
        line: list[tuple[float, float]] = []
        for pt in raw_coords:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                line.append((float(pt[0]), float(pt[1])))
        return [line] if line else []

    if gtype == "MultiLineString":
        result: list[list[tuple[float, float]]] = []
        for segment in raw_coords:
            seg_pts: list[tuple[float, float]] = []
            for pt in segment:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    seg_pts.append((float(pt[0]), float(pt[1])))
            if seg_pts:
                result.append(seg_pts)
        return result

    return []


def _extract_coordinates(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    """Flatten all lines from a GeoJSON geometry into a single coordinate list.

    Used for single-LineString KML output. MultiLineString segments are
    concatenated in order, which is acceptable for most visualisation tools.
    For topology-preserving output use _extract_lines + KML MultiGeometry.
    """
    return [pt for line in _extract_lines(geometry) for pt in line]


def _placemark_for_geometry(
    geometry: dict[str, Any],
    name: str,
    description: str,
    indent: str = "    ",
) -> list[str]:
    """Build KML <Placemark> lines for a geometry, using <MultiGeometry> when needed."""
    lines_data = _extract_lines(geometry)
    if not lines_data:
        return []

    inner = f"{indent}  "
    inner2 = f"{inner}  "
    placemark = [
        f"{indent}<Placemark>",
        f"{inner}<name>{html.escape(name)}</name>",
        f"{inner}<description>{html.escape(description)}</description>",
    ]

    if len(lines_data) == 1:
        coord_str = " ".join(f"{lon},{lat},0" for lon, lat in lines_data[0])
        placemark.extend(
            [
                f"{inner}<LineString>",
                f"{inner2}<tessellate>1</tessellate>",
                f"{inner2}<coordinates>{coord_str}</coordinates>",
                f"{inner}</LineString>",
            ]
        )
    else:
        # MultiLineString → KML <MultiGeometry> to avoid artificial connecting lines
        placemark.append(f"{inner}<MultiGeometry>")
        for segment in lines_data:
            coord_str = " ".join(f"{lon},{lat},0" for lon, lat in segment)
            placemark.extend(
                [
                    f"{inner2}<LineString>",
                    f"{inner2}  <tessellate>1</tessellate>",
                    f"{inner2}  <coordinates>{coord_str}</coordinates>",
                    f"{inner2}</LineString>",
                ]
            )
        placemark.append(f"{inner}</MultiGeometry>")

    placemark.append(f"{indent}</Placemark>")
    return placemark


def to_kml_string(route: SeaRoute | SequenceSeaRoute) -> str:
    """Generate a standard KML document string for a sea route or multi-leg sequence."""
    from harborly.router import SequenceSeaRoute  # noqa: PLC0415

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "  <Document>",
    ]

    if isinstance(route, SequenceSeaRoute):
        name = f"Route Sequence ({len(route.ports)} ports)"
        lines.append(f"    <name>{html.escape(name)}</name>")
        lines.append(
            "    <description>Total distance: "
            f"{route.total_distance_nmi:.2f} nmi</description>"
        )

        for idx, leg in enumerate(route.legs, start=1):
            leg_name = f"Leg {idx}: {leg.origin.name} to {leg.destination.name}"
            desc = f"Distance: {leg.distance_nmi:.2f} nmi"
            lines.extend(
                _placemark_for_geometry(leg.geometry, leg_name, desc, indent="    ")
            )
    else:
        name = f"{route.origin.name} to {route.destination.name}"
        desc = f"Distance: {route.distance_nmi:.2f} nmi"
        lines.append(f"    <name>{html.escape(name)}</name>")
        lines.append(f"    <description>{html.escape(desc)}</description>")
        lines.extend(_placemark_for_geometry(route.geometry, name, desc, indent="    "))

    lines.extend(["  </Document>", "</kml>"])
    return "\n".join(lines) + "\n"


def write_route_kml(route: SeaRoute | SequenceSeaRoute, path: str | Path) -> None:
    """Write a sea route to a KML file on disk."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_kml_string(route), encoding="utf-8")
