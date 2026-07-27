from __future__ import annotations

import pytest

pytest.importorskip("folium", reason="tests the optional 'map' extra")

from sea_mile.coordinates import LonLat  # noqa: E402
from sea_mile.html_map import (  # noqa: E402
    _route_locations,
    _route_lon_lat,
    write_route_html,
)
from sea_mile.ports import Port  # noqa: E402
from sea_mile.router import SeaRoute  # noqa: E402
from sea_mile.routing import RouteQualityFlag  # noqa: E402


def _port(registry_id: str, name: str, latitude: float, longitude: float) -> Port:
    return Port(
        registry_id=registry_id,
        provider="TEST",
        provider_id=registry_id,
        country_code="ZZ",
        name=name,
        latitude=latitude,
        longitude=longitude,
        unlocode=None,
        function_code="port",
        source_version="test",
        coordinate_resolution="test",
    )


def _route() -> SeaRoute:
    origin = _port("TEST:1", "Mersin", 36.8, 34.65)
    destination = _port("TEST:2", "Piraeus", 37.94, 23.63)
    return SeaRoute(
        origin=origin,
        destination=destination,
        distance_nmi=412.5,
        great_circle_nmi=400.0,
        detour_ratio=1.03125,
        quality_flag=RouteQualityFlag.OK,
        geometry={
            "type": "LineString",
            "coordinates": [[34.65, 36.8], [23.63, 37.94]],
        },
        engine="test",
        engine_version="1",
        algorithm="astar",
        backend="test",
        restrictions=(),
    )


def test_route_coordinates_are_extracted_as_lon_lat() -> None:
    assert _route_lon_lat(_route()) == (
        LonLat(longitude=34.65, latitude=36.8),
        LonLat(longitude=23.63, latitude=37.94),
    )


def test_route_locations_unwrap_the_antimeridian() -> None:
    points = (
        LonLat(longitude=179.0, latitude=10.0),
        LonLat(longitude=-179.0, latitude=11.0),
        LonLat(longitude=-175.0, latitude=12.0),
    )

    assert _route_locations(points) == (
        (10.0, 179.0),
        (11.0, 181.0),
        (12.0, 185.0),
    )


def test_route_html_writes_an_interactive_map(tmp_path) -> None:
    output = tmp_path / "maps" / "route.html"

    write_route_html(_route(), output)

    html = output.read_text(encoding="utf-8")
    assert "leaflet" in html.lower()
    assert "412.50 nautical miles" in html
    assert "Mersin" in html
    assert "Piraeus" in html
    assert "Natural Earth 110m coastline" in html
    assert 'window.location.protocol === "http:"' in html
    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in html
    assert "Embedded coastline preview" in html
    assert ".removeLayer(" in html


def test_route_html_has_no_unconditional_remote_tile_layer(tmp_path) -> None:
    output = tmp_path / "route.html"

    write_route_html(_route(), output)

    html = output.read_text(encoding="utf-8")
    protocol_check = html.index('window.location.protocol === "http:"')
    fallback_removal = html.index(".removeLayer(")
    tile_layer = html.index("https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    fallback = html.index("Embedded coastline preview")
    assert protocol_check < fallback_removal < tile_layer < fallback
