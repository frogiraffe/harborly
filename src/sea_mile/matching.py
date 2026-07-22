"""Deterministic decisions for bulk destination-port matching."""

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import pandas as pd
from rapidfuzz import fuzz, process

from sea_mile.quality import great_circle_nmi

OFFICIAL_PROVIDERS = frozenset({"NGA_WPI", "UN_LOCODE"})


class MatchStatus(StrEnum):
    AUTO_RESOLVED = "auto_resolved"
    REVIEW_REQUIRED = "review_required"
    UNRESOLVED = "unresolved"


class ConfidenceTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


@dataclass(frozen=True, slots=True)
class ExactMatchDecision:
    status: MatchStatus
    confidence_tier: ConfidenceTier
    selected_registry_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class BatchMatchResult:
    query: str
    country_code: str | None
    status: MatchStatus
    confidence_tier: ConfidenceTier
    selected_registry_id: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "country_code": self.country_code,
            "status": str(self.status),
            "confidence_tier": str(self.confidence_tier),
            "selected_registry_id": self.selected_registry_id,
            "reason": self.reason,
        }


def _location_agreement(
    first_id: str,
    second_id: str,
    coordinates_by_registry_id: dict[str, tuple[float, float]] | None,
    agreement_nmi: float,
) -> bool | None:
    """True/False if both coordinates are known, None if it can't be checked."""

    if coordinates_by_registry_id is None:
        return None
    first = coordinates_by_registry_id.get(first_id)
    second = coordinates_by_registry_id.get(second_id)
    if first is None or second is None:
        return None
    return great_circle_nmi(*first, *second) <= agreement_nmi


def decide_exact_match(
    wpi_registry_ids: list[str],
    unlocode_registry_ids_with_coordinates: list[str],
    *,
    country_requires_review: bool = False,
    coordinates_by_registry_id: dict[str, tuple[float, float]] | None = None,
    coordinate_agreement_nmi: float = 25.0,
) -> ExactMatchDecision:
    """Select only unambiguous exact official matches.

    A single exact WPI match and a single exact UN/LOCODE match for the
    same query are not necessarily the same physical port. Real places
    can legitimately share a name within one country (seen on the real
    registry, more than one US "Hamilton" or "Chatham" hundreds to
    thousands of nautical miles apart). Passing
    coordinates_by_registry_id lets this be caught instead of silently
    auto-resolving to whichever one WPI happens to prefer. Omitting it
    preserves prior behavior.
    """

    wpi_ids = sorted(set(wpi_registry_ids))
    unlocode_ids = sorted(set(unlocode_registry_ids_with_coordinates))
    if len(wpi_ids) == 1:
        reason = "unique exact WPI alias match"
        if len(unlocode_ids) == 1:
            agreement = _location_agreement(
                wpi_ids[0],
                unlocode_ids[0],
                coordinates_by_registry_id,
                coordinate_agreement_nmi,
            )
            if agreement is False:
                return ExactMatchDecision(
                    MatchStatus.REVIEW_REQUIRED,
                    ConfidenceTier.C,
                    None,
                    "exact WPI and UN/LOCODE matches disagree on location",
                )
            if agreement is None:
                reason += " (location unchecked, no coordinates supplied)"
        return ExactMatchDecision(
            MatchStatus.REVIEW_REQUIRED
            if country_requires_review
            else MatchStatus.AUTO_RESOLVED,
            ConfidenceTier.B if country_requires_review else ConfidenceTier.A,
            wpi_ids[0],
            reason,
        )
    if len(wpi_ids) > 1:
        return ExactMatchDecision(
            MatchStatus.REVIEW_REQUIRED,
            ConfidenceTier.C,
            None,
            "multiple exact WPI records",
        )
    if len(unlocode_ids) == 1:
        return ExactMatchDecision(
            MatchStatus.REVIEW_REQUIRED
            if country_requires_review
            else MatchStatus.AUTO_RESOLVED,
            ConfidenceTier.C if country_requires_review else ConfidenceTier.B,
            unlocode_ids[0],
            "unique exact UN/LOCODE port match with coordinates",
        )
    if len(unlocode_ids) > 1:
        return ExactMatchDecision(
            MatchStatus.REVIEW_REQUIRED,
            ConfidenceTier.C,
            None,
            "multiple exact UN/LOCODE records",
        )
    return ExactMatchDecision(
        MatchStatus.UNRESOLVED, ConfidenceTier.D, None, "no exact official match"
    )


def _aliases_by_country(aliases: pd.DataFrame) -> dict[str, dict[str, list[dict]]]:
    result: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for record in aliases.dropna(subset=["country_code", "alias_key"]).to_dict(
        "records"
    ):
        result[record["country_code"]][record["alias_key"]].append(record)
    return result


def _fuzzy_records(
    query_fields: dict[str, Any],
    country_aliases: dict[str, list[dict]],
    *,
    score_cutoff: float,
    limit: int,
    match_method: str,
) -> list[dict]:
    destination_key = str(query_fields["destination_key"])
    # Drop aliases far shorter than the query, which WRatio scores too high.
    min_alias_length = -(-len(destination_key) // 2)  # ceil(len / 2)
    candidate_keys = [key for key in country_aliases if len(key) >= min_alias_length]
    if not candidate_keys:
        return []
    matches = process.extract(
        destination_key,
        candidate_keys,
        scorer=fuzz.WRatio,
        score_cutoff=score_cutoff,
        limit=limit,
    )
    return [
        {
            **query_fields,
            **candidate,
            "match_method": match_method,
            "name_score": float(score),
        }
        for alias_key, score, _ in matches
        for candidate in country_aliases[alias_key]
    ]


def generate_source_aware_candidates(
    queries: pd.DataFrame, aliases: pd.DataFrame
) -> pd.DataFrame:
    """Generate official and GeoNames candidates without cross-source crowding.

    GeoNames is candidate evidence only. A GeoNames exact alias therefore must
    not suppress fuzzy WPI/UN/LOCODE candidate generation for the same query.
    """

    valid_queries = queries[
        queries["country_code"].notna() & queries["destination_key"].ne("")
    ].copy()
    exact = valid_queries.merge(
        aliases,
        left_on=["country_code", "destination_key"],
        right_on=["country_code", "alias_key"],
        how="inner",
    )
    exact["match_method"] = "exact_alias"
    exact["name_score"] = 100.0
    exact = exact.drop_duplicates(["query_id", "registry_id"])

    official_aliases = _aliases_by_country(
        aliases[aliases["provider"].isin(OFFICIAL_PROVIDERS)]
    )
    geonames_aliases = _aliases_by_country(aliases[aliases["provider"].eq("GEONAMES")])
    official_exact_ids = set(
        exact.loc[exact["provider"].isin(OFFICIAL_PROVIDERS), "query_id"]
    )
    geonames_exact_ids = set(exact.loc[exact["provider"].eq("GEONAMES"), "query_id"])

    strong_records: list[dict] = []
    for query in valid_queries.itertuples(index=False):
        query_fields = query._asdict()
        if query.query_id not in official_exact_ids:
            strong_records.extend(
                _fuzzy_records(
                    query_fields,
                    official_aliases.get(query.country_code, {}),
                    score_cutoff=80,
                    limit=5,
                    match_method="fuzzy_alias",
                )
            )
        if query.query_id not in geonames_exact_ids:
            strong_records.extend(
                _fuzzy_records(
                    query_fields,
                    geonames_aliases.get(query.country_code, {}),
                    score_cutoff=80,
                    limit=3,
                    match_method="fuzzy_alias",
                )
            )
    combined = pd.concat(
        [exact, pd.DataFrame(strong_records)], ignore_index=True, sort=False
    )
    official_strong_ids = (
        set(combined.loc[combined["provider"].isin(OFFICIAL_PROVIDERS), "query_id"])
        if not combined.empty
        else set()
    )

    weak_records: list[dict] = []
    for query in valid_queries.itertuples(index=False):
        if query.query_id in official_strong_ids:
            continue
        weak_records.extend(
            _fuzzy_records(
                query._asdict(),
                official_aliases.get(query.country_code, {}),
                score_cutoff=55,
                limit=3,
                match_method="weak_fuzzy_review_only",
            )
        )
    combined = pd.concat(
        [combined, pd.DataFrame(weak_records)], ignore_index=True, sort=False
    )
    if combined.empty:
        return combined
    method_order = {
        "exact_alias": 0,
        "fuzzy_alias": 1,
        "weak_fuzzy_review_only": 2,
    }
    combined["_method_order"] = combined["match_method"].map(method_order)
    return (
        combined.drop_duplicates(["query_id", "registry_id", "match_method"])
        .sort_values(
            ["query_id", "_method_order", "name_score", "registry_id"],
            ascending=[True, True, False, True],
        )
        .drop(columns="_method_order")
    )
