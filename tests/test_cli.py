from __future__ import annotations

import csv
import json

import pandas as pd
import pytest

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


def test_route_json_error_carries_a_stable_reason(
    tmp_path, capsys, monkeypatch
) -> None:
    from sea_mile.exceptions import RoutingError, RoutingErrorReason

    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    def boom(self, origin, destination):
        raise RoutingError(
            "backend blew up", reason=RoutingErrorReason.MALFORMED_BACKEND_RESULT
        )

    monkeypatch.setattr("sea_mile.router.SeaRouter.route", boom)
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
    assert "sea-mile search" in stderr


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
        "sea_mile.build.download.download_reference_data",
        lambda *args, **kwargs: download_manifest,
    )
    monkeypatch.setattr(
        "sea_mile.build.registry.build_reference_registry",
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
        "sea_mile.build.download.download_reference_data",
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
    row = next(csv.DictReader(output_csv.open(encoding="utf-8")))
    assert row["ref"] == "X-1"
    assert row["port_name"] == "Mersin"
    assert row["sea_mile_status"] == "auto_resolved"
    assert row["sea_mile_registry_id"] == "WPI:1"
    assert row["sea_mile_name"] == "Mersin"


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
    rows = list(csv.DictReader(review_csv.open(encoding="utf-8")))
    assert [row["candidate_registry_id"] for row in rows] == ["WPI:2", "UNLOCODE:USHAM"]
    assert all(row["row_id"] == "7" for row in rows)
    assert all(row["reason_code"] == "coordinate_conflict" for row in rows)


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
    assert "sea-mile: error:" in captured.err


def test_match_output_streams_across_chunks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("sea_mile.cli._MATCH_CHUNK_SIZE", 2)
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
    rows = list(csv.DictReader(output_csv.open(encoding="utf-8")))
    assert [row["row_id"] for row in rows] == ["1", "2", "3", "4", "5"]
    assert all(row["sea_mile_registry_id"] == "WPI:1" for row in rows)


def test_match_review_row_ids_continue_across_chunks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("sea_mile.cli._MATCH_CHUNK_SIZE", 1)
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
    rows = list(csv.DictReader(review_csv.open(encoding="utf-8")))
    assert sorted({row["row_id"] for row in rows}) == ["1", "2", "3"]
