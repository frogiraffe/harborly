"""Internal registry spatial, clustering, and grouping services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from harborly._registry_data import (
    _PROVIDER_PRIORITY,
    NearbyPortGroup,
    NearbyPortResult,
    Port,
    PortGroup,
    _port_from_row,
    _port_priority,
)
from harborly._registry_search import normalize_unlocode
from harborly._registry_validation import validate_limit
from harborly.exceptions import (
    PortCoordinateError,
    PortNotFoundError,
)
from harborly.geo import great_circle_nmi, validate_coordinate
from harborly.text import canonical_key

if TYPE_CHECKING:
    from harborly.ports import PortRegistry


def same_identity(first: Port, second: Port, coordinate_agreement_nmi: float) -> bool:
    """Check if two port records describe the same physical identity."""
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
        return distance <= coordinate_agreement_nmi
    return True


def cluster_ports(
    ports: list[Port], coordinate_agreement_nmi: float
) -> list[list[Port]]:
    """Cluster related provider port records into physical port groups."""
    clusters: list[list[Port]] = []
    for port in ports:
        for cluster in clusters:
            codes = {member.unlocode for member in cluster if member.unlocode}
            if port.unlocode and codes and port.unlocode not in codes:
                continue
            if any(
                same_identity(port, member, coordinate_agreement_nmi)
                for member in cluster
            ):
                cluster.append(port)
                break
        else:
            clusters.append([port])
    return clusters


def members_disagree(
    coordinate_ports: list[Port], coordinate_agreement_nmi: float
) -> bool:
    """Check if coordinate-bearing group members disagree beyond tolerance."""
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
                > coordinate_agreement_nmi
            ):
                return True
    return False


def make_port_group(
    members: list[Port],
    best_score: float,
    match_method: str,
    coordinate_agreement_nmi: float,
) -> PortGroup:
    """Assemble a PortGroup object from clustered member records."""
    members = sorted(members, key=_port_priority)
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
    conflict = members_disagree(coordinate_ports, coordinate_agreement_nmi)
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


def search_grouped_ports(
    registry: PortRegistry,
    query: str,
    *,
    country_code: str | None = None,
    limit: int = 10,
    fuzzy: bool = True,
    minimum_score: float = 75.0,
) -> list[PortGroup]:
    """Search and collapse records that describe the same physical port."""
    limit = validate_limit(limit)
    results = registry._search_cached(
        query,
        country_code=country_code,
        limit=min(limit * 3, 600),
        fuzzy=fuzzy,
        minimum_score=minimum_score,
    )
    score_by_id = {result.port.registry_id: result for result in results}
    groups: list[PortGroup] = []
    for cluster in cluster_ports(
        [result.port for result in results], registry._coordinate_agreement_nmi
    ):
        best = max(
            (score_by_id[port.registry_id] for port in cluster),
            key=lambda result: result.name_score,
        )
        groups.append(
            make_port_group(
                cluster,
                best.name_score,
                best.match_method,
                registry._coordinate_agreement_nmi,
            )
        )
    return groups[:limit]


def nearest_ports(
    registry: PortRegistry,
    latitude: float,
    longitude: float,
    *,
    country_code: str | None = None,
    limit: int = 10,
    max_distance_nmi: float | None = None,
) -> list[NearbyPortResult]:
    """Return provider records nearest to a query point."""
    limit = validate_limit(limit)
    if max_distance_nmi is not None and max_distance_nmi < 0:
        raise ValueError("max_distance_nmi must not be negative")
    query_check = validate_coordinate(latitude, longitude)
    if not query_check.is_valid:
        raise PortCoordinateError(f"invalid query coordinate: {query_check.reason}")

    return [
        NearbyPortResult(
            port=_port_from_row(registry._by_id.loc[match.registry_id]),
            distance_nmi=match.distance_nmi,
        )
        for match in registry._spatial_index.nearest(
            latitude,
            longitude,
            country_code=country_code,
            limit=limit,
            max_distance_nmi=max_distance_nmi,
        )
    ]


def nearest_grouped_ports(
    registry: PortRegistry,
    latitude: float,
    longitude: float,
    *,
    country_code: str | None = None,
    limit: int = 10,
    max_distance_nmi: float | None = None,
) -> list[NearbyPortGroup]:
    """Nearest ports, collapsed so each physical port appears once."""
    limit = validate_limit(limit)
    raw = registry.nearest(
        latitude,
        longitude,
        country_code=country_code,
        limit=min(limit * 3, 600),
        max_distance_nmi=max_distance_nmi,
    )
    distance_by_id = {result.port.registry_id: result.distance_nmi for result in raw}
    groups: list[NearbyPortGroup] = []
    for cluster in cluster_ports(
        [result.port for result in raw], registry._coordinate_agreement_nmi
    ):
        distance = min(distance_by_id[port.registry_id] for port in cluster)
        groups.append(
            NearbyPortGroup(
                group=make_port_group(
                    cluster, 0.0, "nearest", registry._coordinate_agreement_nmi
                ),
                distance_nmi=distance,
            )
        )
    groups.sort(key=lambda item: item.distance_nmi)
    return groups[:limit]


def group_for_query(
    registry: PortRegistry, query: str, *, country_code: str | None = None
) -> PortGroup:
    """Return the grouped port for a UN/LOCODE code or a registry ID."""
    normalized = normalize_unlocode(query)
    coded = registry.get_by_unlocode(normalized) if len(normalized) == 5 else []
    if coded:
        anchor = coded[0]
    elif query in registry._by_id.index:
        anchor = registry.get(query)
    else:
        raise PortNotFoundError(f"unknown port code or registry ID: {query}")
    exact = registry._search_cached(
        anchor.name,
        country_code=country_code or anchor.country_code,
        fuzzy=False,
        limit=1000,
    )
    ports = [result.port for result in exact]
    if all(port.registry_id != anchor.registry_id for port in ports):
        ports.append(anchor)
    for cluster in cluster_ports(ports, registry._coordinate_agreement_nmi):
        if any(port.registry_id == anchor.registry_id for port in cluster):
            return make_port_group(
                cluster, 100.0, "exact", registry._coordinate_agreement_nmi
            )
    return make_port_group([anchor], 100.0, "exact", registry._coordinate_agreement_nmi)


def resolve_canonical_group(registry: PortRegistry, canonical_id: str) -> PortGroup:
    """Return the grouped port for a stable canonical ID."""
    frame = registry._registry[registry._registry["canonical_id"] == canonical_id]
    if frame.empty:
        raise PortNotFoundError(f"unknown canonical ID: {canonical_id}")
    ports = [_port_from_row(row) for _, row in frame.iterrows()]
    return make_port_group(
        ports, 100.0, "canonical", registry._coordinate_agreement_nmi
    )
