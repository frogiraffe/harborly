"""Verify a local reference build against its manifests and integrity rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sea_mile.build.download import sha256
from sea_mile.exceptions import RegistryDataError
from sea_mile.geo import _EARTH_RADIUS_NMI

NMI_IN_METERS = 1852.0


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str


def _checksum_checks(reference_root: Path, manifest: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    for source, details in manifest["sources"].items():
        path = reference_root / details["path"]
        if not path.exists():
            checks.append(Check(f"checksum_{source}", False, "raw file is missing"))
            continue
        matches = sha256(path) == details["sha256"]
        checks.append(
            Check(
                f"checksum_{source}",
                matches,
                "matches manifest" if matches else "differs from manifest",
            )
        )
    return checks


def _integrity_checks(
    registry: pd.DataFrame, aliases: pd.DataFrame, build_manifest: dict[str, Any]
) -> list[Check]:
    duplicates = int(registry["registry_id"].duplicated().sum())
    orphans = int((~aliases["registry_id"].isin(registry["registry_id"])).sum())
    coordinates = registry[["latitude", "longitude"]]
    partial = int(
        coordinates.notna().any(axis=1).ne(coordinates.notna().all(axis=1)).sum()
    )
    out_of_bounds = int(
        (registry["latitude"].notna() & ~registry["latitude"].between(-90, 90)).sum()
        + (
            registry["longitude"].notna() & ~registry["longitude"].between(-180, 180)
        ).sum()
    )
    null_island = int((registry["latitude"].eq(0) & registry["longitude"].eq(0)).sum())
    return [
        Check("registry_id_unique", duplicates == 0, f"{duplicates} duplicates"),
        Check("aliases_parented", orphans == 0, f"{orphans} orphan aliases"),
        Check("coordinate_pairs_complete", partial == 0, f"{partial} partial pairs"),
        Check(
            "coordinates_in_bounds",
            out_of_bounds == 0,
            f"{out_of_bounds} out of bounds",
        ),
        Check("no_null_island", null_island == 0, f"{null_island} at (0, 0)"),
        Check(
            "registry_rows_match_manifest",
            len(registry) == build_manifest["registry_rows"],
            f"{len(registry)} rows, manifest says {build_manifest['registry_rows']}",
        ),
        Check(
            "alias_rows_match_manifest",
            len(aliases) == build_manifest["alias_rows"],
            f"{len(aliases)} rows, manifest says {build_manifest['alias_rows']}",
        ),
    ]


def _coordinate_agreement(registry: pd.DataFrame) -> dict[str, Any]:
    wpi = registry[registry["provider"].eq("NGA_WPI") & registry["unlocode"].notna()]
    unlocode = registry[
        registry["provider"].eq("UN_LOCODE") & registry["unlocode"].notna()
    ]
    shared = set(wpi["unlocode"]) & set(unlocode["unlocode"])
    columns = ["unlocode", "latitude", "longitude"]
    pairs = (
        wpi[columns]
        .dropna()
        .merge(unlocode[columns].dropna(), on="unlocode", suffixes=("_w", "_u"))
    )
    lat1 = np.radians(pairs["latitude_w"].to_numpy(dtype=float))
    lon1 = np.radians(pairs["longitude_w"].to_numpy(dtype=float))
    lat2 = np.radians(pairs["latitude_u"].to_numpy(dtype=float))
    lon2 = np.radians(pairs["longitude_u"].to_numpy(dtype=float))
    haversine = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    pairs = pairs.assign(
        distance_nmi=_EARTH_RADIUS_NMI * 2 * np.arcsin(np.sqrt(haversine))
    )
    values = pairs.groupby("unlocode")["distance_nmi"].min()
    return {
        "shared_unlocodes": len(shared),
        "coordinate_comparable": int(len(values)),
        "median_minimum_distance_nmi": float(values.median()) if len(values) else None,
        "within_5_nmi": int(values.le(5).sum()),
        "over_25_nmi": int(values.gt(25).sum()),
    }


def _route_check(registry: pd.DataFrame, aliases: pd.DataFrame) -> dict[str, Any]:
    try:
        from pyproj import Geod
    except ImportError:
        return {"skipped": "pyproj is not installed"}

    try:
        from sea_mile.ports import PortRegistry
        from sea_mile.router import SeaRouter

        loaded = PortRegistry(registry, aliases)
        route = SeaRouter().route(loaded.resolve("TRMER"), loaded.resolve("GRPIR"))
    except ImportError:
        return {"skipped": "searoute is not installed"}
    except Exception as error:  # noqa: BLE001
        return {"skipped": f"reference route unavailable ({error})"}

    geod = Geod(ellps="WGS84")
    coordinates = route.geometry["coordinates"]
    meters = 0.0
    for (first_lon, first_lat), (second_lon, second_lat) in zip(
        coordinates, coordinates[1:], strict=False
    ):
        _, _, segment = geod.inv(first_lon, first_lat, second_lon, second_lat)
        meters += segment
    independent_nmi = meters / NMI_IN_METERS
    difference_percent = (independent_nmi / route.distance_nmi - 1) * 100
    return {
        "route": "TRMER-GRPIR",
        "engine_distance_nmi": route.distance_nmi,
        "independent_wgs84_nmi": independent_nmi,
        "relative_difference_percent": difference_percent,
        "passed": abs(difference_percent) <= 1,
    }


def verify_reference_data(reference_root: str | Path) -> dict[str, Any]:
    """Recompute the build checks for a local reference directory."""

    reference_root = Path(reference_root)
    processed = reference_root / "processed"
    manifest_path = reference_root / "manifest.json"
    build_manifest_path = processed / "registry_manifest.json"
    registry_path = processed / "port_registry.parquet"
    aliases_path = processed / "port_aliases.parquet"
    for required in (manifest_path, build_manifest_path, registry_path, aliases_path):
        if not required.exists():
            raise RegistryDataError(f"missing {required}; run data prepare first")

    manifest = json.loads(manifest_path.read_text())
    build_manifest = json.loads(build_manifest_path.read_text())
    registry = pd.read_parquet(registry_path)
    aliases = pd.read_parquet(aliases_path)

    checks = _checksum_checks(reference_root, manifest) + _integrity_checks(
        registry, aliases, build_manifest
    )
    route = _route_check(registry, aliases)
    if "passed" in route:
        checks.append(
            Check(
                "route_independent_within_1_percent",
                bool(route["passed"]),
                f"{route['relative_difference_percent']:.3f}% vs WGS84",
            )
        )

    return {
        "status": "passed" if all(check.passed for check in checks) else "failed",
        "checks": [
            {"name": check.name, "passed": check.passed, "detail": check.detail}
            for check in checks
        ],
        "coordinate_agreement": _coordinate_agreement(registry),
        "route_check": route,
    }
