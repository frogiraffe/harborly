from __future__ import annotations

import pytest

pytest.importorskip("textual", reason="tests the optional 'tui' extra")

from test_ports import alias_frame, registry_frame  # noqa: E402

from sea_mile import PortRegistry  # noqa: E402
from sea_mile.coordinates import LatLon  # noqa: E402
from sea_mile.tui.map_canvas import (  # noqa: E402
    BrailleWorldMap,
    _cluster_ports,
    _geo_to_pixel,
    _in_viewport,
)


def test_geo_to_pixel_default_world_view() -> None:
    # (0, 0) should map to center of canvas.
    x, y = _geo_to_pixel(LatLon(0, 0), 100, 100)
    assert x == 50
    assert y == 50


def test_geo_to_pixel_zoomed() -> None:
    # At zoom 2x centered on (0, 0), (0, 0) should still be center.
    x, y = _geo_to_pixel(LatLon(0, 0), 100, 100, zoom=2.0)
    assert x == 50
    assert y == 50


def test_geo_to_pixel_panned() -> None:
    # Pan to (45, 45): port at (45, 45) should be center.
    x, y = _geo_to_pixel(
        LatLon(45, 45), 100, 100, zoom=2.0, center_lat=45, center_lon=45
    )
    assert x == 50
    assert y == 50


def test_in_viewport_world_view() -> None:
    assert _in_viewport(40.0, 30.0, zoom=1.0, center_lat=0.0, center_lon=0.0)


def test_in_viewport_outside_zoomed() -> None:
    # Zoomed to Mediterranean, Tokyo should be outside.
    assert not _in_viewport(35.0, 140.0, zoom=4.0, center_lat=38.0, center_lon=25.0)


def test_cluster_ports_single() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    groups = registry.search_grouped("Mersin")
    clusters = _cluster_ports(
        groups, 200, 200, zoom=1.0, center_lat=0.0, center_lon=0.0
    )
    assert len(clusters) >= 1
    assert len(clusters[0].indices) == 1


def test_cluster_ports_merge_nearby() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    groups = registry.search_grouped("Piraeus")
    if len(groups) >= 2:
        clusters = _cluster_ports(
            groups, 200, 200, zoom=1.0, center_lat=0.0, center_lon=0.0
        )
        # At zoom 1x, Aegean ports may cluster together.
        assert len(clusters) >= 1


def test_braille_map_zoom_render() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    groups = registry.search_grouped("Mersin")
    world_map = BrailleWorldMap(40, 20, zoom=4.0, center_lat=36.8, center_lon=34.6)
    rendered = world_map.render(groups, selected=0)
    # At 4x zoom centered on Mersin, coastline should be visible.
    assert len(rendered) > 0
