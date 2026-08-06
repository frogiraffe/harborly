from __future__ import annotations

from sea_mile import SeaRouter
from sea_mile.kml import to_kml_string, write_route_kml
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


def test_kml_route_string_generation() -> None:
    origin = port("TEST:1", "Mersin", 36.8, 34.65)
    destination = port("TEST:2", "Piraeus", 37.94, 23.63)

    route = SeaRouter().route(origin, destination)
    kml_text = to_kml_string(route)

    assert "<?xml" in kml_text
    assert "<kml" in kml_text
    assert "<Placemark>" in kml_text
    assert "<LineString>" in kml_text
    assert "<coordinates>" in kml_text
    assert route.to_kml() == kml_text


def test_kml_route_file_writing(tmp_path) -> None:
    origin = port("TEST:1", "Mersin", 36.8, 34.65)
    destination = port("TEST:2", "Piraeus", 37.94, 23.63)

    route = SeaRouter().route(origin, destination)
    output = tmp_path / "route.kml"
    write_route_kml(route, output)

    assert output.is_file()
    assert "<LineString>" in output.read_text(encoding="utf-8")


def test_kml_sequence_string_generation() -> None:
    port_a = port("TEST:1", "Mersin", 36.8, 34.65)
    port_b = port("TEST:2", "Piraeus", 37.94, 23.63)
    port_c = port("TEST:3", "Istanbul", 41.0, 28.97)

    seq = SeaRouter().route_sequence([port_a, port_b, port_c])
    kml_text = seq.to_kml()

    assert "<name>Leg 1: Mersin to Piraeus</name>" in kml_text
    assert "<name>Leg 2: Piraeus to Istanbul</name>" in kml_text
