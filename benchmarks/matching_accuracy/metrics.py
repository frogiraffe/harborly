"""Score matcher output against the labelled cases."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from benchmarks.matching_accuracy.cases import MatchingCase
from harborly.geo import great_circle_nmi
from harborly.matching import OFFICIAL_PROVIDERS, BatchMatchResult, MatchStatus

__all__ = ["OFFICIAL_PROVIDERS", "MatchingMetrics", "VariantScore", "score"]


@dataclass(frozen=True, slots=True)
class VariantScore:
    total: int
    auto_resolved: int
    auto_correct: int
    review_required: int
    unresolved: int
    candidate_recall: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "auto_resolved": self.auto_resolved,
            "auto_correct": self.auto_correct,
            "review_required": self.review_required,
            "unresolved": self.unresolved,
            "candidate_recall": round(self.candidate_recall, 4),
        }


@dataclass(frozen=True, slots=True)
class MatchingMetrics:
    """Headline numbers plus the breakdowns needed to act on them."""

    total: int
    auto_resolved: int
    auto_correct: int
    auto_wrong: int
    review_required: int
    unresolved: int
    candidate_recall: float
    official_candidate_recall: float
    official_candidate_cases: int
    hard_negatives: int
    hard_negative_auto_resolved: int
    by_variant: dict[str, VariantScore] = field(default_factory=dict)
    worst_countries: list[tuple[str, float]] = field(default_factory=list)

    @property
    def auto_resolved_precision(self) -> float:
        return self.auto_correct / self.auto_resolved if self.auto_resolved else 1.0

    @property
    def auto_resolve_rate(self) -> float:
        return self.auto_resolved / self.total if self.total else 0.0

    @property
    def review_rate(self) -> float:
        return self.review_required / self.total if self.total else 0.0

    @property
    def unresolved_rate(self) -> float:
        return self.unresolved / self.total if self.total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "auto_resolved": self.auto_resolved,
            "auto_correct": self.auto_correct,
            "auto_wrong": self.auto_wrong,
            "review_required": self.review_required,
            "unresolved": self.unresolved,
            "auto_resolved_precision": round(self.auto_resolved_precision, 4),
            "auto_resolve_rate": round(self.auto_resolve_rate, 4),
            "review_rate": round(self.review_rate, 4),
            "unresolved_rate": round(self.unresolved_rate, 4),
            "candidate_recall": round(self.candidate_recall, 4),
            "official_candidate_recall": round(self.official_candidate_recall, 4),
            "official_candidate_cases": self.official_candidate_cases,
            "hard_negatives": self.hard_negatives,
            "hard_negative_auto_resolved": self.hard_negative_auto_resolved,
            "by_variant": {
                name: score.as_dict() for name, score in sorted(self.by_variant.items())
            },
            "worst_countries": [
                {"country_code": code, "candidate_recall": round(recall, 4)}
                for code, recall in self.worst_countries
            ],
        }


def score(
    cases: list[MatchingCase],
    results: list[BatchMatchResult],
    canonical_by_registry_id: dict[str, str],
    official_canonical_ids: frozenset[str],
    *,
    coordinates_by_registry_id: dict[str, tuple[float, float]] | None = None,
    coordinate_agreement_nmi: float = 25.0,
) -> MatchingMetrics:
    """Compare each result against its label.

    An answer is correct when it names the same place as the source record:
    either it carries the expected canonical identity, or it sits within
    ``coordinate_agreement_nmi`` of the source record. The package already treats
    that radius as one place, in `preferred_same_identity`, `decide_exact_match`
    and canonical clustering, so scoring on it stays consistent with how identity
    is defined everywhere else.

    Proximity matters because canonical identity blocks on the name key as well
    as the coordinate. `Kure-ko` truncated to `Kure` resolves to the official
    `Kure` port record 3.2 nmi away, and the two hold different canonical IDs
    because their names differ, not because they are different harbours. It does
    not weaken the precision guard: hard negatives lie further apart than this
    radius by construction.

    Official candidate recall is scored only over the cases whose expected
    identity actually has an official record. Most of the registry is GeoNames,
    so measuring it over every case would report a low number that mostly counts
    places for which no official record exists to be found.
    """

    coordinates = coordinates_by_registry_id or {}

    def names_the_same_place(candidate_id: str | None, case: MatchingCase) -> bool:
        if not candidate_id:
            return False
        if canonical_by_registry_id.get(candidate_id) == case.expected_canonical_id:
            return True
        here = coordinates.get(candidate_id)
        there = coordinates.get(case.source_registry_id)
        if here is None or there is None:
            return False
        return (
            great_circle_nmi(here[0], here[1], there[0], there[1])
            <= coordinate_agreement_nmi
        )

    positives = [
        (case, result)
        for case, result in zip(cases, results, strict=True)
        if case.kind == "perturbation"
    ]
    negatives = [
        (case, result)
        for case, result in zip(cases, results, strict=True)
        if case.kind == "hard_negative"
    ]

    auto = correct = wrong = review = unresolved = 0
    recalled = official_recalled = official_possible = 0
    per_variant: dict[str, Counter[str]] = defaultdict(Counter)
    per_country: dict[str, list[int]] = defaultdict(list)

    for case, result in positives:
        expected = case.expected_canonical_id
        counter = per_variant[case.variant]
        counter["total"] += 1

        if result.status is MatchStatus.AUTO_RESOLVED:
            auto += 1
            counter["auto_resolved"] += 1
            if names_the_same_place(result.selected_registry_id, case):
                correct += 1
                counter["auto_correct"] += 1
            else:
                wrong += 1
        elif result.status is MatchStatus.REVIEW_REQUIRED:
            review += 1
            counter["review_required"] += 1
        else:
            unresolved += 1
            counter["unresolved"] += 1

        hit = any(
            names_the_same_place(candidate.registry_id, case)
            for candidate in result.candidates
        )
        if expected in official_canonical_ids:
            official_possible += 1
            official_recalled += int(
                any(
                    candidate.provider in OFFICIAL_PROVIDERS
                    and names_the_same_place(candidate.registry_id, case)
                    for candidate in result.candidates
                )
            )
        recalled += int(hit)
        counter["recalled"] += int(hit)
        per_country[case.country_code or ""].append(int(hit))

    total = len(positives)
    by_variant = {
        variant: VariantScore(
            total=counter["total"],
            auto_resolved=counter["auto_resolved"],
            auto_correct=counter["auto_correct"],
            review_required=counter["review_required"],
            unresolved=counter["unresolved"],
            candidate_recall=counter["recalled"] / counter["total"]
            if counter["total"]
            else 0.0,
        )
        for variant, counter in per_variant.items()
    }
    country_recall = sorted(
        (
            (code, sum(hits) / len(hits))
            for code, hits in per_country.items()
            if len(hits) >= 5
        ),
        key=lambda item: (item[1], item[0]),
    )

    return MatchingMetrics(
        total=total,
        auto_resolved=auto,
        auto_correct=correct,
        auto_wrong=wrong,
        review_required=review,
        unresolved=unresolved,
        candidate_recall=recalled / total if total else 0.0,
        official_candidate_recall=(
            official_recalled / official_possible if official_possible else 0.0
        ),
        official_candidate_cases=official_possible,
        hard_negatives=len(negatives),
        hard_negative_auto_resolved=sum(
            1 for _, result in negatives if result.status is MatchStatus.AUTO_RESOLVED
        ),
        by_variant=by_variant,
        worst_countries=country_recall[:10],
    )
