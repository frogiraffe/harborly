"""Regression gate on matching accuracy.

The thresholds are ratchets recorded from a measured run, not aspirations. They
exist so a change that quietly trades precision for coverage fails here instead
of shipping. Tighten them when the underlying numbers improve.
"""

from __future__ import annotations

import pandas as pd
import pytest

from benchmarks.matching_accuracy import build_cases, mine_hard_negatives, score
from benchmarks.matching_accuracy.metrics import OFFICIAL_PROVIDERS
from sea_mile._registry_data import bundled_data_directory
from sea_mile.ports import PortRegistry

SEED = 20260729
# Kept small on purpose. The full-fidelity run is
# `python -m benchmarks.matching_accuracy`; this gate only has to notice a
# regression, and matching an unmatched name costs about 12 ms.
SAMPLE_SIZE = 60

# Measured at seed 20260729 over the bundled registry: precision 1.0000,
# candidate recall 0.9775, official candidate recall 0.9485, and none of the 19
# hard negatives auto-resolved.
MINIMUM_AUTO_RESOLVED_PRECISION = 0.99
MINIMUM_CANDIDATE_RECALL = 0.95
MINIMUM_OFFICIAL_CANDIDATE_RECALL = 0.90


@pytest.fixture(scope="module")
def measured():
    registry = PortRegistry.bundled()
    frame = pd.read_parquet(bundled_data_directory() / "port_registry.parquet")

    cases = build_cases(frame, seed=SEED, sample_size=SAMPLE_SIZE)
    cases.extend(mine_hard_negatives(frame))
    results = registry.match_names(
        [case.query for case in cases],
        country_codes=[case.country_code for case in cases],
    )
    located = frame[frame["latitude"].notna() & frame["longitude"].notna()]
    return score(
        cases,
        results,
        dict(zip(frame["registry_id"], frame["canonical_id"], strict=True)),
        frozenset(
            frame.loc[frame["provider"].isin(OFFICIAL_PROVIDERS), "canonical_id"]
        ),
        coordinates_by_registry_id={
            str(row.registry_id): (float(row.latitude), float(row.longitude))
            for row in located.itertuples()
        },
    )


def test_auto_resolved_answers_stay_precise(measured) -> None:
    assert measured.auto_resolved > 0, "no auto-resolutions to judge"
    assert measured.auto_resolved_precision >= MINIMUM_AUTO_RESOLVED_PRECISION


def test_the_right_answer_reaches_the_candidate_list(measured) -> None:
    assert measured.candidate_recall >= MINIMUM_CANDIDATE_RECALL


def test_official_records_surface_when_one_exists(measured) -> None:
    assert measured.official_candidate_cases > 0
    assert measured.official_candidate_recall >= MINIMUM_OFFICIAL_CANDIDATE_RECALL


def test_names_covering_two_places_are_never_auto_resolved(measured) -> None:
    # The strongest guarantee the matcher offers: where one name in one country
    # covers two official records too far apart to be one place, it must ask for
    # review rather than pick. A confident wrong answer is the worst outcome.
    assert measured.hard_negatives > 0
    assert measured.hard_negative_auto_resolved == 0
