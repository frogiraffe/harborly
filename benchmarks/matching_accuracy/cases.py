"""Build labelled matching cases out of the registry itself."""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass

import pandas as pd

from harborly.geo import great_circle_nmi
from harborly.matching import OFFICIAL_PROVIDERS
from harborly.text import canonical_key


@dataclass(frozen=True, slots=True)
class MatchingCase:
    """One labelled query.

    ``expected_canonical_id`` is ``None`` for a hard negative, where no single
    answer is correct and the matcher is only required not to pick one.
    """

    query: str
    country_code: str | None
    expected_canonical_id: str | None
    kind: str
    variant: str
    source_registry_id: str


def _swap_two_letters(name: str, rng: random.Random) -> str | None:
    positions = [
        index for index, char in enumerate(name[:-1]) if char != name[index + 1]
    ]
    if not positions:
        return None
    index = rng.choice(positions)
    letters = list(name)
    letters[index], letters[index + 1] = letters[index + 1], letters[index]
    return "".join(letters)


def _drop_a_letter(name: str, rng: random.Random) -> str | None:
    if len(name) < 4:
        return None
    index = rng.randrange(1, len(name) - 1)
    return name[:index] + name[index + 1 :]


def _double_a_letter(name: str, rng: random.Random) -> str | None:
    if len(name) < 3:
        return None
    index = rng.randrange(1, len(name))
    return name[:index] + name[index] + name[index:]


def _strip_diacritics(name: str) -> str | None:
    folded = "".join(
        char
        for char in unicodedata.normalize("NFD", name)
        if not unicodedata.combining(char)
    )
    return folded if folded != name else None


def _truncate(name: str, rng: random.Random) -> str | None:
    if len(name) < 6:
        return None
    return name[: rng.randrange(4, len(name))]


def _expand_saint(name: str) -> str | None:
    for short, long in (("St.", "Saint"), ("St ", "Saint "), ("Ste.", "Sainte")):
        if name.startswith(short):
            return long + name[len(short) :]
    return None


def perturbations(name: str, *, seed: int) -> list[tuple[str, str]]:
    """Return ``(variant, text)`` pairs that a dirty spreadsheet would produce.

    Only perturbations that actually change the name are returned, so a variant
    that does not apply to a given name is skipped rather than scored as a
    trivially correct case.
    """

    rng = random.Random(seed)
    produced: list[tuple[str, str | None]] = [
        ("typo_swap", _swap_two_letters(name, rng)),
        ("typo_drop", _drop_a_letter(name, rng)),
        ("typo_double", _double_a_letter(name, rng)),
        ("port_of_prefix", f"Port of {name}"),
        ("port_suffix", f"{name} Port"),
        ("diacritics_stripped", _strip_diacritics(name)),
        ("truncated", _truncate(name, rng)),
        ("uppercase", name.upper() if name.upper() != name else None),
        ("extra_whitespace", f"  {name}  ".replace(" ", "  ")),
        ("saint_expanded", _expand_saint(name)),
    ]
    return [
        (variant, text)
        for variant, text in produced
        if text is not None and text != name and text.strip()
    ]


def build_cases(
    registry: pd.DataFrame, *, seed: int, sample_size: int
) -> list[MatchingCase]:
    """Perturb a deterministic sample of named records with coordinates."""

    usable = registry[
        registry["canonical_name"].notna()
        & registry["canonical_name"].astype(str).str.strip().ne("")
        & registry["country_code"].notna()
    ]
    if usable.empty:
        return []
    rng = random.Random(seed)
    positions = sorted(range(len(usable)))
    rng.shuffle(positions)
    chosen = positions[: min(sample_size, len(positions))]

    cases: list[MatchingCase] = []
    for offset, position in enumerate(chosen):
        row = usable.iloc[position]
        name = str(row["canonical_name"]).strip()
        for variant, text in perturbations(name, seed=seed + offset):
            cases.append(
                MatchingCase(
                    query=text,
                    country_code=str(row["country_code"]),
                    expected_canonical_id=str(row["canonical_id"]),
                    kind="perturbation",
                    variant=variant,
                    source_registry_id=str(row["registry_id"]),
                )
            )
    return cases


def mine_hard_negatives(
    registry: pd.DataFrame, *, coordinate_agreement_nmi: float = 25.0
) -> list[MatchingCase]:
    """Find names that identify two different places among selectable records.

    These are the cases where a confident wrong answer is worst, and the registry
    supplies them for free: if two records share a country and a canonical name
    but lie further apart than the agreement radius, no single record can be the
    right answer for the bare name.

    Only official records count. `decide_exact_match` selects from WPI and
    UN/LOCODE, and treats GeoNames as candidate evidence that never wins, so a
    GeoNames bay or village sharing a port's name creates no ambiguity the
    matcher could resolve wrongly. Counting those made the benchmark report 14
    defects against the bundled registry that were all correct resolutions to a
    single official port record, which would have argued for weakening exactly
    the behaviour the benchmark exists to protect.
    """

    usable = registry[
        registry["provider"].isin(OFFICIAL_PROVIDERS)
        & registry["canonical_name"].notna()
        & registry["country_code"].notna()
        & registry["latitude"].notna()
        & registry["longitude"].notna()
    ].copy()
    if usable.empty:
        return []
    usable["_name_key"] = [canonical_key(name) for name in usable["canonical_name"]]

    negatives: list[MatchingCase] = []
    for (country, _), group in usable.groupby(["country_code", "_name_key"]):
        if len(group) < 2:
            continue
        rows = list(group.itertuples())
        spread = max(
            great_circle_nmi(
                first.latitude, first.longitude, second.latitude, second.longitude
            )
            for index, first in enumerate(rows)
            for second in rows[index + 1 :]
        )
        if spread <= coordinate_agreement_nmi:
            continue
        negatives.append(
            MatchingCase(
                query=str(rows[0].canonical_name).strip(),
                country_code=str(country),
                expected_canonical_id=None,
                kind="hard_negative",
                variant="same_name_far_apart",
                source_registry_id=str(rows[0].registry_id),
            )
        )
    return negatives
