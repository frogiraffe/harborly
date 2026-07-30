"""Build realistic bulk-CSV query buckets out of the bundled registry."""

from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd

from benchmarks.matching_accuracy.cases import perturbations

_TYPO_VARIANTS = frozenset({"typo_swap", "typo_drop", "typo_double"})


@dataclass(frozen=True, slots=True)
class WorkloadRow:
    """One query a bulk CSV import would send through `match_names`."""

    query: str
    country_code: str | None
    bucket: str


def _sample_rows(frame: pd.DataFrame, *, rng: random.Random, size: int) -> pd.DataFrame:
    usable = frame[
        frame["canonical_name"].notna()
        & frame["canonical_name"].astype(str).str.strip().ne("")
        & frame["country_code"].notna()
    ]
    positions = list(range(len(usable)))
    rng.shuffle(positions)
    chosen = positions[: min(size, len(positions))]
    return usable.iloc[chosen]


def build_exact_only(frame: pd.DataFrame, *, seed: int, size: int) -> list[WorkloadRow]:
    """Clean names with a correct country code: the exact-match gate should
    resolve every one of these without ever reaching the fuzzy path."""

    rows = _sample_rows(frame, rng=random.Random(seed), size=size)
    return [
        WorkloadRow(
            str(row.canonical_name).strip(), str(row.country_code), "exact_only"
        )
        for row in rows.itertuples()
    ]


def build_fuzzy_typo(frame: pd.DataFrame, *, seed: int, size: int) -> list[WorkloadRow]:
    """Single-typo names with a correct country code: these miss the exact
    gate and exercise the fuzzy-candidate path added in f556fdf."""

    rows = _sample_rows(frame, rng=random.Random(seed), size=size)
    out: list[WorkloadRow] = []
    for offset, row in enumerate(rows.itertuples()):
        name = str(row.canonical_name).strip()
        for variant, text in perturbations(name, seed=seed + offset):
            if variant in _TYPO_VARIANTS:
                out.append(WorkloadRow(text, str(row.country_code), "fuzzy_typo"))
                break
    return out


def build_country_less(
    frame: pd.DataFrame, *, seed: int, size: int
) -> list[WorkloadRow]:
    """Clean names with no country code: exercises the global fallback path
    in `AliasSearchIndex.candidates`, which scans all distinct alias keys
    instead of a per-country subset."""

    rows = _sample_rows(frame, rng=random.Random(seed), size=size)
    return [
        WorkloadRow(str(row.canonical_name).strip(), None, "country_less")
        for row in rows.itertuples()
    ]


def build_mixed(
    exact_only: list[WorkloadRow],
    fuzzy_typo: list[WorkloadRow],
    country_less: list[WorkloadRow],
    *,
    seed: int,
) -> list[WorkloadRow]:
    """A shuffled combination standing in for a realistic dirty CSV import."""

    combined = [*exact_only, *fuzzy_typo, *country_less]
    random.Random(seed).shuffle(combined)
    return combined
