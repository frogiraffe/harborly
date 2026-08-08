from __future__ import annotations

import csv
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd
import pyarrow.parquet as pq
import pytest

import harborly
from harborly.cli import main
from harborly.route_cache import RouteCache


def write_registry(directory, *, first_name: str = "Mersin") -> None:
    directory.mkdir()
    registry = pd.DataFrame(
        [
            {
                "registry_id": "WPI:1",
                "provider": "NGA_WPI",
                "provider_id": "1",
                "country_code": "TR",
                "canonical_name": first_name,
                "latitude": 36.8,
                "longitude": 34.65,
                "unlocode": "TRMER",
                "function_code": "port",
                "source_version": "test",
                "coordinate_resolution": "arc_second",
                "variant_count": 1,
                "coordinate_conflict": False,
            },
            {
                "registry_id": "WPI:2",
                "provider": "NGA_WPI",
                "provider_id": "2",
                "country_code": "GR",
                "canonical_name": "Piraeus",
                "latitude": 37.94,
                "longitude": 23.63,
                "unlocode": "GRPIR",
                "function_code": "port",
                "source_version": "test",
                "coordinate_resolution": "arc_second",
                "variant_count": 1,
                "coordinate_conflict": False,
            },
        ]
    )
    aliases = pd.DataFrame(
        [
            {
                "registry_id": "WPI:1",
                "provider": "NGA_WPI",
                "alias": "Mersin",
                "alias_key": "mersin",
                "alias_type": "primary",
            },
            {
                "registry_id": "WPI:2",
                "provider": "NGA_WPI",
                "alias": "Piraeus",
                "alias_key": "piraeus",
                "alias_type": "primary",
            },
        ]
    )
    registry.to_parquet(directory / "port_registry.parquet", index=False)
    aliases.to_parquet(directory / "port_aliases.parquet", index=False)


def write_ambiguous_registry(directory) -> None:
    directory.mkdir()
    registry = pd.DataFrame(
        [
            {
                "registry_id": "WPI:2",
                "provider": "NGA_WPI",
                "provider_id": "2",
                "country_code": "US",
                "canonical_name": "Hamilton",
                "latitude": 39.4,
                "longitude": -84.6,
                "unlocode": None,
                "function_code": "port",
                "source_version": "test",
                "coordinate_resolution": "arc_second",
                "variant_count": 1,
                "coordinate_conflict": False,
            },
            {
                "registry_id": "UNLOCODE:USHAM",
                "provider": "UN_LOCODE",
                "provider_id": "USHAM",
                "country_code": "US",
                "canonical_name": "Hamilton",
                "latitude": 43.9,
                "longitude": -75.5,
                "unlocode": "USHAM",
                "function_code": "1-----",
                "source_version": "test",
                "coordinate_resolution": "arc_minute",
                "variant_count": 1,
                "coordinate_conflict": False,
            },
        ]
    )
    aliases = pd.DataFrame(
        [
            {
                "registry_id": "WPI:2",
                "provider": "NGA_WPI",
                "alias": "Hamilton",
                "alias_key": "hamilton",
                "alias_type": "primary",
            },
            {
                "registry_id": "UNLOCODE:USHAM",
                "provider": "UN_LOCODE",
                "alias": "Hamilton",
                "alias_key": "hamilton",
                "alias_type": "primary",
            },
        ]
    )
    registry.to_parquet(directory / "port_registry.parquet", index=False)
    aliases.to_parquet(directory / "port_aliases.parquet", index=False)


def test_info_and_search_emit_machine_readable_json(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    assert main(["--data-dir", str(data_directory), "info", "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["schema_version"] == "1"
    assert info["command"] == "info"
    assert info["warnings"] == []
    assert info["data"]["registry_records"] == 2

    assert (
        main(
            [
                "--data-dir",
                str(data_directory),
                "search",
                "Mersin",
                "--country",
                "TR",
                "--json",
            ]
        )
        == 0
    )
    results = json.loads(capsys.readouterr().out)["data"]
    assert results[0]["best_id"] == "WPI:1"
    assert results[0]["sources"] == ["NGA_WPI"]

    assert (
        main(
            [
                "--data-dir",
                str(data_directory),
                "near",
                "36.81",
                "34.65",
                "--country",
                "TR",
                "--limit",
                "1",
                "--json",
            ]
        )
        == 0
    )
    nearest = json.loads(capsys.readouterr().out)["data"]
    assert nearest[0]["best_id"] == "WPI:1"
    assert "distance_nmi" in nearest[0]


def test_harborly_data_dir_selects_the_cli_registry(
    tmp_path, monkeypatch, capsys
) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    monkeypatch.setenv("HARBORLY_DATA_DIR", str(data_directory))

    assert main(["info", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["data"]["registry_records"] == 2


def test_search_prints_grouped_table_by_default(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    assert main(["--data-dir", str(data_directory), "search", "Mersin"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["NAME", "COUNTRY", "UNLOCODE", "SOURCES", "COORD", "ID"]
    row = lines[1]
    for cell in ("Mersin", "TR", "TRMER", "WPI", "WPI:1"):
        assert cell in row


def test_search_all_sources_prints_per_source_rows(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    assert (
        main(["--data-dir", str(data_directory), "search", "Mersin", "--all-sources"])
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["NAME", "COUNTRY", "PROVIDER", "METHOD", "SCORE", "ID"]
    assert lines[1].split() == [
        "Mersin",
        "TR",
        "NGA_WPI",
        "exact_alias",
        "100",
        "WPI:1",
    ]


def test_search_without_matches_prints_no_matches(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    assert main(["--data-dir", str(data_directory), "search", "Atlantis"]) == 0
    assert capsys.readouterr().out.strip() == "no matches"


def test_show_prints_readable_port_record(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    assert main(["--data-dir", str(data_directory), "show", "TRMER"]) == 0
    out = capsys.readouterr().out
    assert "name: Mersin" in out
    assert "registry_id: WPI:1" in out
    assert "unlocode: TRMER" in out
    assert "coordinates: 36.8000, 34.6500" in out


def test_route_prints_readable_summary_by_default(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    assert main(["--data-dir", str(data_directory), "route", "TRMER", "GRPIR"]) == 0
    out = capsys.readouterr().out
    assert "origin: Mersin (WPI:1)" in out
    assert "destination: Piraeus (WPI:2)" in out
    assert "distance_nmi: " in out
    assert "quality_flag: " in out


def test_route_can_write_geojson(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    output = tmp_path / "route.geojson"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "route",
            "TRMER",
            "GRPIR",
            "--geojson",
            str(output),
            "--json",
        ]
    )

    assert status == 0
    summary = json.loads(capsys.readouterr().out)["data"]
    feature = json.loads(output.read_text())
    assert summary["distance_nmi"] > 0
    assert feature["properties"]["routing_units"] == "nautical_miles"


def test_route_can_write_parseable_kml(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    output = tmp_path / "route.kml"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "route",
            "TRMER",
            "GRPIR",
            "--kml",
            str(output),
        ]
    )

    root = ElementTree.parse(output).getroot()
    namespace = {"kml": "http://www.opengis.net/kml/2.2"}
    assert status == 0
    assert root.find(".//kml:LineString/kml:coordinates", namespace) is not None
    assert "distance_nmi:" in capsys.readouterr().out


def test_route_can_write_html_map(tmp_path, capsys) -> None:
    pytest.importorskip("folium", reason="HTML maps need the map extra")
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    output = tmp_path / "route.html"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "route",
            "TRMER",
            "GRPIR",
            "--html-map",
            str(output),
        ]
    )

    assert status == 0
    output_text = capsys.readouterr().out
    assert "html_map:" in output_text
    assert "direct file viewing uses an embedded coastline" in output_text
    assert "leaflet" in output.read_text(encoding="utf-8").lower()


def test_route_html_map_reports_missing_extra(tmp_path, capsys, monkeypatch) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    monkeypatch.setitem(sys.modules, "harborly.html_map", None)
    monkeypatch.setattr(
        "harborly.router.SeaRouter.route",
        lambda *args, **kwargs: pytest.fail("route should not be calculated"),
    )
    geojson = tmp_path / "route.geojson"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "route",
            "TRMER",
            "GRPIR",
            "--html-map",
            str(tmp_path / "route.html"),
            "--geojson",
            str(geojson),
            "--json",
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "harborly[routing,map]" in captured.err
    assert "uv tool install --force" in captured.err
    assert "uv run harborly" in captured.err
    assert not geojson.exists()


def test_route_html_map_preflight_keeps_required_extras_together(
    tmp_path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(
        "harborly.cli._module_available",
        lambda module: module == "searoute",
    )
    monkeypatch.setattr(
        "harborly.cli._load_registry",
        lambda args: pytest.fail(f"registry should not load: {args}"),
    )

    status = main(
        [
            "route",
            "TRMER",
            "GRPIR",
            "--html-map",
            str(tmp_path / "route.html"),
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    assert "harborly[routing,map]" in captured.err
    assert "--extra routing --extra map" in captured.err


def test_route_rejects_relative_aliases_for_duplicate_exports(
    tmp_path, capsys, monkeypatch
) -> None:
    output = tmp_path / "route.out"
    output.write_text("existing route", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "harborly.cli._require_optional_extras",
        lambda *_args: pytest.fail("extras should not be checked"),
    )
    monkeypatch.setattr(
        "harborly.cli._load_registry",
        lambda _args: pytest.fail("registry should not load"),
    )

    assert (
        main(
            [
                "route",
                "A",
                "C",
                "--geojson",
                "route.out",
                "--kml",
                "./route.out",
            ]
        )
        == 2
    )

    assert "route output paths must be distinct" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "existing route"


def test_route_rejects_html_map_collision_before_routing(
    tmp_path, capsys, monkeypatch
) -> None:
    output = tmp_path / "route.out"
    output.write_text("existing route", encoding="utf-8")
    monkeypatch.setattr(
        "harborly.cli._require_optional_extras",
        lambda *_args: pytest.fail("extras should not be checked"),
    )
    monkeypatch.setattr(
        "harborly.cli._load_registry",
        lambda _args: pytest.fail("registry should not load"),
    )

    assert (
        main(
            [
                "route",
                "A",
                "C",
                "--geojson",
                str(output),
                "--html-map",
                str(tmp_path / "." / "route.out"),
            ]
        )
        == 2
    )

    assert "route output paths must be distinct" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "existing route"


def test_route_html_map_write_failure_does_not_emit_success(
    tmp_path, capsys, monkeypatch
) -> None:
    pytest.importorskip("folium", reason="HTML maps need the map extra")
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    def fail_write(*args, **kwargs) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr("harborly.html_map.write_route_html", fail_write)

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "route",
            "TRMER",
            "GRPIR",
            "--html-map",
            str(tmp_path / "route.html"),
            "--json",
        ]
    )

    assert status == 2
    payload = json.loads(capsys.readouterr().out)
    assert "data" not in payload
    assert "could not write HTML map" in payload["error"]["message"]


def test_serve_delegates_to_optional_api(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(
        "harborly.api.run_server",
        lambda *, host, port: calls.append((host, port)),
    )

    status = main(["serve", "--host", "0.0.0.0", "--port", "9000"])

    assert status == 0
    assert calls == [("0.0.0.0", 9000)]


def test_serve_reports_missing_extra(capsys, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "harborly.api", None)

    status = main(["serve"])

    assert status == 2
    captured = capsys.readouterr()
    assert "harborly[api,routing]" in captured.err
    assert "uv tool install --force" in captured.err


def test_serve_checks_routing_before_starting_server(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "harborly.cli._module_available",
        lambda module: module != "searoute",
    )
    monkeypatch.setattr(
        "harborly.api.run_server",
        lambda **kwargs: pytest.fail(f"server should not start: {kwargs}"),
    )

    status = main(["serve"])

    assert status == 2
    captured = capsys.readouterr()
    assert "harborly[api,routing]" in captured.err
    assert "--extra api --extra routing" in captured.err


def test_serve_rejects_out_of_range_port(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["serve", "--port", "65536"])

    assert caught.value.code == 2
    assert "range 0-65535" in capsys.readouterr().err


def test_tui_reports_missing_extra(tmp_path, capsys, monkeypatch) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    monkeypatch.delattr(harborly, "tui", raising=False)
    monkeypatch.setitem(sys.modules, "harborly.tui", None)

    status = main(["--data-dir", str(data_directory), "tui"])

    assert status == 2
    assert "harborly[tui]" in capsys.readouterr().err


def test_route_json_error_carries_a_stable_reason(
    tmp_path, capsys, monkeypatch
) -> None:
    from harborly.exceptions import RoutingError, RoutingErrorReason

    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    def boom(self, origin, destination):
        raise RoutingError(
            "backend blew up", reason=RoutingErrorReason.MALFORMED_BACKEND_RESULT
        )

    monkeypatch.setattr("harborly.router.SeaRouter.route", boom)
    status = main(
        ["--data-dir", str(data_directory), "route", "TRMER", "GRPIR", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 2
    assert payload["error"]["code"] == "routing_error"
    assert payload["error"]["details"] == {"reason": "malformed_backend_result"}


def test_match_resolves_names_from_csv(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    csv_path = tmp_path / "names.csv"
    csv_path.write_text("name,country\nMersin,TR\nAtlantis,TR\n", encoding="utf-8")

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "match",
            str(csv_path),
            "--country-column",
            "country",
            "--json",
        ]
    )

    assert status == 0
    results = {row["query"]: row for row in json.loads(capsys.readouterr().out)["data"]}
    assert results["Mersin"]["status"] == "auto_resolved"
    assert results["Mersin"]["selected_registry_id"] == "WPI:1"
    assert results["Mersin"]["reason_code"] == "unique_exact_wpi"
    assert results["Mersin"]["rules_applied"] == ["single_exact_wpi"]
    assert [c["registry_id"] for c in results["Mersin"]["candidates"]] == ["WPI:1"]
    assert results["Atlantis"]["status"] == "unresolved"
    assert results["Atlantis"]["reason_code"] == "no_candidate"
    assert results["Atlantis"]["rules_applied"] == ["no_official_candidate"]
    assert results["Atlantis"]["candidates"] == []


def test_match_reports_missing_name_column(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    csv_path = tmp_path / "names.csv"
    csv_path.write_text("port\nMersin\n", encoding="utf-8")

    status = main(["--data-dir", str(data_directory), "match", str(csv_path)])

    assert status == 2
    assert "no column 'name'" in capsys.readouterr().err


def test_near_rejects_a_port_name_instead_of_a_coordinate(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    with pytest.raises(SystemExit):
        main(["--data-dir", str(data_directory), "near", "mersin", "34.65"])
    stderr = capsys.readouterr().err
    assert "not a coordinate" in stderr
    assert "harborly search" in stderr


def test_near_grouped_table_by_default(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    assert main(["--data-dir", str(data_directory), "near", "36.8", "34.65"]) == 0
    header = capsys.readouterr().out.splitlines()[0].split()
    assert header == ["NAME", "COUNTRY", "UNLOCODE", "SOURCES", "DISTANCE_NMI", "ID"]


def test_export_csv_to_stdout(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "export",
            "--country",
            "TR",
            "--format",
            "csv",
        ]
    )
    out = capsys.readouterr().out

    assert status == 0
    assert out.splitlines()[0].startswith("registry_id,provider")
    assert "WPI:1" in out


def test_export_kml_writes_escaped_port_point(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory, first_name="Mersin & <Port>")
    output = tmp_path / "ports.kml"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "export",
            "--country",
            "TR",
            "--format",
            "kml",
            "--output",
            str(output),
        ]
    )

    root = ElementTree.parse(output).getroot()
    namespace = {"kml": "http://www.opengis.net/kml/2.2"}
    assert status == 0
    assert (
        root.findtext(".//kml:Placemark/kml:name", namespaces=namespace)
        == "Mersin & <Port>"
    )
    assert root.find(".//kml:Placemark/kml:Point", namespace) is not None
    assert "wrote 1 records" in capsys.readouterr().out


def test_export_geoparquet_writes_port_wkb(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    output = tmp_path / "ports.geoparquet"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "export",
            "--country",
            "TR",
            "--format",
            "geoparquet",
            "--output",
            str(output),
        ]
    )

    table = pq.read_table(output)
    geo = json.loads(table.schema.metadata[b"geo"])
    assert status == 0
    assert table["geometry"][0].as_py() is not None
    assert geo["columns"]["geometry"]["encoding"] == "WKB"
    assert "wrote 1 records" in capsys.readouterr().out


def test_export_needs_a_filter(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    assert main(["--data-dir", str(data_directory), "export"]) == 2
    assert "needs --query or --country" in capsys.readouterr().err


def test_matrix_reports_pairwise_distance(tmp_path, capsys) -> None:
    pytest.importorskip("searoute", reason="matrix needs the routing extra")
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    status = main(
        ["--data-dir", str(data_directory), "matrix", "TRMER", "GRPIR", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)["data"]

    assert status == 0
    assert payload["ports"] == ["WPI:1", "WPI:2"]
    assert payload["distances_nmi"][0][0] == 0.0
    assert payload["distances_nmi"][0][1] > 0


def test_matrix_streams_edges_to_csv(tmp_path, capsys) -> None:
    pytest.importorskip("searoute", reason="matrix needs the routing extra")
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    output = tmp_path / "edges.csv"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "matrix",
            "TRMER",
            "GRPIR",
            "--workers",
            "1",
            "--edge-csv",
            str(output),
        ]
    )

    assert status == 0
    assert "wrote 1 route edges" in capsys.readouterr().out
    with output.open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["origin"] == "WPI:1"
    assert rows[0]["destination"] == "WPI:2"
    assert float(rows[0]["distance_nmi"]) > 0


def test_matrix_edge_csv_rejects_json(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "matrix",
            "TRMER",
            "GRPIR",
            "--edge-csv",
            str(tmp_path / "edges.csv"),
            "--json",
        ]
    )

    assert status == 2
    assert "cannot be combined" in capsys.readouterr().out


def test_matrix_rejects_nonpositive_worker_count() -> None:
    with pytest.raises(SystemExit):
        main(["matrix", "TRMER", "GRPIR", "--workers", "0"])


def test_matrix_speed_adds_derived_duration_outputs(
    tmp_path, capsys, monkeypatch
) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    class FakeRouter:
        def __init__(self, **_kwargs) -> None:
            pass

        def distance_matrix(self, _ports, *, max_workers=None):
            return [[0.0, 10.0], [20.0, 0.0]]

        def iter_distance_edges(self, _ports, *, max_workers=None):
            yield 0, 1, 10.0
            yield 1, 0, 20.0

    monkeypatch.setattr("harborly.router.SeaRouter", FakeRouter)
    args = ["--data-dir", str(data_directory), "matrix", "TRMER", "GRPIR"]

    assert main([*args, "--speed-knots", "10", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)["data"]
    assert payload["speed_knots"] == 10.0
    assert payload["durations_hours"] == [[0.0, 1.0], [2.0, 0.0]]

    assert main([*args, "--speed-knots", "10"]) == 0
    text = capsys.readouterr().out
    assert "FROM/TO" in text
    assert "DURATION HOURS" in text
    assert "1.00" in text
    assert "2.00" in text

    output = tmp_path / "edges.csv"
    assert main([*args, "--speed-knots", "10", "--edge-csv", str(output)]) == 0
    with output.open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "origin": "WPI:1",
            "destination": "WPI:2",
            "distance_nmi": "10.0",
            "duration_hours": "1.0",
        },
        {
            "origin": "WPI:2",
            "destination": "WPI:1",
            "distance_nmi": "20.0",
            "duration_hours": "2.0",
        },
    ]


def test_matrix_without_speed_retains_legacy_json_schema(
    tmp_path, capsys, monkeypatch
) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    class FakeRouter:
        def __init__(self, **_kwargs) -> None:
            pass

        def distance_matrix(self, _ports, *, max_workers=None):
            return [[0.0, 10.0], [20.0, 0.0]]

    monkeypatch.setattr("harborly.router.SeaRouter", FakeRouter)

    assert (
        main(["--data-dir", str(data_directory), "matrix", "TRMER", "GRPIR", "--json"])
        == 0
    )
    assert set(json.loads(capsys.readouterr().out)["data"]) == {
        "ports",
        "distances_nmi",
    }


def test_cache_info_and_clear_support_json(tmp_path, capsys) -> None:
    cache_path = tmp_path / "routes.sqlite3"
    RouteCache(cache_path)

    assert main(["cache", "info", str(cache_path), "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["command"] == "cache info"
    assert info["data"]["schema_version"] == 1
    assert info["data"]["entries"] == 0

    with closing(sqlite3.connect(cache_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO routes (cache_key, distance_nmi, geometry_json)
            VALUES (?, ?, ?)
            """,
            (
                "test",
                1.0,
                '{"type":"LineString","coordinates":[[0,0],[1,1]]}',
            ),
        )

    assert main(["cache", "clear", str(cache_path), "--json"]) == 0
    cleared = json.loads(capsys.readouterr().out)
    assert cleared["command"] == "cache clear"
    assert cleared["data"]["removed_entries"] == 1
    assert cleared["data"]["entries"] == 0


def test_cache_prune_requires_positive_retention(tmp_path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "cache",
                "prune",
                str(tmp_path / "routes.sqlite3"),
                "--older-than-days",
                "0",
            ]
        )


def test_cache_info_rejects_a_missing_file(tmp_path, capsys) -> None:
    status = main(["cache", "info", str(tmp_path / "missing.sqlite3")])

    assert status == 2
    assert "does not exist" in capsys.readouterr().err


def test_data_build_reports_missing_sources_without_loading_registry(
    tmp_path, capsys
) -> None:
    status = main(["data", "build", "--reference-root", str(tmp_path / "reference")])

    assert status == 2
    assert "run data download first" in capsys.readouterr().err


def test_data_prepare_json_is_one_valid_document(tmp_path, capsys, monkeypatch) -> None:
    download_manifest = {"retrieved_at_utc": "test", "sources": {}}
    build_manifest = {"registry_rows": 2, "providers": {}}
    monkeypatch.setattr(
        "harborly.build.download.download_reference_data",
        lambda *args, **kwargs: download_manifest,
    )
    monkeypatch.setattr(
        "harborly.build.registry.build_reference_registry",
        lambda *args, **kwargs: build_manifest,
    )

    status = main(["data", "prepare", "--reference-root", str(tmp_path), "--json"])

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "data prepare"
    assert payload["data"] == {"download": download_manifest, "build": build_manifest}


def test_data_download_json_keeps_flat_manifest_shape(
    tmp_path, capsys, monkeypatch
) -> None:
    download_manifest = {"retrieved_at_utc": "test", "sources": {}}
    monkeypatch.setattr(
        "harborly.build.download.download_reference_data",
        lambda *args, **kwargs: download_manifest,
    )

    status = main(["data", "download", "--reference-root", str(tmp_path), "--json"])

    assert status == 0
    assert json.loads(capsys.readouterr().out)["data"] == download_manifest


@pytest.mark.parametrize("command", [["export", "--country", "TR"], ["tui"]])
def test_non_json_commands_reject_the_json_flag(tmp_path, command) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    with pytest.raises(SystemExit):
        main(["--data-dir", str(data_directory), *command, "--json"])


def test_matrix_requires_two_or_more_ports(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    status = main(["--data-dir", str(data_directory), "matrix", "TRMER"])

    assert status == 2
    assert "two or more ports" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("command", "returns_list"),
    [
        (["info"], False),
        (["search", "Mersin"], True),
        (["show", "TRMER"], False),
        (["near", "36.8", "34.65"], True),
    ],
)
def test_json_commands_emit_one_valid_document(
    tmp_path, capsys, command, returns_list
) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    status = main(["--data-dir", str(data_directory), *command, "--json"])

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1"
    assert payload["warnings"] == []
    assert isinstance(payload["data"], list if returns_list else dict)


def test_match_output_enriches_input_and_preserves_columns(tmp_path) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    input_csv = tmp_path / "in.csv"
    input_csv.write_text("port_name,ref\nMersin,X-1\n", encoding="utf-8")
    output_csv = tmp_path / "out.csv"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "match",
            str(input_csv),
            "--name-column",
            "port_name",
            "--output",
            str(output_csv),
        ]
    )

    assert status == 0
    with output_csv.open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["ref"] == "X-1"
    assert row["port_name"] == "Mersin"
    assert row["harborly_status"] == "auto_resolved"
    assert row["harborly_registry_id"] == "WPI:1"
    assert row["harborly_name"] == "Mersin"


def test_match_review_writes_one_row_per_candidate(tmp_path) -> None:
    data_directory = tmp_path / "registry"
    write_ambiguous_registry(data_directory)
    input_csv = tmp_path / "in.csv"
    input_csv.write_text("row_id,port_name,country\n7,Hamilton,US\n", encoding="utf-8")
    review_csv = tmp_path / "review.csv"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "match",
            str(input_csv),
            "--name-column",
            "port_name",
            "--country-column",
            "country",
            "--id-column",
            "row_id",
            "--review",
            str(review_csv),
        ]
    )

    assert status == 0
    with review_csv.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["candidate_registry_id"] for row in rows] == ["WPI:2", "UNLOCODE:USHAM"]
    assert all(row["row_id"] == "7" for row in rows)
    assert all(row["reason_code"] == "coordinate_conflict" for row in rows)
    # A reviewer must be able to tell an exact hit from a fuzzy suggestion.
    assert all(row["candidate_match_method"] == "exact_alias" for row in rows)
    assert all(row["candidate_name_score"] == "100.0" for row in rows)


@pytest.mark.parametrize(
    "rows",
    [
        "row_id,port_name\n,Mersin\n",
        "row_id,port_name\n01024,Mersin\n01024,Mersin\n",
    ],
)
def test_match_rejects_missing_or_duplicate_explicit_ids(
    tmp_path, capsys, rows
) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    input_csv = tmp_path / "in.csv"
    input_csv.write_text(rows, encoding="utf-8")
    output_csv = tmp_path / "out.csv"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "match",
            str(input_csv),
            "--id-column",
            "row_id",
            "--output",
            str(output_csv),
        ]
    )

    assert status == 2
    assert not output_csv.exists()
    assert "row_id" in capsys.readouterr().err


def test_match_preserves_leading_zero_explicit_ids(tmp_path) -> None:
    data_directory = tmp_path / "registry"
    write_ambiguous_registry(data_directory)
    input_csv = tmp_path / "in.csv"
    input_csv.write_text(
        "row_id,port_name,country\n01024,Hamilton,US\n", encoding="utf-8"
    )
    review_csv = tmp_path / "review.csv"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "match",
            str(input_csv),
            "--name-column",
            "port_name",
            "--country-column",
            "country",
            "--id-column",
            "row_id",
            "--review",
            str(review_csv),
        ]
    )

    assert status == 0
    with review_csv.open(encoding="utf-8") as handle:
        assert {row["row_id"] for row in csv.DictReader(handle)} == {"01024"}


def test_match_applies_a_reviewed_decision(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_ambiguous_registry(data_directory)
    input_csv = tmp_path / "in.csv"
    input_csv.write_text("row_id,port_name,country\n7,Hamilton,US\n", encoding="utf-8")
    decisions_csv = tmp_path / "decisions.csv"
    decisions_csv.write_text(
        "row_id,chosen_registry_id\n7,UNLOCODE:USHAM\n", encoding="utf-8"
    )

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "match",
            str(input_csv),
            "--name-column",
            "port_name",
            "--country-column",
            "country",
            "--id-column",
            "row_id",
            "--decisions",
            str(decisions_csv),
            "--json",
        ]
    )

    assert status == 0
    row = json.loads(capsys.readouterr().out)["data"][0]
    assert row["status"] == "manually_resolved"
    assert row["selected_registry_id"] == "UNLOCODE:USHAM"
    assert row["reason_code"] == "manual_decision"
    assert row["rules_applied"][-1] == "manual_decision"


def test_match_decision_with_unknown_id_is_an_error(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    input_csv = tmp_path / "in.csv"
    input_csv.write_text("row_id,name\n1,Mersin\n", encoding="utf-8")
    decisions_csv = tmp_path / "decisions.csv"
    decisions_csv.write_text("row_id,chosen_registry_id\n1,WPI:999\n", encoding="utf-8")

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "match",
            str(input_csv),
            "--id-column",
            "row_id",
            "--decisions",
            str(decisions_csv),
        ]
    )

    assert status == 2
    assert "unknown registry ID" in capsys.readouterr().err


def test_match_bad_decision_writes_no_partial_output(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    input_csv = tmp_path / "in.csv"
    input_csv.write_text("row_id,name\n1,Mersin\n", encoding="utf-8")
    decisions_csv = tmp_path / "decisions.csv"
    decisions_csv.write_text("row_id,chosen_registry_id\n1,WPI:999\n", encoding="utf-8")
    output_csv = tmp_path / "out.csv"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "match",
            str(input_csv),
            "--id-column",
            "row_id",
            "--decisions",
            str(decisions_csv),
            "--output",
            str(output_csv),
        ]
    )

    assert status == 2
    assert "unknown registry ID" in capsys.readouterr().err
    assert not output_csv.exists()


def test_json_error_output_is_structured(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    status = main(["--data-dir", str(data_directory), "show", "Nowhere", "--json"])

    assert status == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "show"
    assert payload["error"]["code"] == "port_not_found"
    assert payload["error"]["message"]
    assert payload["error"]["details"] == {}


def test_text_error_still_goes_to_stderr(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    status = main(["--data-dir", str(data_directory), "show", "Nowhere"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "harborly: error:" in captured.err


def test_match_output_streams_across_chunks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("harborly.cli._MATCH_CHUNK_SIZE", 2)
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    input_csv = tmp_path / "in.csv"
    input_csv.write_text(
        "row_id,port_name\n1,Mersin\n2,Mersin\n3,Mersin\n4,Mersin\n5,Mersin\n",
        encoding="utf-8",
    )
    output_csv = tmp_path / "out.csv"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "match",
            str(input_csv),
            "--name-column",
            "port_name",
            "--id-column",
            "row_id",
            "--output",
            str(output_csv),
        ]
    )

    assert status == 0
    with output_csv.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["row_id"] for row in rows] == ["1", "2", "3", "4", "5"]
    assert all(row["harborly_registry_id"] == "WPI:1" for row in rows)


def test_match_review_row_ids_continue_across_chunks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("harborly.cli._MATCH_CHUNK_SIZE", 1)
    data_directory = tmp_path / "registry"
    write_ambiguous_registry(data_directory)
    input_csv = tmp_path / "in.csv"
    input_csv.write_text(
        "port_name,country\nHamilton,US\nHamilton,US\nHamilton,US\n", encoding="utf-8"
    )
    review_csv = tmp_path / "review.csv"

    status = main(
        [
            "--data-dir",
            str(data_directory),
            "match",
            str(input_csv),
            "--name-column",
            "port_name",
            "--country-column",
            "country",
            "--review",
            str(review_csv),
        ]
    )

    assert status == 0
    with review_csv.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert sorted({row["row_id"] for row in rows}) == ["1", "2", "3"]


class _RouteCommandRegistry:
    def __init__(self, ports: dict[str, object]) -> None:
        self.ports = ports
        self.calls: list[tuple[str, str | None]] = []

    def resolve(self, value: str, *, country_code: str | None = None) -> object:
        self.calls.append((value, country_code))
        return self.ports[value]


class _RouteCommandResult:
    def __init__(self, summary: dict[str, object]) -> None:
        self._summary = summary

    def summary(self) -> dict[str, object]:
        return self._summary


def test_route_cli_preserves_two_port_path_and_default_restrictions(
    monkeypatch, capsys
) -> None:
    origin, destination = object(), object()
    registry = _RouteCommandRegistry({"A": origin, "C": destination})

    class FakeRouter:
        instances: list[FakeRouter] = []

        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.route_calls: list[tuple[object, object, dict[str, object]]] = []
            FakeRouter.instances.append(self)

        def route(
            self, start: object, end: object, **kwargs: object
        ) -> _RouteCommandResult:
            self.route_calls.append((start, end, kwargs))
            return _RouteCommandResult({"kind": "single"})

        def route_sequence(self, *args: object, **kwargs: object) -> object:
            pytest.fail(f"route_sequence should not be called: {args}, {kwargs}")

    monkeypatch.setattr("harborly.cli._require_optional_extras", lambda *_args: True)
    monkeypatch.setattr("harborly.cli._load_registry", lambda _args: registry)
    monkeypatch.setattr("harborly.router.SeaRouter", FakeRouter)

    assert main(["route", "A", "C", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"] == {"kind": "single"}
    assert registry.calls == [("A", None), ("C", None)]
    assert len(FakeRouter.instances) == 1
    assert FakeRouter.instances[0].kwargs == {"cache_path": None}
    assert FakeRouter.instances[0].route_calls == [(origin, destination, {})]


def test_route_cli_routes_ordered_vias_with_explicit_restrictions(
    monkeypatch, capsys
) -> None:
    origin, via_one, via_two, destination = object(), object(), object(), object()
    registry = _RouteCommandRegistry(
        {"A": origin, "B": via_one, "D": via_two, "C": destination}
    )

    class FakeRouter:
        instance: FakeRouter | None = None

        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.sequence_calls: list[tuple[object, ...]] = []
            FakeRouter.instance = self

        def route(self, *args: object, **kwargs: object) -> object:
            pytest.fail(f"route should not be called: {args}, {kwargs}")

        def route_sequence(
            self, ports: list[object], **kwargs: object
        ) -> _RouteCommandResult:
            self.sequence_calls.append((*ports, kwargs))
            return _RouteCommandResult({"kind": "sequence"})

    monkeypatch.setattr("harborly.cli._require_optional_extras", lambda *_args: True)
    monkeypatch.setattr("harborly.cli._load_registry", lambda _args: registry)
    monkeypatch.setattr("harborly.router.SeaRouter", FakeRouter)

    assert (
        main(
            [
                "route",
                "A",
                "C",
                "--via",
                "B",
                "--via",
                "D",
                "--restrictions",
                "suez",
                "panama",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"] == {"kind": "sequence"}
    assert registry.calls == [("A", None), ("B", None), ("D", None), ("C", None)]
    assert FakeRouter.instance is not None
    assert FakeRouter.instance.kwargs == {
        "cache_path": None,
        "restrictions": ["suez", "panama"],
    }
    assert FakeRouter.instance.sequence_calls == [
        (origin, via_one, via_two, destination, {})
    ]


def test_route_cli_rejects_invalid_restriction(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["route", "A", "C", "--restrictions", "not-a-passage"])

    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


class _SequenceCommandResult:
    def __init__(self) -> None:
        self.kml_paths: list[object] = []
        self.legs = (
            _SequenceCommandLeg("A", "B", 10.0),
            _SequenceCommandLeg("B", "C", 20.0),
        )
        self.total_distance_nmi = 30.0
        self.duration_hours = 2.0
        self.duration_days = 0.08

    def summary(self) -> dict[str, object]:
        return {
            "total_distance_nmi": 30.0,
            "duration_hours": 2.0,
            "legs": [{"origin": {"name": "A"}}, {"origin": {"name": "B"}}],
        }

    def to_geojson_feature_collection(self) -> dict[str, object]:
        return {"type": "FeatureCollection", "features": [{}, {}]}

    def write_kml(self, path: object) -> None:
        self.kml_paths.append(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("<kml><Placemark/><Placemark/></kml>", encoding="utf-8")


class _SequenceCommandLeg:
    def __init__(self, origin: str, destination: str, distance_nmi: float) -> None:
        self.origin = _SequenceCommandPort(origin)
        self.destination = _SequenceCommandPort(destination)
        self.distance_nmi = distance_nmi


class _SequenceCommandPort:
    def __init__(self, name: str) -> None:
        self.name = name
        self.registry_id = name


def test_route_sequence_outputs(monkeypatch, tmp_path, capsys) -> None:
    origin, via, destination = object(), object(), object()
    registry = _RouteCommandRegistry({"A": origin, "B": via, "C": destination})
    result = _SequenceCommandResult()

    class FakeRouter:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def route_sequence(
            self, ports: list[object], **_kwargs: object
        ) -> _SequenceCommandResult:
            assert ports == [origin, via, destination]
            return result

    monkeypatch.setattr("harborly.cli._require_optional_extras", lambda *_args: True)
    monkeypatch.setattr("harborly.cli._load_registry", lambda _args: registry)
    monkeypatch.setattr("harborly.router.SeaRouter", FakeRouter)
    monkeypatch.setattr("harborly.router.SequenceSeaRoute", _SequenceCommandResult)

    assert main(["route", "A", "C", "--via", "B", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"] == result.summary()

    geojson_path = tmp_path / "trip.geojson"
    kml_path = tmp_path / "trip.kml"
    assert (
        main(
            [
                "route",
                "A",
                "C",
                "--via",
                "B",
                "--geojson",
                str(geojson_path),
                "--kml",
                str(kml_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "leg 1:" in output
    assert "leg 2:" in output
    assert "total_distance_nmi: 30.00" in output
    assert "duration_hours: 2.00" in output
    assert json.loads(geojson_path.read_text())["type"] == "FeatureCollection"
    assert len(json.loads(geojson_path.read_text())["features"]) == 2
    assert len(result.kml_paths) == 1
    assert Path(result.kml_paths[0]).parent == kml_path.parent
    assert Path(result.kml_paths[0]) != kml_path


def _set_sequence_command_result(monkeypatch, result: _SequenceCommandResult) -> None:
    origin, via, destination = object(), object(), object()
    registry = _RouteCommandRegistry({"A": origin, "B": via, "C": destination})

    class FakeRouter:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def route_sequence(
            self, *_args: object, **_kwargs: object
        ) -> _SequenceCommandResult:
            return result

    monkeypatch.setattr("harborly.cli._require_optional_extras", lambda *_args: True)
    monkeypatch.setattr("harborly.cli._load_registry", lambda _args: registry)
    monkeypatch.setattr("harborly.router.SeaRouter", FakeRouter)
    monkeypatch.setattr("harborly.router.SequenceSeaRoute", _SequenceCommandResult)


@pytest.mark.parametrize("existing", [False, True])
def test_route_sequence_export_failure_preserves_output_state(
    monkeypatch, tmp_path, capsys, existing
) -> None:
    result = _SequenceCommandResult()

    def fail_write_kml(_path: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(result, "write_kml", fail_write_kml)
    _set_sequence_command_result(monkeypatch, result)
    geojson_path = tmp_path / "trip.geojson"
    kml_path = tmp_path / "trip.kml"
    if existing:
        geojson_path.write_text("old geojson", encoding="utf-8")
        kml_path.write_text("old kml", encoding="utf-8")

    assert (
        main(
            [
                "route",
                "A",
                "C",
                "--via",
                "B",
                "--geojson",
                str(geojson_path),
                "--kml",
                str(kml_path),
            ]
        )
        == 2
    )

    assert "could not write KML" in capsys.readouterr().err
    if existing:
        assert geojson_path.read_text(encoding="utf-8") == "old geojson"
        assert kml_path.read_text(encoding="utf-8") == "old kml"
    else:
        assert not geojson_path.exists()
        assert not kml_path.exists()
    assert not list(tmp_path.glob(".trip.*"))


def test_route_sequence_geojson_write_failure_uses_cli_error_path(
    monkeypatch, tmp_path, capsys
) -> None:
    result = _SequenceCommandResult()

    def fail_write_text(_self: Path, *_args: object, **_kwargs: object) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", fail_write_text)
    _set_sequence_command_result(monkeypatch, result)
    geojson_path = tmp_path / "trip.geojson"

    assert (
        main(
            [
                "route",
                "A",
                "C",
                "--via",
                "B",
                "--geojson",
                str(geojson_path),
            ]
        )
        == 2
    )

    assert "could not write GeoJSON" in capsys.readouterr().err
    assert not geojson_path.exists()
    assert not list(tmp_path.glob(".trip.*"))


def test_route_sequence_publish_failure_rolls_back_new_outputs(
    monkeypatch, tmp_path, capsys
) -> None:
    result = _SequenceCommandResult()
    _set_sequence_command_result(monkeypatch, result)
    geojson_path = tmp_path / "trip.geojson"
    kml_path = tmp_path / "trip.kml"
    original_replace = Path.replace
    publishes = 0

    def fail_second_publish(source: Path, target: Path) -> Path:
        nonlocal publishes
        if target in {geojson_path, kml_path}:
            publishes += 1
            if publishes == 2:
                raise OSError("disk full")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_second_publish)

    assert (
        main(
            [
                "route",
                "A",
                "C",
                "--via",
                "B",
                "--geojson",
                str(geojson_path),
                "--kml",
                str(kml_path),
            ]
        )
        == 2
    )

    assert "could not write KML" in capsys.readouterr().err
    assert not geojson_path.exists()
    assert not kml_path.exists()
    assert not list(tmp_path.glob(".trip.*"))


def test_route_via_failure_writes_no_partial_output(
    monkeypatch, tmp_path, capsys
) -> None:
    origin, via, destination = object(), object(), object()
    registry = _RouteCommandRegistry({"A": origin, "B": via, "C": destination})

    class FakeRouter:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def route_sequence(self, *_args: object, **_kwargs: object) -> object:
            raise ValueError("leg failed")

    monkeypatch.setattr("harborly.cli._require_optional_extras", lambda *_args: True)
    monkeypatch.setattr("harborly.cli._load_registry", lambda _args: registry)
    monkeypatch.setattr("harborly.router.SeaRouter", FakeRouter)
    geojson_path = tmp_path / "failed.geojson"
    kml_path = tmp_path / "failed.kml"

    assert (
        main(
            [
                "route",
                "A",
                "C",
                "--via",
                "B",
                "--geojson",
                str(geojson_path),
                "--kml",
                str(kml_path),
            ]
        )
        == 2
    )
    assert "leg failed" in capsys.readouterr().err
    assert not geojson_path.exists()
    assert not kml_path.exists()


def test_route_ambiguous_via_writes_no_output(monkeypatch, tmp_path, capsys) -> None:
    origin, destination = object(), object()
    registry = _RouteCommandRegistry(
        {"A": origin, "B": ValueError("ambiguous"), "C": destination}
    )

    def resolve(value: str, *, country_code: str | None = None) -> object:
        result = registry.ports[value]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(registry, "resolve", resolve)
    monkeypatch.setattr("harborly.cli._require_optional_extras", lambda *_args: True)
    monkeypatch.setattr("harborly.cli._load_registry", lambda _args: registry)
    monkeypatch.setattr(
        "harborly.router.SeaRouter",
        lambda **_kwargs: pytest.fail("router should not construct"),
    )
    output = tmp_path / "ambiguous.geojson"

    assert main(["route", "A", "C", "--via", "B", "--geojson", str(output)]) == 2
    assert "ambiguous" in capsys.readouterr().err
    assert not output.exists()


def test_route_via_rejects_html_map_before_routing(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setattr(
        "harborly.cli._load_registry",
        lambda _args: pytest.fail("registry should not load"),
    )

    assert (
        main(
            [
                "route",
                "A",
                "C",
                "--via",
                "B",
                "--html-map",
                str(tmp_path / "route.html"),
            ]
        )
        == 2
    )
    assert "--via cannot be combined with --html-map" in capsys.readouterr().err
