"""Parse OpenStreetMap harbor and marina features from a local GeoJSON file."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path

import pandas as pd

from sea_mile.exceptions import RegistryDataError
from sea_mile.normalization import canonical_key, normalize_display_text

_COUNTRY_KEYS = ("addr:country", "country", "ISO3166-1:alpha2", "is_in:country_code")
_ALIAS_KEYS = ("name", "alt_name", "official_name", "int_name")


def _country_code(properties: dict[str, object]) -> str:
    for key in _COUNTRY_KEYS:
        value = properties.get(key)
        if value and len(str(value).strip()) == 2:
            return str(value).strip().upper()
    return ""


def _is_port(properties: dict[str, object]) -> bool:
    if properties.get("harbour") or properties.get("port"):
        return True
    if properties.get("leisure") == "marina":
        return True
    seamark = str(properties.get("seamark:type", ""))
    return seamark.startswith(("harbour", "marina", "port"))


def _function_code(properties: dict[str, object]) -> str:
    if properties.get("leisure") == "marina":
        return "marina"
    if properties.get("port"):
        return "port"
    seamark = properties.get("seamark:type")
    if seamark:
        return f"seamark:{seamark}"
    return "harbour"


def _point(geometry: dict[str, object] | None) -> tuple[float, float] | None:
    if not geometry or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError):
        return None
    if not isfinite(latitude) or not isfinite(longitude):
        return None
    return latitude, longitude


def load_osm_port_archive(
    archive_path: str | Path,
    *,
    source_version: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return normalized provider records and aliases from an OSM GeoJSON file.

    The file is a GeoJSON FeatureCollection of point features. Each feature
    keeps its OpenStreetMap tags as properties. Only harbor, port, and marina
    features with a name, a two-letter country, and a coordinate are kept.
    """

    archive_path = Path(archive_path)
    data = json.loads(archive_path.read_text(encoding="utf-8"))
    features = data.get("features")
    if not isinstance(features, list):
        raise RegistryDataError(f"OSM file has no feature list: {archive_path}")

    records: list[dict[str, object]] = []
    aliases: list[dict[str, str]] = []
    for feature in features:
        properties = feature.get("properties") or {}
        if not _is_port(properties):
            continue
        point = _point(feature.get("geometry"))
        if point is None:
            continue
        name = normalize_display_text(properties.get("name"))
        country = _country_code(properties)
        raw_id = feature.get("id") or properties.get("@id") or properties.get("id")
        if not name or not country or not raw_id:
            continue
        provider_id = str(raw_id).replace("/", "-")
        registry_id = f"OSM:{provider_id}"
        latitude, longitude = point
        records.append(
            {
                "registry_id": registry_id,
                "provider": "OPENSTREETMAP",
                "provider_id": provider_id,
                "country_code": country,
                "canonical_name": name,
                "latitude": latitude,
                "longitude": longitude,
                "unlocode": None,
                "function_code": _function_code(properties),
                "source_version": source_version,
                "coordinate_resolution": "osm_point",
            }
        )
        seen_alias_keys: set[str] = set()
        for key in _ALIAS_KEYS:
            display_name = normalize_display_text(properties.get(key))
            alias_key = canonical_key(display_name)
            if not display_name or not alias_key or alias_key in seen_alias_keys:
                continue
            seen_alias_keys.add(alias_key)
            aliases.append(
                {
                    "registry_id": registry_id,
                    "provider": "OPENSTREETMAP",
                    "alias": display_name,
                    "alias_key": alias_key,
                    "alias_type": "primary" if key == "name" else "alternate",
                }
            )
    return pd.DataFrame(records), pd.DataFrame(aliases)
