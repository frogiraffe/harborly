"""Public, source-aware access to a local multi-provider port registry."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from functools import cached_property, lru_cache
from math import isfinite
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from sea_mile.canonical import assign_canonical_ids
from sea_mile.exceptions import (
    AmbiguousPortError,
    PortCoordinateError,
    PortNotFoundError,
    RegistryDataError,
)
from sea_mile.matching import BatchMatchResult, decide_exact_match
from sea_mile.normalization import canonical_key
from sea_mile.quality import _EARTH_RADIUS_NMI, great_circle_nmi, validate_coordinate

try:
    from scipy.spatial import cKDTree
except ImportError:  # pragma: no cover - exercised only without the optional extra
    cKDTree = None  # type: ignore[assignment, misc]


_REGISTRY_COLUMNS = {
    "registry_id",
    "provider",
    "provider_id",
    "country_code",
    "canonical_name",
    "latitude",
    "longitude",
    "unlocode",
    "function_code",
    "source_version",
    "coordinate_resolution",
    "variant_count",
    "coordinate_conflict",
}
_ALIAS_COLUMNS = {"registry_id", "provider", "alias", "alias_key", "alias_type"}
_PROVIDER_PRIORITY = {
    "NGA_WPI": 0,
    "UN_LOCODE": 1,
    "GEONAMES": 2,
    "OPENSTREETMAP": 3,
}
_SOURCE_SHORT_LABELS = {
    "NGA_WPI": "WPI",
    "UN_LOCODE": "LOCODE",
    "GEONAMES": "GEO",
    "OPENSTREETMAP": "OSM",
}


def source_short_label(provider: str) -> str:
    """Return a compact display label for a provider name."""

    return _SOURCE_SHORT_LABELS.get(provider, provider)


_QUERY_CACHE_SIZE = 4096
# Below this length, fuzzy ranking over a global alias pool is not meaningful.
_MIN_FUZZY_QUERY_LENGTH = 3


def _positions_by_value(values: pd.Series) -> dict[str, np.ndarray]:
    """Map each non-null value to the integer row positions holding it.

    Faster than groupby(...).indices on Arrow-backed string columns.
    """

    codes, uniques = values.factorize(use_na_sentinel=True)
    if len(uniques) == 0:
        return {}
    order = np.argsort(codes, kind="stable")
    sorted_codes = codes[order]
    start = np.searchsorted(sorted_codes, 0, side="left")
    boundaries = np.flatnonzero(np.diff(sorted_codes[start:])) + 1
    groups = np.split(order[start:], boundaries)
    return {
        str(key): positions
        for key, positions in zip(uniques.tolist(), groups, strict=True)
    }


def _optional_text(value: object) -> str | None:
    return None if pd.isna(value) or str(value).strip() == "" else str(value)


def _optional_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    number = float(value)
    return number if isfinite(number) else None


@dataclass(frozen=True, slots=True)
class Port:
    """One provider-specific port record with explicit source provenance."""

    registry_id: str
    provider: str
    provider_id: str
    country_code: str
    name: str
    latitude: float | None
    longitude: float | None
    unlocode: str | None
    function_code: str | None
    source_version: str
    coordinate_resolution: str | None
    variant_count: int = 1
    coordinate_conflict: bool = False
    canonical_id: str = ""

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_geojson_feature(self) -> dict[str, Any]:
        if not self.has_coordinates:
            geometry = None
        else:
            geometry = {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude],
            }
        properties = self.to_dict()
        properties.pop("latitude")
        properties.pop("longitude")
        return {
            "type": "Feature",
            "id": self.registry_id,
            "properties": properties,
            "geometry": geometry,
        }


@dataclass(frozen=True, slots=True)
class PortSearchResult:
    """A port plus the alias evidence that produced a search result."""

    port: Port
    matched_alias: str
    match_method: str
    name_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.port.to_dict(),
            "matched_alias": self.matched_alias,
            "match_method": self.match_method,
            "name_score": self.name_score,
        }


@dataclass(frozen=True, slots=True)
class NearbyPortResult:
    """A port candidate ranked by great-circle distance from a query point."""

    port: Port
    distance_nmi: float

    def to_dict(self) -> dict[str, Any]:
        return {**self.port.to_dict(), "distance_nmi": self.distance_nmi}


@dataclass(frozen=True, slots=True)
class PortGroup:
    """One physical port, with the source records that describe it."""

    name: str
    country_code: str
    canonical_id: str
    unlocode: str | None
    members: tuple[Port, ...]
    sources: tuple[str, ...]
    latitude: float | None
    longitude: float | None
    coordinate_conflict: bool
    best_score: float
    match_method: str
    best_id: str

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "country_code": self.country_code,
            "canonical_id": self.canonical_id,
            "unlocode": self.unlocode,
            "sources": list(self.sources),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "coordinate_conflict": self.coordinate_conflict,
            "best_score": self.best_score,
            "match_method": self.match_method,
            "best_id": self.best_id,
            "members": [member.to_dict() for member in self.members],
        }


@dataclass(frozen=True, slots=True)
class NearbyPortGroup:
    """A grouped physical port ranked by distance from a query point."""

    group: PortGroup
    distance_nmi: float

    def to_dict(self) -> dict[str, Any]:
        return {**self.group.to_dict(), "distance_nmi": self.distance_nmi}


@dataclass(frozen=True, slots=True)
class _CoordinateIndex:
    """Precomputed arrays for vectorized nearest-port distance queries."""

    registry_id: np.ndarray
    country_code: np.ndarray
    provider_priority: np.ndarray
    lat_rad: np.ndarray
    lon_rad: np.ndarray
    cartesian: np.ndarray


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
        # A prebuilt registry stores canonical IDs. Compute them once here for a
        # frame that does not carry them yet.
        if "canonical_id" not in self._registry.columns:
            self._registry["canonical_id"] = assign_canonical_ids(
                self._registry, coordinate_agreement_nmi=coordinate_agreement_nmi
            )
        self._by_id = self._registry.set_index("registry_id", drop=False)
        self._coordinate_agreement_nmi = coordinate_agreement_nmi

        # Derived once here because the registry is immutable after construction.
        self._alias_country = (
            self._by_id["country_code"].reindex(self._aliases["registry_id"]).to_numpy()
        )
        self._alias_positions_by_key = _positions_by_value(self._aliases["alias_key"])
        self._distinct_alias_keys_global = list(self._alias_positions_by_key)
        key_countries = pd.DataFrame(
            {
                "country_code": self._alias_country,
                "alias_key": self._aliases["alias_key"].to_numpy(),
            }
        ).dropna(subset=["alias_key"])
        self._distinct_alias_keys_by_country: dict[str, list[str]] = {
            str(country): group["alias_key"].drop_duplicates().tolist()
            for country, group in key_countries.groupby("country_code")
        }
        self._registry_positions_by_unlocode = _positions_by_value(
            self._registry["unlocode"]
        )

        # Memoized per instance so repeated identical queries skip alias matching.
        self._resolve_cached = lru_cache(maxsize=_QUERY_CACHE_SIZE)(
            self._resolve_uncached
        )
        self._search_cached = lru_cache(maxsize=_QUERY_CACHE_SIZE)(
            self._search_uncached
        )

    @cached_property
    def _coordinate_index(self) -> _CoordinateIndex:
        # Built on first nearest() use, not at construction, so search-only and
        # route-only workflows do not pay for it.
        return self._build_coordinate_index()

    @cached_property
    def _kdtree(self) -> Any:
        index = self._coordinate_index
        if cKDTree is None or index.registry_id.shape[0] == 0:
            return None
        return cKDTree(index.cartesian)

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
        return cls.from_parquet(
            directory / "port_registry.parquet",
            directory / "port_aliases.parquet",
            coordinate_agreement_nmi=coordinate_agreement_nmi,
        )

    def __len__(self) -> int:
        return len(self._registry)

    def __contains__(self, registry_id: object) -> bool:
        return registry_id in self._by_id.index

    def __iter__(self) -> Iterator[Port]:
        for _, row in self._registry.iterrows():
            yield self._port_from_row(row)

    def ports(self) -> list[Port]:
        """Return every provider record as a Port."""

        return list(self)

    def ports_in_country(self, country_code: str) -> list[Port]:
        """Return the provider records for one country."""

        frame = self._registry[self._registry["country_code"] == country_code.upper()]
        return [self._port_from_row(row) for _, row in frame.iterrows()]

    def countries(self) -> list[str]:
        """Return the sorted two-letter country codes present in the registry."""

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
        return self._port_from_row(row)

    def get_by_unlocode(self, unlocode: str) -> list[Port]:
        code = "".join(str(unlocode).split()).upper()
        positions = self._registry_positions_by_unlocode.get(code)
        if positions is None:
            return []
        rows = self._registry.iloc[positions]
        ports = [self._port_from_row(row) for _, row in rows.iterrows()]
        return sorted(ports, key=self._port_priority)

    def search(
        self,
        query: str,
        *,
        country_code: str | None = None,
        limit: int = 10,
        fuzzy: bool = True,
        minimum_score: float = 75.0,
    ) -> list[PortSearchResult]:
        # Return a fresh list so a caller cannot mutate the cached one.
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
        """Search and collapse records that describe the same physical port."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        results = self._search_cached(
            query,
            country_code=country_code,
            limit=min(limit * 3, 600),
            fuzzy=fuzzy,
            minimum_score=minimum_score,
        )
        score_by_id = {result.port.registry_id: result for result in results}
        groups: list[PortGroup] = []
        for cluster in self._cluster_ports([result.port for result in results]):
            best = max(
                (score_by_id[port.registry_id] for port in cluster),
                key=lambda result: result.name_score,
            )
            groups.append(self._make_group(cluster, best.name_score, best.match_method))
        return groups[:limit]

    def _same_identity(self, first: Port, second: Port) -> bool:
        if first.unlocode and second.unlocode:
            return first.unlocode == second.unlocode
        if first.country_code != second.country_code:
            return False
        if canonical_key(first.name) != canonical_key(second.name):
            return False
        if (
            first.latitude is not None
            and first.longitude is not None
            and second.latitude is not None
            and second.longitude is not None
        ):
            distance = great_circle_nmi(
                first.latitude, first.longitude, second.latitude, second.longitude
            )
            return distance <= self._coordinate_agreement_nmi
        return True

    def _cluster_ports(self, ports: list[Port]) -> list[list[Port]]:
        clusters: list[list[Port]] = []
        for port in ports:
            for cluster in clusters:
                codes = {member.unlocode for member in cluster if member.unlocode}
                if port.unlocode and codes and port.unlocode not in codes:
                    # Merging would combine two different official codes.
                    continue
                if any(self._same_identity(port, member) for member in cluster):
                    cluster.append(port)
                    break
            else:
                clusters.append([port])
        return clusters

    def _make_group(
        self, members: list[Port], best_score: float, match_method: str
    ) -> PortGroup:
        members = sorted(members, key=self._port_priority)
        sources = tuple(
            dict.fromkeys(
                sorted(
                    (port.provider for port in members),
                    key=lambda provider: _PROVIDER_PRIORITY.get(provider, 99),
                )
            )
        )
        unlocode = next((port.unlocode for port in members if port.unlocode), None)
        canonical_id = next(
            (port.canonical_id for port in members if port.unlocode),
            members[0].canonical_id,
        )
        coordinate_ports = [port for port in members if port.has_coordinates]
        conflict = self._members_disagree(coordinate_ports)
        if conflict or not coordinate_ports:
            latitude = longitude = None
        else:
            latitude = coordinate_ports[0].latitude
            longitude = coordinate_ports[0].longitude
        return PortGroup(
            name=members[0].name,
            country_code=members[0].country_code,
            canonical_id=canonical_id,
            unlocode=unlocode,
            members=tuple(members),
            sources=sources,
            latitude=latitude,
            longitude=longitude,
            coordinate_conflict=conflict,
            best_score=best_score,
            match_method=match_method,
            best_id=members[0].registry_id,
        )

    def _members_disagree(self, coordinate_ports: list[Port]) -> bool:
        for index, first in enumerate(coordinate_ports):
            for second in coordinate_ports[index + 1 :]:
                if (
                    first.latitude is not None
                    and first.longitude is not None
                    and second.latitude is not None
                    and second.longitude is not None
                    and great_circle_nmi(
                        first.latitude,
                        first.longitude,
                        second.latitude,
                        second.longitude,
                    )
                    > self._coordinate_agreement_nmi
                ):
                    return True
        return False

    def nearest_grouped(
        self,
        latitude: float,
        longitude: float,
        *,
        country_code: str | None = None,
        limit: int = 10,
        max_distance_nmi: float | None = None,
    ) -> list[NearbyPortGroup]:
        """Nearest ports, collapsed so each physical port appears once."""

        raw = self.nearest(
            latitude,
            longitude,
            country_code=country_code,
            limit=min(limit * 3, 600),
            max_distance_nmi=max_distance_nmi,
        )
        distance_by_id = {
            result.port.registry_id: result.distance_nmi for result in raw
        }
        groups: list[NearbyPortGroup] = []
        for cluster in self._cluster_ports([result.port for result in raw]):
            distance = min(distance_by_id[port.registry_id] for port in cluster)
            groups.append(
                NearbyPortGroup(
                    group=self._make_group(cluster, 0.0, "nearest"),
                    distance_nmi=distance,
                )
            )
        groups.sort(key=lambda item: item.distance_nmi)
        return groups[:limit]

    def group_for(self, query: str, *, country_code: str | None = None) -> PortGroup:
        """Return the grouped port for a UN/LOCODE code or a registry ID."""

        normalized = "".join(str(query).split()).upper()
        coded = self.get_by_unlocode(normalized) if len(normalized) == 5 else []
        if coded:
            anchor = coded[0]
        elif query in self._by_id.index:
            anchor = self.get(query)
        else:
            raise PortNotFoundError(f"unknown port code or registry ID: {query}")
        exact = self._search_cached(
            anchor.name,
            country_code=country_code or anchor.country_code,
            fuzzy=False,
            limit=1000,
        )
        ports = [result.port for result in exact]
        if all(port.registry_id != anchor.registry_id for port in ports):
            ports.append(anchor)
        for cluster in self._cluster_ports(ports):
            if any(port.registry_id == anchor.registry_id for port in cluster):
                return self._make_group(cluster, 100.0, "exact")
        return self._make_group([anchor], 100.0, "exact")

    def resolve_canonical(self, canonical_id: str) -> PortGroup:
        """Return the grouped port for a stable canonical ID."""

        frame = self._registry[self._registry["canonical_id"] == canonical_id]
        if frame.empty:
            raise PortNotFoundError(f"unknown canonical ID: {canonical_id}")
        ports = [self._port_from_row(row) for _, row in frame.iterrows()]
        return self._make_group(ports, 100.0, "canonical")

    def match_names(
        self,
        names: Sequence[str],
        *,
        country_codes: Sequence[str | None] | None = None,
    ) -> list[BatchMatchResult]:
        """Resolve many port names in bulk, one decision per input name."""

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
            results.append(
                BatchMatchResult(
                    query=name,
                    country_code=country,
                    status=decision.status,
                    confidence_tier=decision.confidence_tier,
                    selected_registry_id=decision.selected_registry_id,
                    reason=decision.reason,
                )
            )
        return results

    def _search_uncached(
        self,
        query: str,
        *,
        country_code: str | None = None,
        limit: int = 10,
        fuzzy: bool = True,
        minimum_score: float = 75.0,
    ) -> list[PortSearchResult]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if not 0 <= minimum_score <= 100:
            raise ValueError("minimum_score must be between zero and 100")

        code_results = self._code_search_results(query, country_code)
        if code_results:
            # An exact code match is unambiguous, so skip name matching.
            return code_results[:limit]

        query_key = canonical_key(query)
        if not query_key:
            return []

        country = country_code.upper() if country_code else None
        if country:
            distinct_keys = self._distinct_alias_keys_by_country.get(country, [])
        else:
            distinct_keys = self._distinct_alias_keys_global

        exact = self._aliases_for_keys([query_key], country)
        if not exact.empty:
            exact["match_method"] = "exact_alias"
            exact["name_score"] = 100.0
            return self._search_results(exact, limit)
        if not fuzzy or not distinct_keys:
            return []

        # Prefix matching stays available at any length, with alphabetical ties.
        prefix_keys = [key for key in distinct_keys if key.startswith(query_key)]
        prefix_results: list[PortSearchResult] = []
        if prefix_keys:
            prefix_aliases = self._aliases_for_keys(prefix_keys, country)
            prefix_aliases["match_method"] = "prefix_alias"
            prefix_aliases["name_score"] = 95.0
            prefix_results = self._search_results(prefix_aliases, limit)
        if len(prefix_results) >= limit:
            return prefix_results[:limit]

        fuzzy_results: list[PortSearchResult] = []
        if len(query_key) >= _MIN_FUZZY_QUERY_LENGTH:
            # Drop aliases far shorter than the query. WRatio inflates their
            # partial-ratio score and crowds out real near-matches.
            min_alias_length = -(-len(query_key) // 2)  # ceil(len(query_key) / 2)
            prefix_key_set = set(prefix_keys)
            candidate_keys = [
                key
                for key in distinct_keys
                if len(key) >= min_alias_length and key not in prefix_key_set
            ]
            if candidate_keys:
                key_matches = process.extract(
                    query_key,
                    candidate_keys,
                    scorer=fuzz.WRatio,
                    score_cutoff=minimum_score,
                    limit=max(limit * 3, limit),
                )
                candidate_parts = []
                for alias_key, score, _ in key_matches:
                    part = self._aliases_for_keys([alias_key], country)
                    part["match_method"] = "fuzzy_alias"
                    part["name_score"] = float(score)
                    candidate_parts.append(part)
                if candidate_parts:
                    fuzzy_results = self._search_results(
                        pd.concat(candidate_parts), limit
                    )

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

    def _aliases_for_keys(self, keys: list[str], country: str | None) -> pd.DataFrame:
        """Alias rows for canonical keys, optionally restricted to one country."""

        arrays = [
            positions
            for key in keys
            if (positions := self._alias_positions_by_key.get(key)) is not None
        ]
        if not arrays:
            return self._aliases.iloc[:0].copy()
        positions = arrays[0] if len(arrays) == 1 else np.sort(np.concatenate(arrays))
        if country is not None:
            positions = positions[self._alias_country[positions] == country]
        return self._aliases.iloc[positions].copy()

    def _code_search_results(
        self, query: str, country_code: str | None
    ) -> list[PortSearchResult]:
        """Recognize a bare UN/LOCODE such as "TRMER" as a search query."""

        normalized_code = "".join(str(query).split()).upper()
        if len(normalized_code) != 5:
            return []
        ports = self.get_by_unlocode(normalized_code)
        if country_code:
            country = country_code.upper()
            ports = [port for port in ports if port.country_code == country]
        return [
            PortSearchResult(
                port=port,
                matched_alias=normalized_code,
                match_method="exact_unlocode",
                name_score=100.0,
            )
            for port in ports
        ]

    def resolve(self, query: str, *, country_code: str | None = None) -> Port:
        return self._resolve_cached(query, country_code=country_code)

    def _resolve_uncached(self, query: str, *, country_code: str | None = None) -> Port:
        if query in self._by_id.index:
            return self.get(query)
        normalized_code = "".join(str(query).split()).upper()
        if len(normalized_code) == 5:
            locode_ports = self.get_by_unlocode(normalized_code)
            if locode_ports:
                return self._preferred_same_identity(locode_ports)

        results = self._search_cached(
            query, country_code=country_code, fuzzy=False, limit=50
        )
        if not results:
            raise PortNotFoundError(
                f"no exact port match for {query!r}; use search() to inspect candidates"
            )
        return self._preferred_same_identity([result.port for result in results])

    def nearest(
        self,
        latitude: float,
        longitude: float,
        *,
        country_code: str | None = None,
        limit: int = 10,
        max_distance_nmi: float | None = None,
    ) -> list[NearbyPortResult]:
        """Return coordinate-bearing provider records nearest to a query point."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        if max_distance_nmi is not None and max_distance_nmi < 0:
            raise ValueError("max_distance_nmi must not be negative")
        query_check = validate_coordinate(latitude, longitude)
        if not query_check.is_valid:
            raise PortCoordinateError(f"invalid query coordinate: {query_check.reason}")

        index = self._coordinate_index
        positions = self._nearest_candidate_positions(
            latitude, longitude, country_code, limit
        )
        if positions.size == 0:
            return []

        lat1 = np.radians(latitude)
        lon1 = np.radians(longitude)
        lat2 = index.lat_rad[positions]
        lon2 = index.lon_rad[positions]
        haversine = (
            np.sin((lat2 - lat1) / 2) ** 2
            + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        )
        distance_nmi = (
            _EARTH_RADIUS_NMI * 2 * np.arcsin(np.sqrt(np.clip(haversine, 0.0, 1.0)))
        )
        registry_ids = index.registry_id[positions]
        provider_priority = index.provider_priority[positions]

        if max_distance_nmi is not None:
            within = distance_nmi <= max_distance_nmi
            distance_nmi = distance_nmi[within]
            registry_ids = registry_ids[within]
            provider_priority = provider_priority[within]
        if distance_nmi.size == 0:
            return []

        # lexsort reads keys last-first: distance, then provider, then id.
        order = np.lexsort((registry_ids, provider_priority, distance_nmi))[:limit]
        return [
            NearbyPortResult(
                port=self._port_from_row(self._by_id.loc[registry_ids[i]]),
                distance_nmi=float(distance_nmi[i]),
            )
            for i in order
        ]

    def _nearest_candidate_positions(
        self,
        latitude: float,
        longitude: float,
        country_code: str | None,
        limit: int,
    ) -> np.ndarray:
        """Positions into _coordinate_index worth scoring exactly.

        The k-d tree narrows the unfiltered case to a small candidate set.
        An overfetch margin, widened by a radius query, keeps every
        exact-distance tie so the tie-break below sees them. A country filter
        uses the full vectorized scan.
        """

        index = self._coordinate_index
        n = index.registry_id.shape[0]
        if self._kdtree is not None and country_code is None:
            point = _EARTH_RADIUS_NMI * np.array(
                [
                    np.cos(np.radians(latitude)) * np.cos(np.radians(longitude)),
                    np.cos(np.radians(latitude)) * np.sin(np.radians(longitude)),
                    np.sin(np.radians(latitude)),
                ]
            )
            k = min(limit + 8, n)
            if k == 0:
                return np.array([], dtype=np.intp)
            distances, found = self._kdtree.query(point, k=k)
            distances = np.atleast_1d(distances)
            found = np.atleast_1d(found)
            if k < n:
                wider = self._kdtree.query_ball_point(point, r=distances[-1] + 1e-6)
                if len(wider) > found.size:
                    found = np.asarray(wider, dtype=np.intp)
            return found

        mask = np.ones(n, dtype=bool)
        if country_code:
            mask &= index.country_code == country_code.upper()
        return np.nonzero(mask)[0]

    def _build_coordinate_index(self) -> _CoordinateIndex:
        frame = self._registry.dropna(subset=["latitude", "longitude"])
        latitude = frame["latitude"].to_numpy(dtype=float)
        longitude = frame["longitude"].to_numpy(dtype=float)
        # Vectorized equivalent of validate_coordinate() over float pairs.
        valid = (
            np.isfinite(latitude)
            & np.isfinite(longitude)
            & (np.abs(latitude) <= 90)
            & (np.abs(longitude) <= 180)
            & ~((latitude == 0.0) & (longitude == 0.0))
        )
        frame = frame[valid]
        provider_priority = (
            frame["provider"].map(_PROVIDER_PRIORITY).fillna(99).to_numpy(dtype=float)
        )
        lat_rad = np.radians(frame["latitude"].to_numpy(dtype=float))
        lon_rad = np.radians(frame["longitude"].to_numpy(dtype=float))
        # Chord order on the sphere matches great-circle order, so a Euclidean
        # k-d tree over these points answers nearest-port queries correctly.
        cartesian = _EARTH_RADIUS_NMI * np.column_stack(
            (
                np.cos(lat_rad) * np.cos(lon_rad),
                np.cos(lat_rad) * np.sin(lon_rad),
                np.sin(lat_rad),
            )
        )
        return _CoordinateIndex(
            registry_id=frame["registry_id"].to_numpy(),
            country_code=frame["country_code"].to_numpy(),
            provider_priority=provider_priority,
            lat_rad=lat_rad,
            lon_rad=lon_rad,
            cartesian=cartesian,
        )

    def _search_results(
        self, candidate_aliases: pd.DataFrame, limit: int
    ) -> list[PortSearchResult]:
        candidates = candidate_aliases.merge(
            self._registry,
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
                port=self._port_from_row(row),
                matched_alias=str(row["alias"]),
                match_method=str(row["match_method"]),
                name_score=float(row["name_score"]),
            )
            for _, row in candidates.head(limit).iterrows()
        ]

    def _preferred_same_identity(self, ports: list[Port]) -> Port:
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
        if disagreements and max(disagreements) > self._coordinate_agreement_nmi:
            choices = ", ".join(port.registry_id for port in ports[:10])
            raise AmbiguousPortError(
                "sources sharing this identity disagree by up to "
                f"{max(disagreements):.1f} nmi; choose and review an explicit "
                f"registry ID: {choices}"
            )
        return sorted(ports, key=self._port_priority)[0]

    @staticmethod
    def _port_priority(port: Port) -> tuple[int, int, str]:
        return (
            0 if port.has_coordinates else 1,
            _PROVIDER_PRIORITY.get(port.provider, 99),
            port.registry_id,
        )

    @staticmethod
    def _port_from_row(row: pd.Series) -> Port:
        return Port(
            registry_id=str(row["registry_id"]),
            provider=str(row["provider"]),
            provider_id=str(row["provider_id"]),
            country_code=str(row["country_code"]),
            name=str(row["canonical_name"]),
            latitude=_optional_float(row["latitude"]),
            longitude=_optional_float(row["longitude"]),
            unlocode=_optional_text(row["unlocode"]),
            function_code=_optional_text(row["function_code"]),
            source_version=str(row["source_version"]),
            coordinate_resolution=_optional_text(row["coordinate_resolution"]),
            variant_count=int(row["variant_count"]),
            coordinate_conflict=bool(row["coordinate_conflict"]),
            canonical_id=str(row["canonical_id"]),
        )
