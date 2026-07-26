"""Indexed alias candidate generation for port-name search."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from sea_mile.text import canonical_key

_MIN_FUZZY_QUERY_LENGTH = 3
_MIN_GLOBAL_FUZZY_QUERY_LENGTH = 4


@dataclass(frozen=True, slots=True)
class AliasCandidates:
    """Alias rows separated by match phase and ordered by precedence."""

    exact: pd.DataFrame
    prefix: pd.DataFrame
    fuzzy: pd.DataFrame


class AliasSearchIndex:
    """Immutable lookup structures used to generate alias candidates."""

    def __init__(
        self,
        aliases: pd.DataFrame,
        *,
        alias_country: np.ndarray,
        positions_by_key: dict[str, np.ndarray],
    ) -> None:
        self._aliases = aliases
        self._alias_country = alias_country
        self._positions_by_key = positions_by_key
        self._global_keys = list(positions_by_key)
        key_countries = pd.DataFrame(
            {
                "country_code": alias_country,
                "alias_key": aliases["alias_key"].to_numpy(),
            }
        ).dropna(subset=["alias_key"])
        self._keys_by_country: dict[str, list[str]] = {
            str(country): group["alias_key"].drop_duplicates().tolist()
            for country, group in key_countries.groupby("country_code")
        }

    def candidates(
        self,
        query: str,
        *,
        country_code: str | None,
        limit: int,
        fuzzy_enabled: bool,
        minimum_score: float,
    ) -> AliasCandidates:
        """Return exact, prefix, and fuzzy alias rows for a query."""

        empty = self._aliases.iloc[:0].copy()
        query_key = canonical_key(query)
        if not query_key:
            return AliasCandidates(empty, empty.copy(), empty.copy())

        country = country_code.upper() if country_code else None
        distinct_keys = (
            self._keys_by_country.get(country, []) if country else self._global_keys
        )
        exact = self._for_keys([query_key], country)
        if not exact.empty:
            exact["match_method"] = "exact_alias"
            exact["name_score"] = 100.0
            return AliasCandidates(exact, empty, empty.copy())
        if not fuzzy_enabled or not distinct_keys:
            return AliasCandidates(empty, empty.copy(), empty.copy())

        min_fuzzy_len = (
            _MIN_FUZZY_QUERY_LENGTH if country else _MIN_GLOBAL_FUZZY_QUERY_LENGTH
        )
        prefix_keys = [key for key in distinct_keys if key.startswith(query_key)]
        prefix = self._for_keys(prefix_keys, country)
        if not prefix.empty:
            prefix["match_method"] = "prefix_alias"
            prefix["name_score"] = 95.0

        fuzzy = empty.copy()
        if len(query_key) >= min_fuzzy_len:
            minimum_length = -(-len(query_key) // 2)
            prefix_set = set(prefix_keys)
            candidate_keys = [
                key
                for key in distinct_keys
                if len(key) >= minimum_length and key not in prefix_set
            ]
            matches = process.extract(
                query_key,
                candidate_keys,
                scorer=fuzz.WRatio,
                score_cutoff=minimum_score,
                limit=max(limit * 3, limit),
            )
            parts: list[pd.DataFrame] = []
            for alias_key, score, _ in matches:
                part = self._for_keys([alias_key], country)
                part["match_method"] = "fuzzy_alias"
                part["name_score"] = float(score)
                parts.append(part)
            if parts:
                fuzzy = pd.concat(parts)
        return AliasCandidates(empty, prefix, fuzzy)

    def _for_keys(self, keys: list[str], country: str | None) -> pd.DataFrame:
        arrays = [
            positions
            for key in keys
            if (positions := self._positions_by_key.get(key)) is not None
        ]
        if not arrays:
            return self._aliases.iloc[:0].copy()
        positions = arrays[0] if len(arrays) == 1 else np.sort(np.concatenate(arrays))
        if country is not None:
            positions = positions[self._alias_country[positions] == country]
        return self._aliases.iloc[positions].copy()
