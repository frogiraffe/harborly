"""Internal search and resolution services for port registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from sea_mile._registry_data import (
    _PROVIDER_PRIORITY,
    Port,
    PortSearchResult,
    _port_from_row,
    _port_priority,
)
from sea_mile._registry_validation import validate_limit
from sea_mile.exceptions import AmbiguousPortError, PortNotFoundError
from sea_mile.geo import great_circle_nmi

if TYPE_CHECKING:
    from sea_mile.ports import PortRegistry


def normalize_country_code(country_code: str | None) -> str | None:
    """Normalize a two-letter country code query."""
    if not country_code:
        return None
    code = country_code.strip().upper()
    return code if code else None


def normalize_unlocode(code: str) -> str:
    """Normalize a UN/LOCODE string by stripping whitespace and uppercasing."""
    return "".join(str(code).split()).upper()


def code_search_results(
    registry: PortRegistry, query: str, country_code: str | None
) -> list[PortSearchResult]:
    """Recognize a bare UN/LOCODE such as "TRMER" as a search query."""
    normalized_code = normalize_unlocode(query)
    if len(normalized_code) != 5:
        return []
    ports = registry.get_by_unlocode(normalized_code)
    normalized_country = normalize_country_code(country_code)
    if normalized_country:
        ports = [port for port in ports if port.country_code == normalized_country]
    return [
        PortSearchResult(
            port=port,
            matched_alias=normalized_code,
            match_method="exact_unlocode",
            name_score=100.0,
        )
        for port in ports
    ]


def search_results_from_candidates(
    registry: PortRegistry, candidate_aliases: pd.DataFrame, limit: int
) -> list[PortSearchResult]:
    """Rank candidate alias matches into final PortSearchResult objects."""
    if candidate_aliases.empty:
        return []
    candidates = candidate_aliases.merge(
        registry._registry,
        on=["registry_id", "provider"],
        how="inner",
        validate="many_to_one",
    )
    candidates["has_coordinates"] = (
        candidates[["latitude", "longitude"]].notna().all(axis=1)
    )
    candidates["provider_priority"] = (
        candidates["provider"].map(_PROVIDER_PRIORITY).fillna(99)
    )
    candidates = candidates.sort_values(
        [
            "name_score",
            "has_coordinates",
            "alias",
            "provider_priority",
            "registry_id",
        ],
        ascending=[False, False, True, True, True],
    ).drop_duplicates("registry_id")
    return [
        PortSearchResult(
            port=_port_from_row(row),
            matched_alias=str(row["alias"]),
            match_method=str(row["match_method"]),
            name_score=float(row["name_score"]),
        )
        for _, row in candidates.head(limit).iterrows()
    ]


def search_registry_uncached(
    registry: PortRegistry,
    query: str,
    *,
    country_code: str | None = None,
    limit: int = 10,
    fuzzy: bool = True,
    minimum_score: float = 75.0,
) -> list[PortSearchResult]:
    """Core search resolution without caching wrapper."""
    limit = validate_limit(limit)
    if not 0 <= minimum_score <= 100:
        raise ValueError("minimum_score must be between zero and 100")

    code_results = code_search_results(registry, query, country_code)
    if code_results:
        return code_results[:limit]

    candidates = registry._alias_search.candidates(
        query,
        country_code=country_code,
        limit=limit,
        fuzzy_enabled=fuzzy,
        minimum_score=minimum_score,
    )
    if not candidates.exact.empty:
        return search_results_from_candidates(registry, candidates.exact, limit)
    prefix_results = search_results_from_candidates(registry, candidates.prefix, limit)
    if len(prefix_results) >= limit:
        return prefix_results[:limit]

    fuzzy_results = search_results_from_candidates(registry, candidates.fuzzy, limit)

    seen: set[str] = set()
    merged: list[PortSearchResult] = []
    for result in (*prefix_results, *fuzzy_results):
        if result.port.registry_id in seen:
            continue
        seen.add(result.port.registry_id)
        merged.append(result)
        if len(merged) >= limit:
            break
    return merged


def preferred_same_identity(ports: list[Port], coordinate_agreement_nmi: float) -> Port:
    """Disambiguate multiple records sharing a common identity."""
    identity_codes = {port.unlocode for port in ports if port.unlocode}
    missing_identity = any(not port.unlocode for port in ports)
    if len(ports) > 1 and (len(identity_codes) != 1 or missing_identity):
        choices = ", ".join(port.registry_id for port in ports[:10])
        raise AmbiguousPortError(
            f"port request is ambiguous; choose an explicit registry ID: {choices}"
        )
    coordinate_ports = [port for port in ports if port.has_coordinates]
    disagreements = [
        great_circle_nmi(
            first.latitude,
            first.longitude,
            second.latitude,
            second.longitude,
        )
        for index, first in enumerate(coordinate_ports)
        for second in coordinate_ports[index + 1 :]
        if first.latitude is not None
        and first.longitude is not None
        and second.latitude is not None
        and second.longitude is not None
    ]
    if disagreements and max(disagreements) > coordinate_agreement_nmi:
        choices = ", ".join(port.registry_id for port in ports[:10])
        raise AmbiguousPortError(
            "sources sharing this identity disagree by up to "
            f"{max(disagreements):.1f} nmi; choose and review an explicit "
            f"registry ID: {choices}"
        )
    return sorted(ports, key=_port_priority)[0]


def resolve_port_uncached(
    registry: PortRegistry, query: str, *, country_code: str | None = None
) -> Port:
    """Resolve an exact port match or code to a single Port."""
    if query in registry._by_id.index:
        return registry.get(query)
    normalized_code = normalize_unlocode(query)
    if len(normalized_code) == 5:
        locode_ports = registry.get_by_unlocode(normalized_code)
        if locode_ports:
            return preferred_same_identity(
                locode_ports, registry._coordinate_agreement_nmi
            )

    results = registry._search_cached(
        query, country_code=country_code, fuzzy=False, limit=50
    )
    if not results:
        raise PortNotFoundError(
            f"no exact port match for {query!r}; use search() to inspect candidates"
        )
    return preferred_same_identity(
        [result.port for result in results], registry._coordinate_agreement_nmi
    )
