"""Build the normalized local port registry from public source snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from sea_mile.canonical import assign_canonical_ids
from sea_mile.exceptions import RegistryDataError
from sea_mile.geonames import load_geonames_port_archive
from sea_mile.normalization import canonical_key, normalize_display_text
from sea_mile.osm import load_osm_port_archive
from sea_mile.reference import parse_unlocode_coordinates, parse_wpi_dms

# The on-disk format of the processed registry. A reader refuses a version it does
# not support instead of failing on a missing or renamed column.
REGISTRY_SCHEMA_VERSION = 1


def registry_content_hash(registry: pd.DataFrame, aliases: pd.DataFrame) -> str:
    """Return a deterministic content hash of the normalized registry.

    Two builds from the same sources produce the same hash regardless of row
    order, so it identifies a build and lets a rebuild be checked for drift.
    """

    registry_csv = registry.sort_values("registry_id").to_csv(index=False)
    aliases_csv = aliases.sort_values(["registry_id", "alias_key", "alias"]).to_csv(
        index=False
    )
    digest = hashlib.sha256()
    digest.update(registry_csv.encode())
    digest.update(aliases_csv.encode())
    return digest.hexdigest()


UNLOCODE_COLUMNS = [
    "change",
    "country_code",
    "location_code",
    "name",
    "name_without_diacritics",
    "subdivision",
    "function",
    "status",
    "date",
    "iata",
    "coordinates",
    "remarks",
]


def _latest_snapshot(raw_root: Path, provider: str, filename: str) -> Path:
    candidate = _optional_snapshot(raw_root, provider, filename)
    if candidate is None:
        raise RegistryDataError(
            f"no {provider} snapshot found under {raw_root / provider}; "
            "run data download first"
        )
    return candidate


def _optional_snapshot(raw_root: Path, provider: str, filename: str) -> Path | None:
    candidates = sorted((raw_root / provider).glob(f"*/{filename}"), reverse=True)
    return candidates[0] if candidates else None


def _provider_manifest_entry(
    registry: pd.DataFrame, aliases: pd.DataFrame
) -> dict[str, int]:
    with_coordinates = 0
    if not registry.empty:
        with_coordinates = int(
            registry[["latitude", "longitude"]].notna().all(axis=1).sum()
        )
    return {
        "records": len(registry),
        "records_with_coordinates": with_coordinates,
        "aliases": len(aliases),
    }


def _clean_unlocode(value: object) -> str | None:
    if pd.isna(value):
        return None
    cleaned = "".join(str(value).split()).upper()
    return cleaned or None


def _clean_country_code(value: object) -> str:
    if pd.isna(value):
        return ""
    code = str(value).strip().upper()
    return code if len(code) == 2 else ""


def _split_aliases(value: object) -> list[str]:
    if pd.isna(value):
        return []
    return [
        normalize_display_text(item)
        for item in str(value).split(";")
        if normalize_display_text(item)
    ]


def _load_wpi(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    records: list[dict[str, object]] = []
    aliases: list[dict[str, str]] = []
    for row in raw.itertuples(index=False):
        provider_id = str(row.portNumber)
        registry_id = f"WPI:{provider_id}"
        latitude = parse_wpi_dms(row.latitude)
        longitude = parse_wpi_dms(row.longitude)
        if latitude is None or longitude is None:
            latitude = longitude = None
        records.append(
            {
                "registry_id": registry_id,
                "provider": "NGA_WPI",
                "provider_id": provider_id,
                "country_code": _clean_country_code(row.countryCode),
                "canonical_name": normalize_display_text(row.portName),
                "latitude": latitude,
                "longitude": longitude,
                "unlocode": _clean_unlocode(row.unloCode),
                "function_code": "port",
                "source_version": f"snapshot-{path.parent.name}",
                "coordinate_resolution": "arc_second",
            }
        )
        names = [(row.portName, "primary")]
        names.extend(
            (alias, "alternate") for alias in _split_aliases(row.alternateName)
        )
        for name, alias_type in names:
            display_name = normalize_display_text(name)
            if display_name:
                aliases.append(
                    {
                        "registry_id": registry_id,
                        "provider": "NGA_WPI",
                        "alias": display_name,
                        "alias_key": canonical_key(display_name),
                        "alias_type": alias_type,
                    }
                )
    return pd.DataFrame(records), pd.DataFrame(aliases).drop_duplicates()


def _load_unlocode(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    parts = []
    with ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if "UNLOCODE CodeListPart" in name and name.endswith(".csv")
        )
        for name in names:
            with archive.open(name) as handle:
                parts.append(
                    pd.read_csv(
                        handle,
                        names=UNLOCODE_COLUMNS,
                        dtype=str,
                        keep_default_na=False,
                    )
                )
    if not parts:
        raise RegistryDataError(f"UN/LOCODE archive has no code-list CSV: {path}")
    raw = pd.concat(parts, ignore_index=True)
    raw = raw[
        raw["country_code"].str.fullmatch(r"[A-Z]{2}", na=False)
        & raw["location_code"].str.fullmatch(r"[A-Z0-9]{3}", na=False)
        & raw["function"].str.startswith("1", na=False)
    ].copy()
    records: list[dict[str, object]] = []
    aliases: list[dict[str, str]] = []
    for row in raw.itertuples(index=False):
        provider_id = f"{row.country_code}{row.location_code}"
        registry_id = f"UNLOCODE:{provider_id}"
        coordinates = parse_unlocode_coordinates(row.coordinates)
        latitude, longitude = coordinates if coordinates else (None, None)
        records.append(
            {
                "registry_id": registry_id,
                "provider": "UN_LOCODE",
                "provider_id": provider_id,
                "country_code": row.country_code,
                "canonical_name": normalize_display_text(row.name),
                "latitude": latitude,
                "longitude": longitude,
                "unlocode": provider_id,
                "function_code": row.function,
                "source_version": path.parent.name,
                "coordinate_resolution": "arc_minute" if coordinates else None,
            }
        )
        for name, alias_type in (
            (row.name, "primary"),
            (row.name_without_diacritics, "without_diacritics"),
        ):
            display_name = normalize_display_text(name)
            if display_name:
                aliases.append(
                    {
                        "registry_id": registry_id,
                        "provider": "UN_LOCODE",
                        "alias": display_name,
                        "alias_key": canonical_key(display_name),
                        "alias_type": alias_type,
                    }
                )
    return pd.DataFrame(records), pd.DataFrame(aliases).drop_duplicates()


def _reconcile_registry_duplicates(registry: pd.DataFrame) -> pd.DataFrame:
    registry = registry.reset_index(drop=True)
    reconciled = registry.drop_duplicates("registry_id", keep="first").set_index(
        "registry_id", drop=False
    )
    reconciled["variant_count"] = registry.groupby("registry_id", sort=False).size()

    coordinates = registry.dropna(subset=["latitude", "longitude"]).drop_duplicates(
        ["registry_id", "latitude", "longitude"]
    )
    coordinate_counts = coordinates.groupby("registry_id").size()
    single = coordinates.set_index("registry_id").loc[
        coordinate_counts[coordinate_counts.eq(1)].index
    ]
    conflicted = coordinate_counts[coordinate_counts.gt(1)].index
    reconciled.loc[single.index, "latitude"] = single["latitude"].astype(float)
    reconciled.loc[single.index, "longitude"] = single["longitude"].astype(float)
    reconciled.loc[conflicted, ["latitude", "longitude"]] = None
    reconciled["coordinate_conflict"] = reconciled.index.isin(conflicted)
    return reconciled.reset_index(drop=True)


def build_reference_registry(reference_root: str | Path) -> dict[str, object]:
    """Build registry Parquet files from the latest local provider snapshots."""

    reference_root = Path(reference_root)
    raw_root = reference_root / "raw"
    processed_root = reference_root / "processed"
    wpi_path = _latest_snapshot(raw_root, "wpi", "UpdatedPub150.csv")
    unlocode_path = _latest_snapshot(raw_root, "unlocode", "unlocode-*-artifacts.zip")
    geonames_path = _latest_snapshot(raw_root, "geonames", "allCountries.zip")

    wpi_registry, wpi_aliases = _load_wpi(wpi_path)
    unlocode_registry, unlocode_aliases = _load_unlocode(unlocode_path)
    geonames_registry, geonames_aliases = load_geonames_port_archive(
        geonames_path,
        source_version=f"daily-{geonames_path.parent.name}",
    )
    provider_frames = {
        "NGA_WPI": (wpi_registry, wpi_aliases),
        "UN_LOCODE": (unlocode_registry, unlocode_aliases),
        "GEONAMES": (geonames_registry, geonames_aliases),
    }

    # OpenStreetMap is optional. It is used only when a local export is present.
    osm_path = _optional_snapshot(raw_root, "osm", "*.geojson")
    if osm_path is not None:
        provider_frames["OPENSTREETMAP"] = load_osm_port_archive(
            osm_path, source_version=f"osm-{osm_path.parent.name}"
        )

    registry = _reconcile_registry_duplicates(
        pd.concat([frame for frame, _ in provider_frames.values()], ignore_index=True)
    )
    registry["canonical_id"] = assign_canonical_ids(registry)
    aliases = pd.concat(
        [frame for _, frame in provider_frames.values()], ignore_index=True
    ).drop_duplicates()
    processed_root.mkdir(parents=True, exist_ok=True)
    registry.to_parquet(processed_root / "port_registry.parquet", index=False)
    aliases.to_parquet(processed_root / "port_aliases.parquet", index=False)
    manifest: dict[str, object] = {
        "registry_schema_version": REGISTRY_SCHEMA_VERSION,
        "registry_content_hash": registry_content_hash(registry, aliases),
        "registry_rows": len(registry),
        "alias_rows": len(aliases),
        "providers": {
            provider: _provider_manifest_entry(provider_registry, provider_aliases)
            for provider, (
                provider_registry,
                provider_aliases,
            ) in provider_frames.items()
        },
        "duplicate_provider_ids_reconciled": int(
            registry["variant_count"].sub(1).clip(lower=0).sum()
        ),
        "coordinate_conflict_records": int(registry["coordinate_conflict"].sum()),
    }
    (processed_root / "registry_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
