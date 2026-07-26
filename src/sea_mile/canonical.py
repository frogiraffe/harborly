"""Assign deterministic canonical identifiers to registry records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd

from sea_mile.geo import great_circle_nmi
from sea_mile.text import canonical_key


@dataclass(frozen=True, slots=True)
class CanonicalEvidence:
    """Evidence for why a record received its canonical ID."""

    registry_id: str
    canonical_id: str
    method: str
    source_registry_id: str | None = None
    distance_nmi: float | None = None
    matched_by: str | None = None


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


def assign_canonical_ids_with_evidence(
    registry: pd.DataFrame, *, coordinate_agreement_nmi: float = 25.0
) -> tuple[list[str], list[CanonicalEvidence]]:
    """Return canonical IDs and evidence for each row, in registry order."""

    name_keys = [canonical_key(name) for name in registry["canonical_name"]]
    countries = [str(code) for code in registry["country_code"]]
    unlocodes = list(registry["unlocode"])
    latitudes = list(registry["latitude"])
    longitudes = list(registry["longitude"])
    registry_ids = list(registry["registry_id"])

    coded_blocks: dict[tuple[str, str], list[tuple[float, float, str]]] = {}
    for index, code in enumerate(unlocodes):
        if pd.isna(code) or pd.isna(latitudes[index]) or pd.isna(longitudes[index]):
            continue
        block = (countries[index], name_keys[index])
        coded_blocks.setdefault(block, []).append(
            (float(latitudes[index]), float(longitudes[index]), str(code))
        )

    canonical: list[str] = []
    evidence: list[CanonicalEvidence] = []
    for index, code in enumerate(unlocodes):
        reg_id = str(registry_ids[index]) if index < len(registry_ids) else ""
        if pd.notna(code):
            canonical.append(str(code))
            evidence.append(
                CanonicalEvidence(
                    registry_id=reg_id,
                    canonical_id=str(code),
                    method="unlocode_direct",
                    matched_by="unlocode",
                )
            )
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
        if chosen is not None:
            canonical.append(chosen[1])
            evidence.append(
                CanonicalEvidence(
                    registry_id=reg_id,
                    canonical_id=chosen[1],
                    method="coordinate_match",
                    source_registry_id=chosen[1],
                    distance_nmi=chosen[0],
                    matched_by="name+country+coordinate",
                )
            )
        else:
            synth = _synthetic_id(country, name_key, latitude, longitude)
            canonical.append(synth)
            evidence.append(
                CanonicalEvidence(
                    registry_id=reg_id,
                    canonical_id=synth,
                    method="synthetic",
                    matched_by="no_match",
                )
            )
    return canonical, evidence
