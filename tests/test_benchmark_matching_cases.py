"""The benchmark's ground truth has to be trustworthy before its numbers are."""

from __future__ import annotations

import pandas as pd

from benchmarks.matching_accuracy import build_cases, mine_hard_negatives, perturbations


def _record(
    registry_id: str,
    provider: str,
    country: str,
    name: str,
    canonical_id: str,
    latitude: float,
    longitude: float,
    unlocode: str | None = None,
) -> dict:
    return {
        "registry_id": registry_id,
        "provider": provider,
        "country_code": country,
        "canonical_name": name,
        "canonical_id": canonical_id,
        "latitude": latitude,
        "longitude": longitude,
        "unlocode": unlocode,
    }


def _registry_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _record("WPI:1", "NGA_WPI", "NL", "Rotterdam", "NLRTM", 51.95, 4.14),
            _record("WPI:2", "NGA_WPI", "US", "Newport", "USNPT", 41.49, -71.31),
            _record("WPI:3", "NGA_WPI", "US", "Newport", "SM-FAR", 44.63, -124.05),
        ]
    )


def test_perturbations_are_reproducible_for_one_seed() -> None:
    first = build_cases(_registry_frame(), seed=7, sample_size=2)
    second = build_cases(_registry_frame(), seed=7, sample_size=2)

    assert [(case.query, case.variant) for case in first] == [
        (case.query, case.variant) for case in second
    ]


def test_a_different_seed_produces_different_queries() -> None:
    first = build_cases(_registry_frame(), seed=7, sample_size=2)
    second = build_cases(_registry_frame(), seed=8, sample_size=2)

    assert [case.query for case in first] != [case.query for case in second]


def test_every_perturbation_actually_changes_the_name() -> None:
    for variant, text in perturbations("Rotterdam", seed=3):
        assert text != "Rotterdam", variant
        assert text.strip(), variant


def test_expected_answer_is_the_canonical_id_not_the_registry_id() -> None:
    [case] = [
        case
        for case in build_cases(_registry_frame(), seed=1, sample_size=3)
        if case.source_registry_id == "WPI:1"
    ][:1]

    assert case.expected_canonical_id == "NLRTM"


def test_hard_negatives_pair_same_name_records_that_are_far_apart() -> None:
    negatives = mine_hard_negatives(_registry_frame(), coordinate_agreement_nmi=25.0)

    assert len(negatives) == 1
    negative = negatives[0]
    assert negative.query == "Newport"
    assert negative.country_code == "US"
    # Two genuinely different places, so no single answer is correct.
    assert negative.expected_canonical_id is None


def test_records_of_one_place_are_not_mined_as_hard_negatives() -> None:
    frame = _registry_frame()
    frame.loc[frame["registry_id"] == "WPI:3", ["latitude", "longitude"]] = [
        41.50,
        -71.32,
    ]

    assert mine_hard_negatives(frame, coordinate_agreement_nmi=25.0) == []


def test_a_distant_geonames_namesake_is_not_a_hard_negative() -> None:
    # GeoNames is candidate evidence only and never competes for selection, so a
    # bay or village sharing a port's name does not make the name ambiguous.
    # Resolving to the single official port record is the correct answer.
    frame = pd.DataFrame(
        [
            _record(
                "WPI:9", "NGA_WPI", "CL", "Puerto San Antonio", "CLSAI", -33.58, -71.61
            ),
            _record(
                "GEONAMES:1",
                "GEONAMES",
                "CL",
                "Puerto San Antonio",
                "SM-FAR",
                -53.88,
                -70.89,
            ),
        ]
    )

    assert mine_hard_negatives(frame, coordinate_agreement_nmi=25.0) == []


def test_two_distant_official_records_are_a_hard_negative() -> None:
    frame = pd.DataFrame(
        [
            _record("WPI:9", "NGA_WPI", "US", "Hamilton", "SM-A", 39.40, -84.60),
            _record(
                "UNLOCODE:1",
                "UN_LOCODE",
                "US",
                "Hamilton",
                "USHAM",
                43.90,
                -75.50,
                unlocode="USHAM",
            ),
        ]
    )

    [negative] = mine_hard_negatives(frame, coordinate_agreement_nmi=25.0)

    assert negative.query == "Hamilton"
    assert negative.expected_canonical_id is None
