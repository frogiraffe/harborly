from __future__ import annotations

import pandas as pd
import pytest

import harborly.build.registry as registry_build
from harborly.build.registry import (
    _provider_manifest_entry,
    _write_parquet_atomic,
    _write_text_atomic,
    build_reference_registry,
)


def test_provider_manifest_entry_handles_empty_frame() -> None:
    entry = _provider_manifest_entry(pd.DataFrame(), pd.DataFrame())

    assert entry == {"records": 0, "records_with_coordinates": 0, "aliases": 0}


def test_provider_manifest_entry_counts_coordinate_records() -> None:
    registry = pd.DataFrame(
        [
            {"latitude": 1.0, "longitude": 2.0},
            {"latitude": None, "longitude": None},
        ]
    )
    aliases = pd.DataFrame([{"alias": "a"}, {"alias": "b"}, {"alias": "c"}])

    entry = _provider_manifest_entry(registry, aliases)

    assert entry == {"records": 2, "records_with_coordinates": 1, "aliases": 3}


def test_atomic_parquet_write_leaves_no_partial_file(tmp_path) -> None:
    path = tmp_path / "port_registry.parquet"

    _write_parquet_atomic(pd.DataFrame([{"a": 1}]), path)

    assert path.exists()
    assert not path.with_name(path.name + ".part").exists()
    assert pd.read_parquet(path)["a"].tolist() == [1]


def test_atomic_text_write_leaves_no_partial_file(tmp_path) -> None:
    path = tmp_path / "registry_manifest.json"

    _write_text_atomic(path, "reproducible")

    assert path.read_text() == "reproducible"
    assert not path.with_name(path.name + ".part").exists()


def test_build_rejects_unknown_provider(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown registry providers"):
        build_reference_registry(tmp_path, providers=("UNKNOWN",))


def test_build_rejects_empty_provider_set(tmp_path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_reference_registry(tmp_path, providers=())


def test_build_can_require_complete_coordinates(monkeypatch, tmp_path) -> None:
    snapshot = tmp_path / "raw" / "wpi" / "2026-08-09" / "UpdatedPub150.csv"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("unused", encoding="utf-8")
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
            },
            {
                "registry_id": "WPI:2",
                "provider": "NGA_WPI",
                "provider_id": "2",
                "country_code": "TR",
                "canonical_name": "Unknown Coordinates",
                "latitude": None,
                "longitude": None,
                "unlocode": None,
                "function_code": "port",
                "source_version": "test",
                "coordinate_resolution": "arc_second",
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
                "alias": "Unknown Coordinates",
                "alias_key": "unknown coordinates",
                "alias_type": "primary",
            },
        ]
    )
    monkeypatch.setattr(registry_build, "_load_wpi", lambda _: (registry, aliases))
    output = tmp_path / "output"

    manifest = build_reference_registry(
        tmp_path,
        providers=("NGA_WPI",),
        output_directory=output,
        require_coordinates=True,
    )

    built_registry = pd.read_parquet(output / "port_registry.parquet")
    built_aliases = pd.read_parquet(output / "port_aliases.parquet")
    assert built_registry["registry_id"].tolist() == ["WPI:1"]
    assert built_aliases["registry_id"].tolist() == ["WPI:1"]
    assert manifest["providers"]["NGA_WPI"] == {
        "records": 1,
        "records_with_coordinates": 1,
        "aliases": 1,
    }
