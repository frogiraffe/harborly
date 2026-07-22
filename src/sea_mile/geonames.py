"""Parse GeoNames port-like features from a local global dump."""

from __future__ import annotations

import csv
from math import isfinite
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from sea_mile.exceptions import RegistryDataError
from sea_mile.normalization import canonical_key, normalize_display_text


def _parse_float(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    return number if isfinite(number) else None


GEONAMES_COLUMNS = (
    "geoname_id",
    "name",
    "ascii_name",
    "alternate_names",
    "latitude",
    "longitude",
    "feature_class",
    "feature_code",
    "country_code",
    "alternate_country_codes",
    "admin1_code",
    "admin2_code",
    "admin3_code",
    "admin4_code",
    "population",
    "elevation",
    "dem",
    "timezone",
    "modification_date",
)

# Port-related GeoNames feature codes documented at geonames.org/export/codes.html.
PORT_FEATURE_CODES = frozenset(
    {
        "ANCH",  # anchorage
        "DCK",  # dock
        "DCKB",  # docking basin
        "DCKY",  # dockyard
        "FYT",  # ferry terminal
        "HBR",  # harbor
        "LDNG",  # landing
        "MAR",  # marina
        "PRT",  # port
    }
)


def load_geonames_port_archive(
    archive_path: str | Path,
    *,
    source_version: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return normalized provider records and aliases from a GeoNames ZIP dump."""

    archive_path = Path(archive_path)
    records: list[dict[str, object]] = []
    aliases: list[dict[str, str]] = []
    with ZipFile(archive_path) as archive:
        text_files = sorted(
            name
            for name in archive.namelist()
            if name.endswith(".txt") and not name.startswith("__MACOSX/")
        )
        if not text_files:
            raise RegistryDataError(
                f"GeoNames archive has no text data file: {archive_path}"
            )
        for member_name in text_files:
            with archive.open(member_name) as raw_handle:
                lines = (line.decode("utf-8") for line in raw_handle)
                reader = csv.reader(lines, delimiter="\t")
                for values in reader:
                    if len(values) != len(GEONAMES_COLUMNS):
                        continue
                    row = dict(zip(GEONAMES_COLUMNS, values, strict=True))
                    feature_code = row["feature_code"]
                    if feature_code not in PORT_FEATURE_CODES:
                        continue
                    latitude = _parse_float(row["latitude"])
                    longitude = _parse_float(row["longitude"])
                    if latitude is None or longitude is None:
                        continue
                    provider_id = row["geoname_id"]
                    registry_id = f"GEONAMES:{provider_id}"
                    canonical_name = normalize_display_text(row["name"])
                    records.append(
                        {
                            "registry_id": registry_id,
                            "provider": "GEONAMES",
                            "provider_id": provider_id,
                            "country_code": row["country_code"].upper(),
                            "canonical_name": canonical_name,
                            "latitude": latitude,
                            "longitude": longitude,
                            "unlocode": None,
                            "function_code": (f"{row['feature_class']}.{feature_code}"),
                            "source_version": source_version,
                            "coordinate_resolution": "decimal_degrees_unspecified",
                        }
                    )
                    names = [(row["name"], "primary"), (row["ascii_name"], "ascii")]
                    names.extend(
                        (name, "alternate")
                        for name in row["alternate_names"].split(",")
                    )
                    seen_alias_keys: set[str] = set()
                    for name, alias_type in names:
                        display_name = normalize_display_text(name)
                        alias_key = canonical_key(display_name)
                        if (
                            not display_name
                            or not alias_key
                            or alias_key in seen_alias_keys
                        ):
                            continue
                        seen_alias_keys.add(alias_key)
                        aliases.append(
                            {
                                "registry_id": registry_id,
                                "provider": "GEONAMES",
                                "alias": display_name,
                                "alias_key": alias_key,
                                "alias_type": alias_type,
                            }
                        )
    return pd.DataFrame(records), pd.DataFrame(aliases)
