"""Exercise the real WPI, UN/LOCODE, and GeoNames parsers on format-accurate input.

The rows are synthetic but use the exact on-disk layout of each source, so the
real column names, DMS and arc-minute coordinate parsing, function-code
filtering, and ZIP handling are covered without downloading or committing the
source data.
"""

from __future__ import annotations

from zipfile import ZipFile

import pandas as pd

from sea_mile.build.registry import _load_unlocode, _load_wpi
from sea_mile.sources.geonames import load_geonames_port_archive


def test_load_wpi_parses_the_real_column_layout(tmp_path) -> None:
    frame = pd.DataFrame(
        [
            {
                "portNumber": 10001,
                "portName": "Test Harbour",
                "countryCode": "TX",
                "latitude": "12°30'00\"N",
                "longitude": "34°15'30\"E",
                "unloCode": "TXTHR",
                "alternateName": "Testville;Old Test Harbour",
            },
            {
                "portNumber": 10002,
                "portName": "North Point",
                "countryCode": "TX",
                "latitude": "45°00'00\"N",
                "longitude": "70°45'00\"W",
                "unloCode": "",
                "alternateName": "",
            },
            {
                "portNumber": 10003,
                "portName": "Broken Coord",
                "countryCode": "TX",
                "latitude": "unknown",
                "longitude": "unknown",
                "unloCode": "TXBRK",
                "alternateName": "",
            },
        ]
    )
    path = tmp_path / "UpdatedPub150.csv"
    frame.to_csv(path, index=False, encoding="utf-8-sig")

    records, aliases = _load_wpi(path)
    by_id = records.set_index("registry_id")

    assert by_id.loc["WPI:10001", "latitude"] == 12.5
    assert round(by_id.loc["WPI:10001", "longitude"], 4) == 34.2583
    assert by_id.loc["WPI:10001", "unlocode"] == "TXTHR"
    assert by_id.loc["WPI:10002", "longitude"] == -70.75
    assert pd.isna(by_id.loc["WPI:10002", "unlocode"])
    # A pair with one unparsable coordinate nulls both, staying a complete pair.
    assert pd.isna(by_id.loc["WPI:10003", "latitude"])
    assert pd.isna(by_id.loc["WPI:10003", "longitude"])
    assert set(aliases[aliases["registry_id"] == "WPI:10001"]["alias"]) == {
        "Test Harbour",
        "Testville",
        "Old Test Harbour",
    }


def test_load_unlocode_filters_non_ports_and_parses_coordinates(tmp_path) -> None:
    rows = [
        # change, country, location, name, name_no_diacritics, subdivision,
        # function, status, date, iata, coordinates, remarks
        [
            "",
            "TX",
            "THR",
            "Test Harbour",
            "Test Harbour",
            "",
            "1-------",
            "AI",
            "0601",
            "",
            "1230N 03415E",
            "",
        ],
        [
            "",
            "TX",
            "RLY",
            "Test Railyard",
            "Test Railyard",
            "",
            "--3-----",
            "RL",
            "0307",
            "",
            "1231N 03416E",
            "",
        ],
        [
            "",
            "TX",
            "PRT",
            "Second Port",
            "Second Port",
            "",
            "12345---",
            "AI",
            "0601",
            "",
            "4500N 07045W",
            "",
        ],
        [
            "",
            "XX",
            "NOC",
            "No Coordinate",
            "No Coordinate",
            "",
            "1-------",
            "AI",
            "0601",
            "",
            "",
            "",
        ],
    ]
    content = "\n".join(",".join(row) for row in rows)
    archive = tmp_path / "unlocode.zip"
    with ZipFile(archive, "w") as handle:
        handle.writestr("release/csv/UNLOCODE CodeListPart1.csv", content)

    records, _ = _load_unlocode(archive)
    by_id = records.set_index("registry_id")

    # The railyard (function does not start with "1") is dropped.
    assert set(records["registry_id"]) == {
        "UNLOCODE:TXTHR",
        "UNLOCODE:TXPRT",
        "UNLOCODE:XXNOC",
    }
    assert by_id.loc["UNLOCODE:TXTHR", "latitude"] == 12.5
    assert by_id.loc["UNLOCODE:TXTHR", "longitude"] == 34.25
    assert by_id.loc["UNLOCODE:TXPRT", "longitude"] == -70.75
    assert pd.isna(by_id.loc["UNLOCODE:XXNOC", "latitude"])


def test_load_geonames_keeps_only_port_features(tmp_path) -> None:
    rows = [
        [
            "7001",
            "Test Harbor",
            "Test Harbor",
            "Testville,Old Harbor",
            "12.5",
            "34.25",
            "S",
            "HBR",
            "TX",
            "",
            "",
            "",
            "",
            "",
            "0",
            "",
            "0",
            "Europe/Test",
            "2026-01-01",
        ],
        [
            "7002",
            "Test City",
            "Test City",
            "",
            "12.6",
            "34.30",
            "P",
            "PPL",
            "TX",
            "",
            "",
            "",
            "",
            "",
            "1000",
            "",
            "0",
            "Europe/Test",
            "2026-01-01",
        ],
        [
            "7003",
            "Marina Bay",
            "Marina Bay",
            "",
            "45.0",
            "-70.75",
            "S",
            "MAR",
            "TX",
            "",
            "",
            "",
            "",
            "",
            "0",
            "",
            "0",
            "Europe/Test",
            "2026-01-01",
        ],
    ]
    assert all(len(row) == 19 for row in rows)
    content = "\n".join("\t".join(row) for row in rows)
    archive = tmp_path / "geonames.zip"
    with ZipFile(archive, "w") as handle:
        handle.writestr("allCountries.txt", content)

    records, aliases = load_geonames_port_archive(archive, source_version="test")
    by_id = records.set_index("registry_id")

    # The populated place (feature code PPL) is dropped. The harbor and marina stay.
    assert set(records["registry_id"]) == {"GEONAMES:7001", "GEONAMES:7003"}
    assert by_id.loc["GEONAMES:7001", "latitude"] == 12.5
    assert by_id.loc["GEONAMES:7001", "function_code"] == "S.HBR"
    assert "test harbor" in set(
        aliases[aliases["registry_id"] == "GEONAMES:7001"]["alias_key"]
    )
