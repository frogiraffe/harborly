from __future__ import annotations

from xml.etree import ElementTree

from harborly import RouteQualityFlag, SeaRoute, SeaRouter
from harborly.kml import to_kml_string, write_route_kml
from harborly.ports import Port


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


def test_kml_escapes_labels_and_preserves_multiline_topology() -> None:
    origin = port("TEST:1", "Port & <Alpha>", 36.8, 34.65)
    destination = port("TEST:2", "Port > Beta", 37.94, 23.63)
    route = SeaRoute(
        origin=origin,
        destination=destination,
        distance_nmi=100.0,
        great_circle_nmi=90.0,
        detour_ratio=1.11,
        quality_flag=RouteQualityFlag.OK,
        geometry={
            "type": "MultiLineString",
            "coordinates": [
                [[34.65, 36.8], [30.0, 37.0]],
                [[29.0, 37.2], [23.63, 37.94]],
            ],
        },
        engine="test",
        engine_version="1",
        algorithm="test",
        backend="test",
        restrictions=(),
    )

    kml_text = route.to_kml()
    root = ElementTree.fromstring(kml_text)
    namespace = {"kml": "http://www.opengis.net/kml/2.2"}
    lines = root.findall(".//kml:MultiGeometry/kml:LineString", namespace)

    assert "Port &amp; &lt;Alpha&gt; to Port &gt; Beta" in kml_text
    assert len(lines) == 2
    coordinates = [
        line.findtext("kml:coordinates", namespaces=namespace) for line in lines
    ]
    assert coordinates == [
        "34.65,36.8,0 30.0,37.0,0",
        "29.0,37.2,0 23.63,37.94,0",
    ]
