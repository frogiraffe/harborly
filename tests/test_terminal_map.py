from __future__ import annotations

import pytest

pytest.importorskip("plotext", reason="tests the optional 'tui' extra")

from test_ports import alias_frame, registry_frame  # noqa: E402

from sea_mile import PortRegistry  # noqa: E402
from sea_mile.coordinates import LonLat  # noqa: E402
from sea_mile.terminal_map import _group_lon_lat, render_port_map  # noqa: E402


def test_group_coordinates_use_lon_lat_contract() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    group = registry.search_grouped("GRPIR")[0]

    assert _group_lon_lat(group) == LonLat(longitude=23.63, latitude=37.94)


def test_terminal_map_renders_search_coordinates() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    groups = registry.search_grouped("Piraeus")

    rendered = render_port_map(groups, selected=0)

    assert "Search result coordinates" in rendered
    assert "longitude" in rendered
    assert "latitude" in rendered
