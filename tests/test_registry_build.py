from __future__ import annotations

import pandas as pd

from sea_mile.registry_build import (
    _provider_manifest_entry,
    _write_parquet_atomic,
    _write_text_atomic,
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
