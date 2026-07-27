"""Internal registry data loading, validation, indexing, and data models."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from importlib.resources import files
from math import isfinite
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sea_mile.exceptions import RegistryDataError
from sea_mile.matching import BatchMatchResult

_REGISTRY_COLUMNS = {
    "registry_id",
    "provider",
    "provider_id",
    "country_code",
    "canonical_name",
    "latitude",
    "longitude",
    "unlocode",
    "function_code",
    "source_version",
    "coordinate_resolution",
    "variant_count",
    "coordinate_conflict",
}
_ALIAS_COLUMNS = {"registry_id", "provider", "alias", "alias_key", "alias_type"}
SUPPORTED_REGISTRY_SCHEMA_VERSIONS = frozenset({1})
_PROVIDER_PRIORITY = {
    "NGA_WPI": 0,
    "UN_LOCODE": 1,
    "GEONAMES": 2,
    "OPENSTREETMAP": 3,
}
_SOURCE_SHORT_LABELS = {
    "NGA_WPI": "WPI",
    "UN_LOCODE": "LOCODE",
    "GEONAMES": "GEO",
    "OPENSTREETMAP": "OSM",
}
_QUERY_CACHE_SIZE = 4096


def source_short_label(provider: str) -> str:
    """Return a compact display label for a provider name."""
    return _SOURCE_SHORT_LABELS.get(provider, provider)


def bundled_data_directory() -> Path:
    """Return the directory containing the registry distributed with sea-mile."""
    return Path(str(files("sea_mile").joinpath("data")))


def _positions_by_value(values: pd.Series) -> dict[str, np.ndarray]:
    """Map each non-null value to the integer row positions holding it."""
    codes, uniques = values.factorize(use_na_sentinel=True)
    if len(uniques) == 0:
        return {}
    order = np.argsort(codes, kind="stable")
    sorted_codes = codes[order]
    start = np.searchsorted(sorted_codes, 0, side="left")
    boundaries = np.flatnonzero(np.diff(sorted_codes[start:])) + 1
    groups = np.split(order[start:], boundaries)
    return {
        str(key): positions
        for key, positions in zip(uniques.tolist(), groups, strict=True)
    }


def _optional_text(value: object) -> str | None:
    return None if pd.isna(value) or str(value).strip() == "" else str(value)


def _optional_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _validate_registry_schema(manifest_path: Path) -> None:
    """Refuse a processed registry whose schema this build cannot read."""
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    version = manifest.get("registry_schema_version")
    if version is None or version in SUPPORTED_REGISTRY_SCHEMA_VERSIONS:
        return
    raise RegistryDataError(
        f"registry schema version {version} is not readable by this sea-mile, "
        f"which supports {sorted(SUPPORTED_REGISTRY_SCHEMA_VERSIONS)}. "
        "rebuild the registry with: sea-mile data build"
    )


@dataclass(frozen=True, slots=True)
class Port:
    """One provider-specific port record with explicit source provenance."""

    registry_id: str
    provider: str
    provider_id: str
    country_code: str
    name: str
    latitude: float | None
    longitude: float | None
    unlocode: str | None
    function_code: str | None
    source_version: str
    coordinate_resolution: str | None
    variant_count: int = 1
    coordinate_conflict: bool = False
    canonical_id: str = ""

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_geojson_feature(self) -> dict[str, Any]:
        if not self.has_coordinates:
            geometry = None
        else:
            geometry = {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude],
            }
        properties = self.to_dict()
        properties.pop("latitude")
        properties.pop("longitude")
        return {
            "type": "Feature",
            "id": self.registry_id,
            "properties": properties,
            "geometry": geometry,
        }


@dataclass(frozen=True, slots=True)
class PortSearchResult:
    """A port plus the alias evidence that produced a search result."""

    port: Port
    matched_alias: str
    match_method: str
    name_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.port.to_dict(),
            "matched_alias": self.matched_alias,
            "match_method": self.match_method,
            "name_score": self.name_score,
        }


@dataclass(frozen=True, slots=True)
class NearbyPortResult:
    """A port candidate ranked by great-circle distance from a query point."""

    port: Port
    distance_nmi: float

    def to_dict(self) -> dict[str, Any]:
        return {**self.port.to_dict(), "distance_nmi": self.distance_nmi}


@dataclass(frozen=True, slots=True)
class PortGroup:
    """One physical port, with the source records that describe it."""

    name: str
    country_code: str
    canonical_id: str
    unlocode: str | None
    members: tuple[Port, ...]
    sources: tuple[str, ...]
    latitude: float | None
    longitude: float | None
    coordinate_conflict: bool
    best_score: float
    match_method: str
    best_id: str

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "country_code": self.country_code,
            "canonical_id": self.canonical_id,
            "unlocode": self.unlocode,
            "sources": list(self.sources),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "coordinate_conflict": self.coordinate_conflict,
            "best_score": self.best_score,
            "match_method": self.match_method,
            "best_id": self.best_id,
            "members": [member.to_dict() for member in self.members],
        }


@dataclass(frozen=True, slots=True)
class NearbyPortGroup:
    """A grouped physical port ranked by distance from a query point."""

    group: PortGroup
    distance_nmi: float

    def to_dict(self) -> dict[str, Any]:
        return {**self.group.to_dict(), "distance_nmi": self.distance_nmi}


_ENRICHMENT_FIELDS: tuple[str, ...] = (
    "sea_mile_status",
    "sea_mile_reason_code",
    "sea_mile_registry_id",
    "sea_mile_name",
    "sea_mile_country_code",
    "sea_mile_latitude",
    "sea_mile_longitude",
    "sea_mile_unlocode",
)


def _series_cell(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _port_priority(port: Port) -> tuple[int, int, str]:
    return (
        0 if port.has_coordinates else 1,
        _PROVIDER_PRIORITY.get(port.provider, 99),
        port.registry_id,
    )


def _port_from_row(row: pd.Series) -> Port:
    return Port(
        registry_id=str(row["registry_id"]),
        provider=str(row["provider"]),
        provider_id=str(row["provider_id"]),
        country_code=str(row["country_code"]),
        name=str(row["canonical_name"]),
        latitude=_optional_float(row["latitude"]),
        longitude=_optional_float(row["longitude"]),
        unlocode=_optional_text(row["unlocode"]),
        function_code=_optional_text(row["function_code"]),
        source_version=str(row["source_version"]),
        coordinate_resolution=_optional_text(row["coordinate_resolution"]),
        variant_count=int(row["variant_count"]),
        coordinate_conflict=bool(row["coordinate_conflict"]),
        canonical_id=str(row["canonical_id"]),
    )


def _result_enrichment(registry: Any, result: BatchMatchResult) -> dict[str, object]:
    record: Port | None = None
    registry_id = result.selected_registry_id
    if registry_id and registry_id in registry:
        record = registry.get(registry_id)
    return {
        "sea_mile_status": str(result.status),
        "sea_mile_reason_code": str(result.reason_code),
        "sea_mile_registry_id": registry_id or "",
        "sea_mile_name": record.name if record else "",
        "sea_mile_country_code": record.country_code if record else "",
        "sea_mile_latitude": (
            record.latitude if record and record.latitude is not None else ""
        ),
        "sea_mile_longitude": (
            record.longitude if record and record.longitude is not None else ""
        ),
        "sea_mile_unlocode": record.unlocode if record and record.unlocode else "",
    }
