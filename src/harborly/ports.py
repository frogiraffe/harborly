"""Public, source-aware access to a local multi-provider port registry."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from functools import lru_cache
from pathlib import Path

import pandas as pd

from harborly._registry_data import (
    _ALIAS_COLUMNS,
    _ENRICHMENT_FIELDS,
    _PROVIDER_PRIORITY,
    _QUERY_CACHE_SIZE,
    _REGISTRY_COLUMNS,
    NearbyPortGroup,
    NearbyPortResult,
    Port,
    PortGroup,
    PortSearchResult,
    _port_from_row,
    _port_priority,
    _positions_by_value,
    _result_enrichment,
    _series_cell,
    _validate_registry_schema,
    bundled_data_directory,
    source_short_label,
)
from harborly._registry_search import (
    resolve_port_uncached,
    search_registry_uncached,
)
from harborly._registry_services import (
    group_for_query,
    nearest_grouped_ports,
    nearest_ports,
    resolve_canonical_group,
    search_grouped_ports,
)
from harborly.canonical import assign_canonical_ids
from harborly.exceptions import (
    PortNotFoundError,
    RegistryDataError,
)
from harborly.matching import (
    BatchMatchResult,
    MatchCandidate,
    MatchPolicy,
    MatchReason,
    MatchStatus,
    decide_exact_match,
)
from harborly.search import AliasSearchIndex
from harborly.spatial import PortSpatialIndex


def _match_candidates(
    results: Sequence[PortSearchResult],
) -> tuple[MatchCandidate, ...]:
    """Carry each search hit into review evidence, keeping how it was found."""

    return tuple(
        MatchCandidate(
            registry_id=result.port.registry_id,
            provider=result.port.provider,
            name=result.port.name,
            country_code=result.port.country_code,
            latitude=result.port.latitude,
            longitude=result.port.longitude,
            unlocode=result.port.unlocode,
            match_method=result.match_method,
            name_score=result.name_score,
        )
        for result in results
    )


class PortRegistry:
    """Search and resolve ports from locally stored normalized snapshots."""

    def __init__(
        self,
        registry: pd.DataFrame,
        aliases: pd.DataFrame,
        *,
        coordinate_agreement_nmi: float = 25.0,
    ) -> None:
        if coordinate_agreement_nmi < 0:
            raise ValueError("coordinate_agreement_nmi must not be negative")
        missing_registry = _REGISTRY_COLUMNS - set(registry.columns)
        missing_aliases = _ALIAS_COLUMNS - set(aliases.columns)
        if missing_registry or missing_aliases:
            raise RegistryDataError(
                "registry schema is incomplete: "
                f"registry={sorted(missing_registry)}, "
                f"aliases={sorted(missing_aliases)}"
            )
        if registry["registry_id"].duplicated().any():
            raise RegistryDataError("registry_id must be unique after reconciliation")
        unknown_alias_ids = set(aliases["registry_id"]) - set(registry["registry_id"])
        if unknown_alias_ids:
            raise RegistryDataError(
                f"aliases reference {len(unknown_alias_ids)} unknown registry IDs"
            )
        self._registry = registry.copy()
        self._aliases = aliases.copy()
        if "canonical_id" not in self._registry.columns:
            self._registry["canonical_id"] = assign_canonical_ids(
                self._registry, coordinate_agreement_nmi=coordinate_agreement_nmi
            )
        self._by_id = self._registry.set_index("registry_id", drop=False)
        self._coordinate_agreement_nmi = coordinate_agreement_nmi

        self._alias_country = (
            self._by_id["country_code"].reindex(self._aliases["registry_id"]).to_numpy()
        )
        alias_positions = _positions_by_value(self._aliases["alias_key"])
        self._alias_search = AliasSearchIndex(
            self._aliases,
            alias_country=self._alias_country,
            positions_by_key=alias_positions,
        )
        self._registry_positions_by_unlocode = _positions_by_value(
            self._registry["unlocode"]
        )
        self._spatial_index_lock = threading.Lock()
        self._spatial_index_value: PortSpatialIndex | None = None

        self._resolve_cached = lru_cache(maxsize=_QUERY_CACHE_SIZE)(
            self._resolve_uncached
        )
        self._search_cached = lru_cache(maxsize=_QUERY_CACHE_SIZE)(
            self._search_uncached
        )

    @property
    def _spatial_index(self) -> PortSpatialIndex:
        index = self._spatial_index_value
        if index is None:
            with self._spatial_index_lock:
                index = self._spatial_index_value
                if index is None:
                    index = PortSpatialIndex(
                        self._registry, provider_priority=_PROVIDER_PRIORITY
                    )
                    self._spatial_index_value = index
        return index

    @classmethod
    def from_parquet(
        cls,
        registry_path: str | Path,
        aliases_path: str | Path,
        *,
        coordinate_agreement_nmi: float = 25.0,
    ) -> PortRegistry:
        registry_path = Path(registry_path)
        aliases_path = Path(aliases_path)
        if not registry_path.exists() or not aliases_path.exists():
            raise RegistryDataError(
                "registry files are missing; build or download port_registry.parquet "
                "and port_aliases.parquet first"
            )
        return cls(
            pd.read_parquet(registry_path),
            pd.read_parquet(aliases_path),
            coordinate_agreement_nmi=coordinate_agreement_nmi,
        )

    @classmethod
    def from_directory(
        cls,
        directory: str | Path,
        *,
        coordinate_agreement_nmi: float = 25.0,
    ) -> PortRegistry:
        directory = Path(directory)
        _validate_registry_schema(directory / "registry_manifest.json")
        return cls.from_parquet(
            directory / "port_registry.parquet",
            directory / "port_aliases.parquet",
            coordinate_agreement_nmi=coordinate_agreement_nmi,
        )

    @classmethod
    def bundled(cls, *, coordinate_agreement_nmi: float = 25.0) -> PortRegistry:
        """Load the registry distributed with harborly."""
        return cls.from_directory(
            bundled_data_directory(),
            coordinate_agreement_nmi=coordinate_agreement_nmi,
        )

    def __len__(self) -> int:
        return len(self._registry)

    def __contains__(self, registry_id: object) -> bool:
        return registry_id in self._by_id.index

    def __iter__(self) -> Iterator[Port]:
        for _, row in self._registry.iterrows():
            yield _port_from_row(row)

    def ports(self) -> list[Port]:
        return list(self)

    def ports_in_country(self, country_code: str) -> list[Port]:
        frame = self._registry[self._registry["country_code"] == country_code.upper()]
        return [_port_from_row(row) for _, row in frame.iterrows()]

    def countries(self) -> list[str]:
        codes = self._registry["country_code"].dropna().unique()
        return sorted(code for code in codes if code)

    @property
    def providers(self) -> dict[str, int]:
        counts = self._registry["provider"].value_counts()
        return {
            str(provider): int(counts[provider])
            for provider in sorted(
                counts.index, key=lambda name: _PROVIDER_PRIORITY.get(name, 99)
            )
        }

    def get(self, registry_id: str) -> Port:
        try:
            row = self._by_id.loc[registry_id]
        except KeyError as error:
            raise PortNotFoundError(
                f"unknown port registry ID: {registry_id}"
            ) from error
        return _port_from_row(row)

    def get_by_unlocode(self, unlocode: str) -> list[Port]:
        code = "".join(str(unlocode).split()).upper()
        positions = self._registry_positions_by_unlocode.get(code)
        if positions is None:
            return []
        rows = self._registry.iloc[positions]
        ports = [_port_from_row(row) for _, row in rows.iterrows()]
        return sorted(ports, key=_port_priority)

    def search(
        self,
        query: str,
        *,
        country_code: str | None = None,
        limit: int = 10,
        fuzzy: bool = True,
        minimum_score: float = 75.0,
    ) -> list[PortSearchResult]:
        return list(
            self._search_cached(
                query,
                country_code=country_code,
                limit=limit,
                fuzzy=fuzzy,
                minimum_score=minimum_score,
            )
        )

    def search_grouped(
        self,
        query: str,
        *,
        country_code: str | None = None,
        limit: int = 10,
        fuzzy: bool = True,
        minimum_score: float = 75.0,
    ) -> list[PortGroup]:
        return search_grouped_ports(
            self,
            query,
            country_code=country_code,
            limit=limit,
            fuzzy=fuzzy,
            minimum_score=minimum_score,
        )

    def nearest_grouped(
        self,
        latitude: float,
        longitude: float,
        *,
        country_code: str | None = None,
        limit: int = 10,
        max_distance_nmi: float | None = None,
    ) -> list[NearbyPortGroup]:
        return nearest_grouped_ports(
            self,
            latitude,
            longitude,
            country_code=country_code,
            limit=limit,
            max_distance_nmi=max_distance_nmi,
        )

    def group_for(self, query: str, *, country_code: str | None = None) -> PortGroup:
        return group_for_query(self, query, country_code=country_code)

    def resolve_canonical(self, canonical_id: str) -> PortGroup:
        return resolve_canonical_group(self, canonical_id)

    def match_names(
        self,
        names: Sequence[str],
        *,
        country_codes: Sequence[str | None] | None = None,
        policy: MatchPolicy | None = None,
    ) -> list[BatchMatchResult]:
        active_policy = policy if policy is not None else MatchPolicy()
        results: list[BatchMatchResult] = []
        for index, name in enumerate(names):
            country = country_codes[index] if country_codes is not None else None
            exact = self._search_cached(
                name, country_code=country, fuzzy=False, limit=50
            )
            coordinates: dict[str, tuple[float, float]] = {}
            for result in exact:
                latitude = result.port.latitude
                longitude = result.port.longitude
                if latitude is not None and longitude is not None:
                    coordinates[result.port.registry_id] = (latitude, longitude)
            wpi_ids = [
                result.port.registry_id
                for result in exact
                if result.port.provider == "NGA_WPI"
            ]
            unlocode_ids = [
                result.port.registry_id
                for result in exact
                if result.port.provider == "UN_LOCODE"
                and result.port.registry_id in coordinates
            ]
            decision = decide_exact_match(
                wpi_ids,
                unlocode_ids,
                coordinates_by_registry_id=coordinates,
            )
            candidates = _match_candidates(exact)
            status = decision.status
            reason_code = decision.reason_code
            reason = decision.reason
            if not candidates and status is MatchStatus.UNRESOLVED:
                # Fuzzy evidence never auto-resolves; it only gives a reviewer
                # something to choose from where there was previously nothing.
                candidates = _match_candidates(
                    self._search_cached(
                        name,
                        country_code=country,
                        fuzzy=True,
                        limit=active_policy.max_strong_candidates,
                        minimum_score=active_policy.fuzzy_score_cutoff,
                    )
                )
                if candidates:
                    status = MatchStatus.REVIEW_REQUIRED
                    reason_code = MatchReason.FUZZY_CANDIDATES_ONLY
                    reason = "no exact official match; fuzzy candidates need review"
            results.append(
                BatchMatchResult(
                    query=name,
                    country_code=country,
                    status=status,
                    confidence_tier=decision.confidence_tier,
                    selected_registry_id=decision.selected_registry_id,
                    reason_code=reason_code,
                    reason=reason,
                    rules_applied=decision.rules_applied,
                    candidates=candidates,
                )
            )
        return results

    def match_series(
        self,
        names: pd.Series,
        *,
        country_codes: pd.Series | None = None,
    ) -> list[BatchMatchResult]:
        resolved_names = [_series_cell(value) for value in names]
        resolved_countries: list[str | None] | None = None
        if country_codes is not None:
            resolved_countries = [
                (_series_cell(value) or None) for value in country_codes
            ]
        return self.match_names(resolved_names, country_codes=resolved_countries)

    def match_dataframe(
        self,
        frame: pd.DataFrame,
        *,
        name_column: str,
        country_column: str | None = None,
    ) -> pd.DataFrame:
        if name_column not in frame.columns:
            raise KeyError(f"frame has no column {name_column!r}")
        if country_column is not None and country_column not in frame.columns:
            raise KeyError(f"frame has no column {country_column!r}")
        countries = frame[country_column] if country_column is not None else None
        results = self.match_series(frame[name_column], country_codes=countries)
        columns: dict[str, list[object]] = {field: [] for field in _ENRICHMENT_FIELDS}
        for result in results:
            fields = _result_enrichment(self, result)
            for field in _ENRICHMENT_FIELDS:
                columns[field].append(fields[field])
        enriched = frame.copy()
        for field in _ENRICHMENT_FIELDS:
            enriched[field] = columns[field]
        return enriched

    def _search_uncached(
        self,
        query: str,
        *,
        country_code: str | None = None,
        limit: int = 10,
        fuzzy: bool = True,
        minimum_score: float = 75.0,
    ) -> list[PortSearchResult]:
        return search_registry_uncached(
            self,
            query,
            country_code=country_code,
            limit=limit,
            fuzzy=fuzzy,
            minimum_score=minimum_score,
        )

    def resolve(self, query: str, *, country_code: str | None = None) -> Port:
        return self._resolve_cached(query, country_code=country_code)

    def _resolve_uncached(self, query: str, *, country_code: str | None = None) -> Port:
        return resolve_port_uncached(self, query, country_code=country_code)

    def nearest(
        self,
        latitude: float,
        longitude: float,
        *,
        country_code: str | None = None,
        limit: int = 10,
        max_distance_nmi: float | None = None,
    ) -> list[NearbyPortResult]:
        return nearest_ports(
            self,
            latitude,
            longitude,
            country_code=country_code,
            limit=limit,
            max_distance_nmi=max_distance_nmi,
        )


__all__ = [
    "NearbyPortGroup",
    "NearbyPortResult",
    "Port",
    "PortGroup",
    "PortRegistry",
    "PortSearchResult",
    "bundled_data_directory",
    "source_short_label",
]
