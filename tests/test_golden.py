from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from sea_mile.matching import BatchMatchResult
from sea_mile.ports import PortRegistry

GOLDEN = Path(__file__).resolve().parent / "golden"


def _load_registry() -> PortRegistry:
    registry = pd.read_csv(GOLDEN / "registry.csv", dtype=str, keep_default_na=False)
    aliases = pd.read_csv(GOLDEN / "aliases.csv", dtype=str, keep_default_na=False)
    registry["latitude"] = pd.to_numeric(registry["latitude"], errors="coerce")
    registry["longitude"] = pd.to_numeric(registry["longitude"], errors="coerce")
    registry["variant_count"] = registry["variant_count"].astype(int)
    registry["coordinate_conflict"] = (
        registry["coordinate_conflict"].str.strip().str.lower().eq("true")
    )
    return PortRegistry(registry, aliases)


def _load_cases() -> list[dict[str, str]]:
    with (GOLDEN / "cases.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _run_cases() -> tuple[list[dict[str, str]], list[BatchMatchResult]]:
    registry = _load_registry()
    cases = _load_cases()
    results = registry.match_names(
        [case["name"] for case in cases],
        country_codes=[case["country"] for case in cases],
    )
    return cases, results


def test_golden_cases_resolve_as_labeled() -> None:
    cases, results = _run_cases()
    for case, result in zip(cases, results, strict=True):
        where = f"{case['name']!r} in {case['country']} ({case['category']})"
        assert str(result.status) == case["expect_status"], where
        assert (result.selected_registry_id or "") == case["expect_registry_id"], where
        assert str(result.reason_code) == case["expect_reason_code"], where


def test_golden_precision_and_recall_meet_thresholds() -> None:
    cases, results = _run_cases()
    auto = auto_correct = should_auto = review = 0
    for case, result in zip(cases, results, strict=True):
        expected_auto = case["expect_status"] == "auto_resolved"
        actual_auto = str(result.status) == "auto_resolved"
        should_auto += int(expected_auto)
        auto += int(actual_auto)
        auto_correct += int(
            actual_auto
            and expected_auto
            and (result.selected_registry_id or "") == case["expect_registry_id"]
        )
        review += int(str(result.status) == "review_required")

    precision = auto_correct / auto if auto else 1.0
    recall = auto_correct / should_auto if should_auto else 1.0
    review_rate = review / len(cases)

    # A confident wrong auto-resolve is the worst outcome, so precision is strict.
    assert precision >= 0.99, f"precision {precision}"
    assert recall >= 0.60, f"recall {recall}"
    assert 0.0 <= review_rate <= 1.0


def test_golden_matching_is_deterministic() -> None:
    _, first = _run_cases()
    _, second = _run_cases()
    assert [result.selected_registry_id for result in first] == [
        result.selected_registry_id for result in second
    ]
    assert [str(result.status) for result in first] == [
        str(result.status) for result in second
    ]
