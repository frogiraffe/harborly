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


def _synthetic_id(country: str, name_key: str, representative: str) -> str:
    digest = hashlib.sha256(
        f"{country}|{name_key}|{representative}".encode()
    ).hexdigest()
    return "SM-" + digest[:10].upper()


def _synthetic_representatives(
    pending: list[int],
    *,
    countries: list[str],
    name_keys: list[str],
    latitudes: list[float | None],
    longitudes: list[float | None],
    registry_ids: list[str],
    coordinate_agreement_nmi: float,
) -> dict[int, str]:
    """Map each row needing a synthetic ID to the token identifying its cluster.

    Records sharing a country and name that sit within the agreement radius are
    one place and get one representative. Deriving the identity from a cluster
    leader rather than from rounded coordinates keeps the ID stable when a
    refreshed snapshot nudges a coordinate: a fixed rounding grid split records a
    nautical mile apart whenever they straddled a bucket edge, and moved a record
    to a new identity for a correction far smaller than the agreement radius.

    A record joins a cluster only when it agrees with every member already in it,
    not merely with the first one. Comparing against a single leader would let two
    records 48 nmi apart share an identity because each sits within 25 nmi of a
    record between them, and the rest of the package reads
    ``coordinate_agreement_nmi`` as a pairwise limit: ``preferred_same_identity``
    rejects an identity whose widest pairwise disagreement exceeds it.

    The representative is the smallest registry ID in the cluster, which makes the
    result independent of row order.
    """

    blocks: dict[tuple[str, str], list[int]] = {}
    for index in pending:
        blocks.setdefault((countries[index], name_keys[index]), []).append(index)

    representatives: dict[int, str] = {}
    for indices in blocks.values():
        clusters: list[tuple[str, list[tuple[float, float]]]] = []
        for index in sorted(indices, key=lambda position: str(registry_ids[position])):
            latitude, longitude = latitudes[index], longitudes[index]
            if (
                latitude is None
                or longitude is None
                or pd.isna(latitude)
                or pd.isna(longitude)
            ):
                # Nothing to cluster on, so every coordinate-less record of this
                # name and country shares one identity, as it did before.
                representatives[index] = ""
                continue
            point = (float(latitude), float(longitude))
            for representative, members in clusters:
                if all(
                    great_circle_nmi(point[0], point[1], member[0], member[1])
                    <= coordinate_agreement_nmi
                    for member in members
                ):
                    members.append(point)
                    representatives[index] = representative
                    break
            else:
                representative = str(registry_ids[index])
                clusters.append((representative, [point]))
                representatives[index] = representative
    return representatives


def assign_canonical_ids(
    registry: pd.DataFrame, *, coordinate_agreement_nmi: float = 25.0
) -> list[str]:
    """Return a canonical port ID for each row, in registry order."""

    canonical, _ = assign_canonical_ids_with_evidence(
        registry, coordinate_agreement_nmi=coordinate_agreement_nmi
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

    coded_blocks: dict[tuple[str, str], list[tuple[float, float, str, str]]] = {}
    for index, code in enumerate(unlocodes):
        if pd.isna(code) or pd.isna(latitudes[index]) or pd.isna(longitudes[index]):
            continue
        block = (countries[index], name_keys[index])
        coded_blocks.setdefault(block, []).append(
            (
                float(latitudes[index]),
                float(longitudes[index]),
                str(code),
                str(registry_ids[index]),
            )
        )

    # First pass: settle the rows that inherit an identity, and note which rows
    # are left needing a synthetic one. Clustering those needs the whole set.
    inherited: dict[int, tuple[float, str, str]] = {}
    pending: list[int] = []
    for index, code in enumerate(unlocodes):
        if pd.notna(code):
            continue
        country, name_key = countries[index], name_keys[index]
        latitude, longitude = latitudes[index], longitudes[index]
        chosen: tuple[float, str, str] | None = None
        if pd.notna(latitude) and pd.notna(longitude):
            for coded_lat, coded_lon, coded, coded_reg_id in coded_blocks.get(
                (country, name_key), []
            ):
                distance = great_circle_nmi(
                    float(latitude), float(longitude), coded_lat, coded_lon
                )
                candidate = (distance, coded, coded_reg_id)
                if distance <= coordinate_agreement_nmi and (
                    chosen is None or candidate < chosen
                ):
                    chosen = candidate
        if chosen is not None:
            inherited[index] = chosen
        else:
            pending.append(index)

    representatives = _synthetic_representatives(
        pending,
        countries=countries,
        name_keys=name_keys,
        latitudes=latitudes,
        longitudes=longitudes,
        registry_ids=[str(value) for value in registry_ids],
        coordinate_agreement_nmi=coordinate_agreement_nmi,
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
        chosen = inherited.get(index)
        if chosen is not None:
            canonical.append(chosen[1])
            evidence.append(
                CanonicalEvidence(
                    registry_id=reg_id,
                    canonical_id=chosen[1],
                    method="coordinate_match",
                    source_registry_id=chosen[2],
                    distance_nmi=chosen[0],
                    matched_by="name+country+coordinate",
                )
            )
        else:
            synth = _synthetic_id(
                countries[index], name_keys[index], representatives[index]
            )
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
