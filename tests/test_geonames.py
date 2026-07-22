from __future__ import annotations

from zipfile import ZipFile

import pytest

from sea_mile.exceptions import RegistryDataError
from sea_mile.geonames import load_geonames_port_archive


def geonames_row(
    geoname_id: str,
    name: str,
    feature_class: str,
    feature_code: str,
) -> str:
    values = [
        geoname_id,
        name,
        name.replace("ı", "i"),
        f"{name} Alt,{name}",
        "36.8",
        "34.65",
        feature_class,
        feature_code,
        "TR",
        "",
        "",
        "",
        "",
        "",
        "0",
        "",
        "0",
        "Europe/Istanbul",
        "2026-07-20",
    ]
    return "\t".join(values)


def test_parser_keeps_port_features_and_source_specific_aliases(tmp_path) -> None:
    archive_path = tmp_path / "sample.zip"
    content = "\n".join(
        [
            geonames_row("1", "Mersin Limanı", "S", "PRT"),
            geonames_row("2", "Mersin City", "P", "PPLA"),
        ]
    )
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("allCountries.txt", content)

    registry, aliases = load_geonames_port_archive(
        archive_path, source_version="test-snapshot"
    )

    assert registry["registry_id"].tolist() == ["GEONAMES:1"]
    assert registry.iloc[0]["function_code"] == "S.PRT"
    assert registry.iloc[0]["source_version"] == "test-snapshot"
    assert set(aliases["alias_key"]) == {"mersin limani", "mersin limani alt"}


def test_parser_skips_rows_with_unparsable_coordinates(tmp_path) -> None:
    archive_path = tmp_path / "sample.zip"
    bad = "\t".join(
        [
            "2",
            "Broken",
            "Broken",
            "",
            "",
            "",
            "S",
            "PRT",
            "TR",
            "",
            "",
            "",
            "",
            "",
            "0",
            "",
            "0",
            "Europe/Istanbul",
            "2026-07-20",
        ]
    )
    content = "\n".join([geonames_row("1", "Mersin", "S", "PRT"), bad])
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("allCountries.txt", content)

    registry, _ = load_geonames_port_archive(
        archive_path, source_version="test-snapshot"
    )

    assert registry["registry_id"].tolist() == ["GEONAMES:1"]


def test_archive_without_text_data_raises_registry_error(tmp_path) -> None:
    archive_path = tmp_path / "empty.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("readme.pdf", "not data")

    with pytest.raises(RegistryDataError, match="no text data file"):
        load_geonames_port_archive(archive_path, source_version="test-snapshot")
