"""Assign a stable canonical port identifier to every registry record.

A record that carries a UN/LOCODE code uses that code as its canonical ID, so
every source that shares the code converges on one identifier. A record without
a code attaches to a nearby coded record of the same name when there is one, and
otherwise gets a deterministic SM-<hash> derived from its country, name, and
rounded coordinate. The result is stable across builds and independent of row
order.
"""

from __future__ import annotations

import hashlib

import pandas as pd

from sea_mile.normalization import canonical_key
from sea_mile.quality import great_circle_nmi


def _synthetic_id(
    country: str, name_key: str, latitude: float | None, longitude: float | None
) -> str:
    if (
        latitude is not None
        and longitude is not None
        and pd.notna(latitude)
        and pd.notna(longitude)
    ):
        coordinate = f"{round(float(latitude), 1)}|{round(float(longitude), 1)}"
    else:
        coordinate = ""
    digest = hashlib.sha256(f"{country}|{name_key}|{coordinate}".encode()).hexdigest()
    return "SM-" + digest[:10].upper()


def assign_canonical_ids(
    registry: pd.DataFrame, *, coordinate_agreement_nmi: float = 25.0
) -> list[str]:
    """Return a canonical port ID for each row, in registry order."""

    name_keys = [canonical_key(name) for name in registry["canonical_name"]]
    countries = [str(code) for code in registry["country_code"]]
    unlocodes = list(registry["unlocode"])
    latitudes = list(registry["latitude"])
    longitudes = list(registry["longitude"])

    # Coded records, blocked by country and name, so a code-less record can find
    # a coded sibling to inherit an ID from.
    coded_blocks: dict[tuple[str, str], list[tuple[float, float, str]]] = {}
    for index, code in enumerate(unlocodes):
        if pd.isna(code) or pd.isna(latitudes[index]) or pd.isna(longitudes[index]):
            continue
        block = (countries[index], name_keys[index])
        coded_blocks.setdefault(block, []).append(
            (float(latitudes[index]), float(longitudes[index]), str(code))
        )

    canonical: list[str] = []
    for index, code in enumerate(unlocodes):
        if pd.notna(code):
            canonical.append(str(code))
            continue
        country, name_key = countries[index], name_keys[index]
        latitude, longitude = latitudes[index], longitudes[index]
        chosen: tuple[float, str] | None = None
        if pd.notna(latitude) and pd.notna(longitude):
            for coded_lat, coded_lon, coded in coded_blocks.get(
                (country, name_key), []
            ):
                distance = great_circle_nmi(
                    float(latitude), float(longitude), coded_lat, coded_lon
                )
                candidate = (distance, coded)
                if distance <= coordinate_agreement_nmi and (
                    chosen is None or candidate < chosen
                ):
                    chosen = candidate
        canonical.append(
            chosen[1]
            if chosen is not None
            else _synthetic_id(country, name_key, latitude, longitude)
        )
    return canonical
