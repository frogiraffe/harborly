"""GeoParquet export utilities for ports and sea routes using pyarrow."""

from __future__ import annotations

import json
import struct
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sea_mile.ports import Port
    from sea_mile.router import SeaRoute, SequenceSeaRoute

# GeoParquet 1.0.0 spec: omitting "crs" means OGC:CRS84 (lon/lat WGS84).
# We include null explicitly so readers don't have to guess.
_GEO_CRS: None = None


def _point_to_wkb(longitude: float, latitude: float) -> bytes:
    """Pack longitude and latitude into OGC WKB Point binary format (little-endian)."""
    return struct.pack("<BIdd", 1, 1, float(longitude), float(latitude))


def _linestring_to_wkb(coordinates: list[tuple[float, float]]) -> bytes:
    """Pack coordinate list into OGC WKB LineString binary format (little-endian).

    Requires at least 2 points (OGC Simple Features constraint).
    """
    if len(coordinates) < 2:
        raise ValueError(
            f"A LineString WKB requires at least 2 points; got {len(coordinates)}"
        )
    header = struct.pack("<BII", 1, 2, len(coordinates))
    pts = b"".join(
        struct.pack("<dd", float(lon), float(lat)) for lon, lat in coordinates
    )
    return header + pts


def _multilinestring_to_wkb(lines: list[list[tuple[float, float]]]) -> bytes:
    """Pack multiple coordinate lists into OGC WKB MultiLineString (little-endian)."""
    # Header: byte-order + WKB type 5 + num_geometries
    header = struct.pack("<BII", 1, 5, len(lines))
    parts = [header]
    for coords in lines:
        parts.append(_linestring_to_wkb(coords))
    return b"".join(parts)


def _extract_lines(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Return a list of coordinate rings from a GeoJSON geometry.

    Returns a list of line-lists so callers can preserve MultiLineString
    segment boundaries rather than flattening them into a single LineString.
    """
    gtype = geometry.get("type", "")
    raw_coords = geometry.get("coordinates", [])

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
            if len(seg_pts) >= 2:
                result.append(seg_pts)
        return result

    return []


def _extract_coordinates(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    """Flatten all lines from a GeoJSON geometry into a single coordinate list.

    Suitable for use where a single LineString is expected and MultiLineString
    segments can be safely concatenated (e.g., for KML export).
    """
    return [pt for line in _extract_lines(geometry) for pt in line]


def _geometry_to_wkb(geometry: dict[str, Any]) -> bytes | None:
    """Convert a GeoJSON geometry dict to an OGC WKB bytes value.

    Preserves MultiLineString topology by encoding as WKB MultiLineString
    when multiple segments are present. Returns None for empty/invalid geometry.
    """
    lines = _extract_lines(geometry)
    if not lines:
        return None
    if len(lines) == 1:
        coords = lines[0]
        if len(coords) < 2:
            return None
        return _linestring_to_wkb(coords)
    return _multilinestring_to_wkb(lines)


def _pyarrow_imports() -> tuple[Any, Any]:
    """Import pyarrow with a descriptive error if not installed."""
    try:
        import pyarrow as pa  # type: ignore[import-untyped]
        import pyarrow.parquet as pq  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "The 'pyarrow' package is required for GeoParquet export. "
            "Install it with: pip install pyarrow"
        ) from exc
    return pa, pq


def write_ports_geoparquet(ports: Sequence[Port], path: str | Path) -> None:
    """Export port records as a GeoParquet file."""
    pa, pq = _pyarrow_imports()

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for port in ports:
        geometry = (
            _point_to_wkb(port.longitude, port.latitude)
            if port.latitude is not None and port.longitude is not None
            else None
        )
        rows.append(
            {
                "registry_id": port.registry_id,
                "name": port.name,
                "country_code": port.country_code,
                "unlocode": port.unlocode or "",
                "latitude": port.latitude,
                "longitude": port.longitude,
                "provider": port.provider,
                "geometry": geometry,
            }
        )

    # Explicit schema prevents PyArrow from mistyping 'geometry' as null
    # when the first row has no coordinates.
    schema = pa.schema(
        [
            ("registry_id", pa.string()),
            ("name", pa.string()),
            ("country_code", pa.string()),
            ("unlocode", pa.string()),
            ("latitude", pa.float64()),
            ("longitude", pa.float64()),
            ("provider", pa.string()),
            ("geometry", pa.binary()),
        ]
    )
    table = pa.Table.from_pylist(rows, schema=schema)

    geo_metadata = {
        "version": "1.0.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "geometry_types": ["Point"],
                "crs": _GEO_CRS,
            }
        },
    }
    table = table.replace_schema_metadata(
        {b"geo": json.dumps(geo_metadata).encode("utf-8")}
    )
    pq.write_table(table, target)


def write_route_geoparquet(
    route: SeaRoute | SequenceSeaRoute, path: str | Path
) -> None:
    """Export a sea route or multi-leg sequence as a GeoParquet file."""
    from sea_mile.router import SequenceSeaRoute  # noqa: PLC0415

    pa, pq = _pyarrow_imports()

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    geometry_types: set[str] = set()

    if isinstance(route, SequenceSeaRoute):
        for idx, leg in enumerate(route.legs, start=1):
            wkb = _geometry_to_wkb(leg.geometry)
            if wkb is not None:
                gtype = leg.geometry.get("type", "LineString")
                geometry_types.add(
                    "MultiLineString" if gtype == "MultiLineString" else "LineString"
                )
            rows.append(
                {
                    "leg_number": idx,
                    "origin_id": leg.origin.registry_id,
                    "origin_name": leg.origin.name,
                    "destination_id": leg.destination.registry_id,
                    "destination_name": leg.destination.name,
                    "distance_nmi": leg.distance_nmi,
                    "great_circle_nmi": leg.great_circle_nmi,
                    "speed_knots": leg.speed_knots,
                    "duration_hours": leg.duration_hours,
                    "geometry": wkb,
                }
            )
    else:
        wkb = _geometry_to_wkb(route.geometry)
        if wkb is not None:
            gtype = route.geometry.get("type", "LineString")
            geometry_types.add(
                "MultiLineString" if gtype == "MultiLineString" else "LineString"
            )
        rows.append(
            {
                "leg_number": 1,
                "origin_id": route.origin.registry_id,
                "origin_name": route.origin.name,
                "destination_id": route.destination.registry_id,
                "destination_name": route.destination.name,
                "distance_nmi": route.distance_nmi,
                "great_circle_nmi": route.great_circle_nmi,
                "speed_knots": route.speed_knots,
                "duration_hours": route.duration_hours,
                "geometry": wkb,
            }
        )

    schema = pa.schema(
        [
            ("leg_number", pa.int32()),
            ("origin_id", pa.string()),
            ("origin_name", pa.string()),
            ("destination_id", pa.string()),
            ("destination_name", pa.string()),
            ("distance_nmi", pa.float64()),
            ("great_circle_nmi", pa.float64()),
            ("speed_knots", pa.float64()),
            ("duration_hours", pa.float64()),
            ("geometry", pa.binary()),
        ]
    )
    table = pa.Table.from_pylist(rows, schema=schema)

    geo_metadata = {
        "version": "1.0.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "geometry_types": sorted(geometry_types) or ["LineString"],
                "crs": _GEO_CRS,
            }
        },
    }
    table = table.replace_schema_metadata(
        {b"geo": json.dumps(geo_metadata).encode("utf-8")}
    )
    pq.write_table(table, target)
