from __future__ import annotations

import json

import pyarrow.parquet as pq

from sea_mile import SeaRouter
from sea_mile.geoparquet import write_ports_geoparquet, write_route_geoparquet
from sea_mile.ports import Port


def port(registry_id: str, name: str, latitude: float, longitude: float) -> Port:
    return Port(
        registry_id=registry_id,
        provider="TEST",
        provider_id=registry_id,
        country_code="TR",
        name=name,
        latitude=latitude,
        longitude=longitude,
        unlocode=None,
        function_code="port",
        source_version="test",
        coordinate_resolution="test",
    )


def port_no_coords(registry_id: str, name: str) -> Port:
    return Port(
        registry_id=registry_id,
        provider="TEST",
        provider_id=registry_id,
        country_code="TR",
        name=name,
        latitude=None,
        longitude=None,
        unlocode=None,
        function_code="port",
        source_version="test",
        coordinate_resolution="test",
    )


def test_write_ports_geoparquet(tmp_path) -> None:
    p1 = port("TEST:1", "Mersin", 36.8, 34.65)
    p2 = port("TEST:2", "Piraeus", 37.94, 23.63)

    output = tmp_path / "ports.geoparquet"
    write_ports_geoparquet([p1, p2], output)

    assert output.is_file()
    table = pq.read_table(output)
    assert len(table) == 2
    assert b"geo" in table.schema.metadata
    assert "geometry" in table.column_names


def test_write_ports_geoparquet_null_coords(tmp_path) -> None:
    """Ports with missing coordinates produce null geometry rows without crashing."""
    p_with = port("TEST:1", "Mersin", 36.8, 34.65)
    p_without = port_no_coords("TEST:2", "Unknown Port")

    output = tmp_path / "ports_mixed.geoparquet"
    # Must not crash even though first row has valid geometry and second has None
    write_ports_geoparquet([p_without, p_with], output)

    table = pq.read_table(output)
    assert len(table) == 2
    assert table["geometry"][0].as_py() is None  # no-coord port → null
    assert table["geometry"][1].as_py() is not None  # valid port → WKB bytes


def test_write_route_geoparquet(tmp_path) -> None:
    p1 = port("TEST:1", "Mersin", 36.8, 34.65)
    p2 = port("TEST:2", "Piraeus", 37.94, 23.63)

    route = SeaRouter().route(p1, p2, speed_knots=14.0)
    output = tmp_path / "route.geoparquet"
    write_route_geoparquet(route, output)

    assert output.is_file()
    table = pq.read_table(output)
    assert len(table) == 1
    assert b"geo" in table.schema.metadata
    assert "distance_nmi" in table.column_names
    assert "speed_knots" in table.column_names

    geo = json.loads(table.schema.metadata[b"geo"])
    # GeoParquet spec: null CRS means OGC:CRS84 (lon/lat WGS84) — do NOT expect
    # a full PROJJSON object here; a partial one would be rejected by GIS readers.
    assert geo["columns"]["geometry"]["crs"] is None


def test_write_sequence_route_geoparquet(tmp_path) -> None:
    """Multi-leg SequenceSeaRoute exports one row per leg."""
    p1 = port("TEST:1", "Mersin", 36.8, 34.65)
    p2 = port("TEST:2", "Piraeus", 37.94, 23.63)
    p3 = port("TEST:3", "Istanbul", 41.0, 28.97)

    seq = SeaRouter().route_sequence([p1, p2, p3], speed_knots=13.0)
    output = tmp_path / "seq.geoparquet"
    write_route_geoparquet(seq, output)

    table = pq.read_table(output)
    assert len(table) == 2  # 3 ports → 2 legs
    assert "leg_number" in table.column_names
    assert table["leg_number"].to_pylist() == [1, 2]
    assert "speed_knots" in table.column_names
