"""Labelled accuracy benchmark for bulk port-name matching.

Ground truth comes from the registry itself, so no hand labelling is needed:

* Positive cases perturb the name of a known record. The expected answer is that
  record's ``canonical_id``, not its ``registry_id``, because one physical port
  is often held by several providers and resolving to any of them is correct.
* Hard negatives are mined from the registry: records that share a country and a
  canonical name but sit further apart than the coordinate agreement radius are
  genuinely different places. Auto-resolving one of those is the worst outcome
  the matcher can produce, so they are scored separately.
"""

from benchmarks.matching_accuracy.cases import (
    MatchingCase,
    build_cases,
    mine_hard_negatives,
    perturbations,
)
from benchmarks.matching_accuracy.metrics import MatchingMetrics, score

__all__ = [
    "MatchingCase",
    "MatchingMetrics",
    "build_cases",
    "mine_hard_negatives",
    "perturbations",
    "score",
]
