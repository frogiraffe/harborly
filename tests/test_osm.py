from __future__ import annotations

import json

import pytest

from sea_mile.exceptions import RegistryDataError
from sea_mile.sources.osm import load_osm_port_archive


def _feature(feature_id, name, properties, longitude, latitude) -> dict:
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {"name": name, **properties},
    }


def _write(tmp_path, features) -> str:
    path = tmp_path / "ports.geojson"
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )
    return path


def test_parses_harbour_and_marina_features(tmp_path) -> None:
    features = [
        _feature(
            "node/1",
            "Mersin Harbour",
            {"harbour": "yes", "addr:country": "TR"},
            34.65,
            36.8,
        ),
        _feature(
            "node/2",
            "Istanbul Marina",
            {"leisure": "marina", "addr:country": "TR"},
            29.0,
            41.0,
        ),
        _feature(
            "node/3",
            "Corner Cafe",
            {"amenity": "cafe", "addr:country": "TR"},
            30.0,
            40.0,
        ),
    ]

    registry, aliases = load_osm_port_archive(
        _write(tmp_path, features), source_version="osm-test"
    )

    assert registry["registry_id"].tolist() == ["OSM:node-1", "OSM:node-2"]
    assert registry["provider"].unique().tolist() == ["OPENSTREETMAP"]
    assert registry.iloc[0]["function_code"] == "harbour"
    assert registry.iloc[1]["function_code"] == "marina"
    assert registry.iloc[0]["latitude"] == 36.8
    assert set(aliases["alias_key"]) == {"mersin harbour", "istanbul marina"}


def test_skips_features_without_a_country(tmp_path) -> None:
    features = [
        _feature("node/1", "No Country Harbour", {"harbour": "yes"}, 34.65, 36.8),
    ]

    registry, _ = load_osm_port_archive(
        _write(tmp_path, features), source_version="osm-test"
    )

    assert registry.empty


def test_missing_feature_list_raises(tmp_path) -> None:
    path = tmp_path / "bad.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection"}), encoding="utf-8")

    with pytest.raises(RegistryDataError, match="no feature list"):
        load_osm_port_archive(path, source_version="osm-test")
