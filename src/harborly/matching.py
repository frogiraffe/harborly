"""Deterministic decisions for bulk destination-port matching."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from harborly.geo import great_circle_nmi

OFFICIAL_PROVIDERS = frozenset({"NGA_WPI", "UN_LOCODE"})


@dataclass(frozen=True, slots=True)
class MatchPolicy:
    """Centralized configuration for matching thresholds and behavior."""

    coordinate_agreement_nmi: float = 25.0
    fuzzy_score_cutoff: float = 80.0
    weak_fuzzy_cutoff: float = 55.0
    max_strong_candidates: int = 5
    max_weak_candidates: int = 3


class MatchStatus(StrEnum):
    AUTO_RESOLVED = "auto_resolved"
    REVIEW_REQUIRED = "review_required"
    UNRESOLVED = "unresolved"
    MANUALLY_RESOLVED = "manually_resolved"


class ConfidenceTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class MatchReason(StrEnum):
    UNIQUE_EXACT_WPI = "unique_exact_wpi"
    UNIQUE_EXACT_UNLOCODE = "unique_exact_unlocode"
    COORDINATE_CONFLICT = "coordinate_conflict"
    MULTIPLE_IDENTITIES = "multiple_identities"
    NO_CANDIDATE = "no_candidate"
    FUZZY_CANDIDATES_ONLY = "fuzzy_candidates_only"
    MANUAL_DECISION = "manual_decision"


@dataclass(frozen=True, slots=True)
class ExactMatchDecision:
    status: MatchStatus
    confidence_tier: ConfidenceTier
    selected_registry_id: str | None
    reason_code: MatchReason
    reason: str
    rules_applied: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """One exact-match record that informed a bulk decision."""

    registry_id: str
    provider: str
    name: str
    country_code: str
    latitude: float | None
    longitude: float | None
    unlocode: str | None
    match_method: str = "exact_alias"
    name_score: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "provider": self.provider,
            "name": self.name,
            "country_code": self.country_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "unlocode": self.unlocode,
            "match_method": self.match_method,
            "name_score": self.name_score,
        }


@dataclass(frozen=True, slots=True)
class BatchMatchResult:
    query: str
    country_code: str | None
    status: MatchStatus
    confidence_tier: ConfidenceTier
    selected_registry_id: str | None
    reason_code: MatchReason
    reason: str
    rules_applied: tuple[str, ...] = ()
    candidates: tuple[MatchCandidate, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "country_code": self.country_code,
            "status": str(self.status),
            "confidence_tier": str(self.confidence_tier),
            "selected_registry_id": self.selected_registry_id,
            "reason_code": str(self.reason_code),
            "reason": self.reason,
            "rules_applied": list(self.rules_applied),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
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
        rules = ["single_exact_wpi"]
        reason = "unique exact WPI alias match"
        if len(unlocode_ids) == 1:
            rules.append("single_exact_unlocode")
            agreement = _location_agreement(
                wpi_ids[0],
                unlocode_ids[0],
                coordinates_by_registry_id,
                coordinate_agreement_nmi,
            )
            if agreement is False:
                rules.append("coordinate_conflict_detected")
                return ExactMatchDecision(
                    MatchStatus.REVIEW_REQUIRED,
                    ConfidenceTier.C,
                    None,
                    MatchReason.COORDINATE_CONFLICT,
                    "exact WPI and UN/LOCODE matches disagree on location",
                    tuple(rules),
                )
            if agreement is None:
                rules.append("coordinate_unchecked")
                reason += " (location unchecked, no coordinates supplied)"
            else:
                rules.append("coordinate_agreement_confirmed")
        return ExactMatchDecision(
            MatchStatus.AUTO_RESOLVED,
            ConfidenceTier.A,
            wpi_ids[0],
            MatchReason.UNIQUE_EXACT_WPI,
            reason,
            tuple(rules),
        )
    if len(wpi_ids) > 1:
        return ExactMatchDecision(
            MatchStatus.REVIEW_REQUIRED,
            ConfidenceTier.C,
            None,
            MatchReason.MULTIPLE_IDENTITIES,
            "multiple exact WPI records",
            ("multiple_exact_wpi",),
        )
    if len(unlocode_ids) == 1:
        return ExactMatchDecision(
            MatchStatus.AUTO_RESOLVED,
            ConfidenceTier.B,
            unlocode_ids[0],
            MatchReason.UNIQUE_EXACT_UNLOCODE,
            "unique exact UN/LOCODE port match with coordinates",
            ("single_exact_unlocode",),
        )
    if len(unlocode_ids) > 1:
        return ExactMatchDecision(
            MatchStatus.REVIEW_REQUIRED,
            ConfidenceTier.C,
            None,
            MatchReason.MULTIPLE_IDENTITIES,
            "multiple exact UN/LOCODE records",
            ("multiple_exact_unlocode",),
        )
    return ExactMatchDecision(
        MatchStatus.UNRESOLVED,
        ConfidenceTier.D,
        None,
        MatchReason.NO_CANDIDATE,
        "no exact official match",
        ("no_official_candidate",),
    )
