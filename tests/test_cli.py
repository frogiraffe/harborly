from __future__ import annotations

import json

import pandas as pd

from sea_mile.cli import main


def write_registry(directory) -> None:
    directory.mkdir()
    registry = pd.DataFrame(
        [
            {
                "registry_id": "WPI:1",
                "provider": "NGA_WPI",
                "provider_id": "1",
                "country_code": "TR",
                "canonical_name": "Mersin",
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


def test_info_and_search_emit_machine_readable_json(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    assert main(["--data-dir", str(data_directory), "info", "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["registry_records"] == 2

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
    results = json.loads(capsys.readouterr().out)
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
    nearest = json.loads(capsys.readouterr().out)
    assert nearest[0]["best_id"] == "WPI:1"
    assert "distance_nmi" in nearest[0]


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
    summary = json.loads(capsys.readouterr().out)
    feature = json.loads(output.read_text())
    assert summary["distance_nmi"] > 0
    assert feature["properties"]["routing_units"] == "nautical_miles"


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
    results = {row["query"]: row for row in json.loads(capsys.readouterr().out)}
    assert results["Mersin"]["status"] == "auto_resolved"
    assert results["Mersin"]["selected_registry_id"] == "WPI:1"
    assert results["Atlantis"]["status"] == "unresolved"


def test_match_reports_missing_name_column(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    csv_path = tmp_path / "names.csv"
    csv_path.write_text("port\nMersin\n", encoding="utf-8")

    status = main(["--data-dir", str(data_directory), "match", str(csv_path)])

    assert status == 2
    assert "no column 'name'" in capsys.readouterr().err


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


def test_export_needs_a_filter(tmp_path, capsys) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    assert main(["--data-dir", str(data_directory), "export"]) == 2
    assert "needs --query or --country" in capsys.readouterr().err


def test_matrix_reports_pairwise_distance(tmp_path, capsys) -> None:
    import pytest

    pytest.importorskip("searoute", reason="matrix needs the routing extra")
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    status = main(
        ["--data-dir", str(data_directory), "matrix", "TRMER", "GRPIR", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status == 0
    assert payload["ports"] == ["WPI:1", "WPI:2"]
    assert payload["distances_nmi"][0][0] == 0.0
    assert payload["distances_nmi"][0][1] > 0


def test_data_build_reports_missing_sources_without_loading_registry(
    tmp_path, capsys
) -> None:
    status = main(["data", "build", "--reference-root", str(tmp_path / "reference")])

    assert status == 2
    assert "run data download first" in capsys.readouterr().err
