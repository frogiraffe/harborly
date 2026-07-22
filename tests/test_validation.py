from __future__ import annotations

import json
import sys

import pandas as pd
import pytest

from sea_mile.source_data import sha256
from sea_mile.validation import verify_reference_data


def _record(registry_id, provider, country, name, unlocode, lat, lon) -> dict:
    return {
        "registry_id": registry_id,
        "provider": provider,
        "provider_id": registry_id.split(":", 1)[1],
        "country_code": country,
        "canonical_name": name,
        "latitude": lat,
        "longitude": lon,
        "unlocode": unlocode,
        "function_code": "port",
        "source_version": "test",
        "coordinate_resolution": "test",
        "variant_count": 1,
        "coordinate_conflict": False,
    }


def _alias(registry_id, provider, name, key) -> dict:
    return {
        "registry_id": registry_id,
        "provider": provider,
        "alias": name,
        "alias_key": key,
        "alias_type": "primary",
    }


def _write_reference(root, *, registry_rows: int | None = None) -> None:
    raw_files = {
        "wpi": ("raw/wpi/2020-01-01/UpdatedPub150.csv", b"wpi-data"),
        "unlocode": (
            "raw/unlocode/2025-1/unlocode-2025-1-artifacts.zip",
            b"unlocode-data",
        ),
        "geonames": ("raw/geonames/2020-01-01/allCountries.zip", b"geonames-data"),
    }
    sources = {}
    for name, (relpath, payload) in raw_files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        sources[name] = {"path": relpath, "sha256": sha256(path)}
    (root / "manifest.json").write_text(json.dumps({"sources": sources}))

    processed = root / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    registry = pd.DataFrame(
        [
            _record("WPI:1", "NGA_WPI", "TR", "Mersin", "TRMER", 36.8, 34.65),
            _record(
                "UNLOCODE:TRMER", "UN_LOCODE", "TR", "Mersin", "TRMER", 36.8, 34.63
            ),
        ]
    )
    aliases = pd.DataFrame(
        [
            _alias("WPI:1", "NGA_WPI", "Mersin", "mersin"),
            _alias("UNLOCODE:TRMER", "UN_LOCODE", "Mersin", "mersin"),
        ]
    )
    registry.to_parquet(processed / "port_registry.parquet", index=False)
    aliases.to_parquet(processed / "port_aliases.parquet", index=False)
    (processed / "registry_manifest.json").write_text(
        json.dumps(
            {
                "registry_rows": registry_rows
                if registry_rows is not None
                else len(registry),
                "alias_rows": len(aliases),
            }
        )
    )


@pytest.fixture
def no_pyproj(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyproj", None)


def test_verify_passes_on_a_consistent_build(tmp_path, no_pyproj) -> None:
    _write_reference(tmp_path)

    report = verify_reference_data(tmp_path)

    assert report["status"] == "passed"
    names = {check["name"] for check in report["checks"]}
    assert "checksum_wpi" in names
    assert "registry_id_unique" in names
    assert report["route_check"]["skipped"]


def test_verify_flags_a_checksum_mismatch(tmp_path, no_pyproj) -> None:
    _write_reference(tmp_path)
    (tmp_path / "raw" / "wpi" / "2020-01-01" / "UpdatedPub150.csv").write_bytes(
        b"other"
    )

    report = verify_reference_data(tmp_path)

    assert report["status"] == "failed"
    checksum = next(c for c in report["checks"] if c["name"] == "checksum_wpi")
    assert checksum["passed"] is False


def test_verify_flags_a_row_count_mismatch(tmp_path, no_pyproj) -> None:
    _write_reference(tmp_path, registry_rows=999)

    report = verify_reference_data(tmp_path)

    assert report["status"] == "failed"
    rows = next(
        c for c in report["checks"] if c["name"] == "registry_rows_match_manifest"
    )
    assert rows["passed"] is False
