"""Scoring rules for the matching benchmark."""

from __future__ import annotations

from benchmarks.matching_accuracy import MatchingCase, score
from harborly.matching import (
    BatchMatchResult,
    ConfidenceTier,
    MatchCandidate,
    MatchReason,
    MatchStatus,
)

COORDINATES = {
    # A GeoNames feature and the official port record for the same harbour.
    "GEONAMES:1": (34.240, 132.560),
    "WPI:1": (34.290, 132.560),
    # A different place entirely.
    "WPI:2": (40.000, 140.000),
}
CANONICAL = {"GEONAMES:1": "SM-KURE", "WPI:1": "JPKRE", "WPI:2": "JPOTH"}


def _case(source: str, expected: str) -> MatchingCase:
    return MatchingCase(
        query="Kure",
        country_code="JP",
        expected_canonical_id=expected,
        kind="perturbation",
        variant="truncated",
        source_registry_id=source,
    )


def _resolved(registry_id: str) -> BatchMatchResult:
    return BatchMatchResult(
        query="Kure",
        country_code="JP",
        status=MatchStatus.AUTO_RESOLVED,
        confidence_tier=ConfidenceTier.A,
        selected_registry_id=registry_id,
        reason_code=MatchReason.UNIQUE_EXACT_WPI,
        reason="unique exact WPI alias match",
        candidates=(
            MatchCandidate(
                registry_id=registry_id,
                provider="NGA_WPI",
                name="Kure",
                country_code="JP",
                latitude=COORDINATES[registry_id][0],
                longitude=COORDINATES[registry_id][1],
                unlocode=None,
            ),
        ),
    )


def _score(case: MatchingCase, result: BatchMatchResult):
    return score(
        [case],
        [result],
        CANONICAL,
        frozenset({"JPKRE", "JPOTH"}),
        coordinates_by_registry_id=COORDINATES,
        coordinate_agreement_nmi=25.0,
    )


def test_resolving_to_the_same_place_counts_as_correct() -> None:
    # 'Kure-ko' truncated to 'Kure' resolves to the official Kure port record
    # three miles away. Different canonical IDs, one harbour.
    metrics = _score(_case("GEONAMES:1", "SM-KURE"), _resolved("WPI:1"))

    assert metrics.auto_correct == 1
    assert metrics.auto_wrong == 0


def test_resolving_to_a_distant_record_stays_wrong() -> None:
    metrics = _score(_case("GEONAMES:1", "SM-KURE"), _resolved("WPI:2"))

    assert metrics.auto_correct == 0
    assert metrics.auto_wrong == 1


def test_an_exact_canonical_hit_is_still_correct() -> None:
    metrics = _score(_case("WPI:1", "JPKRE"), _resolved("WPI:1"))

    assert metrics.auto_correct == 1
