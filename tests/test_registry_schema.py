from __future__ import annotations

import json

import pandas as pd
import pytest

from sea_mile.build.registry import REGISTRY_SCHEMA_VERSION, registry_content_hash
from sea_mile.exceptions import RegistryDataError
from sea_mile.ports import PortRegistry, bundled_data_directory


def _registry_frame() -> pd.DataFrame:
    return pd.DataFrame(
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
            }
        ]
    )


def _alias_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "registry_id": "WPI:1",
                "provider": "NGA_WPI",
                "alias": "Mersin",
                "alias_key": "mersin",
                "alias_type": "primary",
            }
        ]
    )


def _write_registry(directory) -> None:
    directory.mkdir()
    _registry_frame().to_parquet(directory / "port_registry.parquet", index=False)
    _alias_frame().to_parquet(directory / "port_aliases.parquet", index=False)


def test_content_hash_is_order_independent() -> None:
    registry = _registry_frame()
    aliases = _alias_frame()
    reversed_registry = registry.iloc[::-1].reset_index(drop=True)

    assert registry_content_hash(registry, aliases) == registry_content_hash(
        reversed_registry, aliases
    )


def test_content_hash_changes_with_content() -> None:
    registry = _registry_frame()
    aliases = _alias_frame()
    changed = registry.copy()
    changed.loc[0, "canonical_name"] = "Renamed"

    assert registry_content_hash(registry, aliases) != registry_content_hash(
        changed, aliases
    )


def test_from_directory_rejects_an_unsupported_schema(tmp_path) -> None:
    directory = tmp_path / "registry"
    _write_registry(directory)
    (directory / "registry_manifest.json").write_text(
        json.dumps({"registry_schema_version": 999})
    )

    with pytest.raises(RegistryDataError, match="schema version 999"):
        PortRegistry.from_directory(directory)


def test_from_directory_accepts_the_current_schema(tmp_path) -> None:
    directory = tmp_path / "registry"
    _write_registry(directory)
    (directory / "registry_manifest.json").write_text(
        json.dumps({"registry_schema_version": REGISTRY_SCHEMA_VERSION})
    )

    assert len(PortRegistry.from_directory(directory)) == 1


def test_from_directory_without_a_manifest_still_loads(tmp_path) -> None:
    directory = tmp_path / "registry"
    _write_registry(directory)

    assert len(PortRegistry.from_directory(directory)) == 1


def test_bundled_registry_is_loadable() -> None:
    registry = PortRegistry.bundled()

    assert len(registry) > 0
    assert set(registry.providers) == {"NGA_WPI", "GEONAMES"}
    assert bundled_data_directory().is_dir()
