from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

from harborly.build.registry import REGISTRY_SCHEMA_VERSION, registry_content_hash
from harborly.exceptions import RegistryDataError
from harborly.ports import PortRegistry, bundled_data_directory


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


def test_content_hash_uses_platform_independent_lf_line_endings() -> None:
    registry = _registry_frame()
    aliases = _alias_frame()

    def hash_with_line_ending(line_ending: str) -> str:
        digest = hashlib.sha256()
        digest.update(
            registry.sort_values("registry_id")
            .to_csv(index=False, lineterminator=line_ending)
            .encode()
        )
        digest.update(
            aliases.sort_values(["registry_id", "alias_key", "alias"])
            .to_csv(index=False, lineterminator=line_ending)
            .encode()
        )
        return digest.hexdigest()

    content_hash = registry_content_hash(registry, aliases)

    assert content_hash == hash_with_line_ending("\n")
    assert content_hash != hash_with_line_ending("\r\n")


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


def test_bundled_registry_manifest_and_data_quality() -> None:
    directory = bundled_data_directory()
    registry = pd.read_parquet(directory / "port_registry.parquet")
    aliases = pd.read_parquet(directory / "port_aliases.parquet")
    manifest = json.loads((directory / "registry_manifest.json").read_text())

    assert manifest["registry_rows"] == len(registry)
    assert manifest["alias_rows"] == len(aliases)
    assert manifest["registry_content_hash"] == registry_content_hash(registry, aliases)
    assert not registry["registry_id"].duplicated().any()
    assert not registry.duplicated(["provider", "provider_id"]).any()
    assert not aliases.duplicated(["registry_id", "alias"]).any()
    assert registry[["latitude", "longitude"]].notna().all(axis=1).all()
    assert pd.to_numeric(registry["latitude"], errors="coerce").between(-90, 90).all()
    assert (
        pd.to_numeric(registry["longitude"], errors="coerce").between(-180, 180).all()
    )
    assert registry["country_code"].str.fullmatch(r"[A-Z]{2}|", na=False).all()
    missing_country = registry[registry["country_code"] == ""]
    assert len(missing_country) == 8
    assert set(missing_country["provider"]) == {"GEONAMES"}
    assert (
        registry["unlocode"].isna()
        | registry["unlocode"].str.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", na=False)
    ).all()
    assert registry["source_version"].str.strip().ne("").all()


def test_bundled_wpi_normalization_preserves_verified_search_behavior() -> None:
    registry = PortRegistry.bundled()

    luderitz = registry.get("WPI:46650")
    portsmouth = registry.get("WPI:35600")

    assert luderitz.country_code == "NA"
    assert luderitz.unlocode == "NALUD"
    assert any(
        result.port.registry_id == luderitz.registry_id
        for result in registry.search("Luderitz Bay", country_code="NA")
    )
    assert portsmouth.unlocode is None
    assert any(
        result.port.registry_id == portsmouth.registry_id
        for result in registry.search("Portsmouth Harbour", country_code="GB")
    )
