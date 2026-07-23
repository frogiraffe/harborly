from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_cli import write_registry

from sea_mile.cli import main

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "schemas" / "envelope-1.schema.json"
)


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.mark.parametrize(
    "command",
    [
        ["info"],
        ["search", "Mersin"],
        ["search", "Mersin", "--all-sources"],
        ["show", "TRMER"],
        ["near", "36.8", "34.65"],
        ["near", "36.8", "34.65", "--all-sources"],
        ["show", "Nowhere"],  # the error envelope must validate too
    ],
)
def test_command_envelope_matches_schema(tmp_path, capsys, validator, command) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    main(["--data-dir", str(data_directory), *command, "--json"])

    validator.validate(json.loads(capsys.readouterr().out))


def test_match_envelope_matches_schema(tmp_path, capsys, validator) -> None:
    data_directory = tmp_path / "registry"
    write_registry(data_directory)
    csv_path = tmp_path / "names.csv"
    csv_path.write_text("name,country\nMersin,TR\n", encoding="utf-8")

    main(
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

    validator.validate(json.loads(capsys.readouterr().out))


def test_data_command_envelopes_match_schema(
    tmp_path, capsys, validator, monkeypatch
) -> None:
    monkeypatch.setattr(
        "sea_mile.build.download.download_reference_data",
        lambda *args, **kwargs: {"sources": {}},
    )
    monkeypatch.setattr(
        "sea_mile.build.registry.build_reference_registry",
        lambda *args, **kwargs: {"registry_rows": 0},
    )

    main(["data", "download", "--reference-root", str(tmp_path), "--json"])
    validator.validate(json.loads(capsys.readouterr().out))

    main(["data", "prepare", "--reference-root", str(tmp_path), "--json"])
    validator.validate(json.loads(capsys.readouterr().out))


def test_route_and_matrix_envelopes_match_schema(tmp_path, capsys, validator) -> None:
    pytest.importorskip("searoute", reason="route and matrix need the routing extra")
    data_directory = tmp_path / "registry"
    write_registry(data_directory)

    main(["--data-dir", str(data_directory), "route", "TRMER", "GRPIR", "--json"])
    validator.validate(json.loads(capsys.readouterr().out))

    main(["--data-dir", str(data_directory), "matrix", "TRMER", "GRPIR", "--json"])
    validator.validate(json.loads(capsys.readouterr().out))
