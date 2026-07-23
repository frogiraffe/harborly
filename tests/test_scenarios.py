"""End to end validation of the three usage scenarios sea-mile targets.

An analyst cleaning a large name list, a developer embedding search and routing,
and a researcher building a reproducible distance matrix. These lock the public
surface each persona relies on before the 1.0 freeze.
"""

from __future__ import annotations

import pandas as pd
import pytest

from sea_mile import PortRegistry, SeaRouter

_PORTS = [
    ("WPI:1", "1", "TR", "Mersin", 36.8, 34.65, "TRMER"),
    ("WPI:2", "2", "GR", "Piraeus", 37.94, 23.63, "GRPIR"),
    ("WPI:3", "3", "TR", "Istanbul", 41.0, 28.97, "TRIST"),
    ("WPI:4", "4", "NL", "Rotterdam", 51.95, 4.14, "NLRTM"),
    ("WPI:5", "5", "SG", "Singapore", 1.26, 103.83, "SGSIN"),
]


def _registry() -> PortRegistry:
    records = pd.DataFrame(
        [
            {
                "registry_id": rid,
                "provider": "NGA_WPI",
                "provider_id": pid,
                "country_code": country,
                "canonical_name": name,
                "latitude": lat,
                "longitude": lon,
                "unlocode": unlocode,
                "function_code": "port",
                "source_version": "test",
                "coordinate_resolution": "arc_second",
                "variant_count": 1,
                "coordinate_conflict": False,
            }
            for rid, pid, country, name, lat, lon, unlocode in _PORTS
        ]
    )
    aliases = pd.DataFrame(
        [
            {
                "registry_id": rid,
                "provider": "NGA_WPI",
                "alias": name,
                "alias_key": name.lower(),
                "alias_type": "primary",
            }
            for rid, pid, country, name, lat, lon, unlocode in _PORTS
        ]
    )
    return PortRegistry(records, aliases)


def test_analyst_bulk_match_enriches_every_row_and_repeats() -> None:
    registry = _registry()
    clean = ["Mersin", "piraeus", "ISTANBUL", "Rotterdam", "Singapore"]
    noise = ["Nowhere Port", "Zzz Unknown"]
    names = (clean + noise) * 300
    frame = pd.DataFrame({"row_id": range(len(names)), "port_name": names})

    enriched = registry.match_dataframe(frame, name_column="port_name")

    assert len(enriched) == len(frame)
    for column in (
        "sea_mile_status",
        "sea_mile_reason_code",
        "sea_mile_registry_id",
        "sea_mile_name",
        "sea_mile_country_code",
        "sea_mile_latitude",
        "sea_mile_longitude",
        "sea_mile_unlocode",
    ):
        assert column in enriched.columns

    mersin = enriched[enriched["port_name"] == "Mersin"]
    assert (mersin["sea_mile_registry_id"] != "").all()
    assert (mersin["sea_mile_name"] == "Mersin").all()

    unknown = enriched[enriched["port_name"] == "Zzz Unknown"]
    assert (unknown["sea_mile_status"] == "unresolved").all()
    assert (unknown["sea_mile_registry_id"] == "").all()

    again = registry.match_dataframe(frame, name_column="port_name")
    pd.testing.assert_frame_equal(enriched, again)


def test_developer_embeds_search_resolve_and_route() -> None:
    pytest.importorskip("searoute")
    registry = _registry()

    groups = registry.search_grouped("Mersin", country_code="TR")
    assert groups
    assert groups[0].name == "Mersin"

    origin = registry.resolve("TRMER")
    destination = registry.resolve("GRPIR")
    route = SeaRouter().route(origin, destination)

    assert route.distance_nmi >= route.great_circle_nmi
    assert str(route.quality_flag)
    feature = route.to_geojson_feature()
    assert feature["type"] == "Feature"
    assert feature["properties"]["routing_units"] == "nautical_miles"


def test_researcher_builds_a_reproducible_distance_matrix() -> None:
    pytest.importorskip("searoute")
    registry = _registry()
    ports = [registry.resolve(code) for code in ("TRMER", "GRPIR", "NLRTM")]

    first = SeaRouter().distance_matrix(ports)
    second = SeaRouter().distance_matrix(ports)

    size = len(ports)
    assert len(first) == size
    assert all(len(row) == size for row in first)
    for i in range(size):
        assert first[i][i] == 0.0
        for j in range(size):
            assert first[i][j] == first[j][i]
    assert first == second
