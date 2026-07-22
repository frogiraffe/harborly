from __future__ import annotations

import json

import pytest

from sea_mile.matching import BatchMatchResult, ConfidenceTier, MatchStatus
from sea_mile.ports import (
    NearbyPortGroup,
    NearbyPortResult,
    Port,
    PortGroup,
    PortSearchResult,
)
from sea_mile.router import SeaRoute


def _port() -> Port:
    return Port(
        registry_id="WPI:1",
        provider="NGA_WPI",
        provider_id="1",
        country_code="TR",
        name="Mersin",
        latitude=36.8,
        longitude=34.65,
        unlocode="TRMER",
        function_code="port",
        source_version="test",
        coordinate_resolution="arc_second",
        variant_count=1,
        coordinate_conflict=False,
        canonical_id="TRMER",
    )


def _group() -> PortGroup:
    port = _port()
    return PortGroup(
        name=port.name,
        country_code=port.country_code,
        canonical_id="TRMER",
        unlocode="TRMER",
        members=(port,),
        sources=("NGA_WPI",),
        latitude=port.latitude,
        longitude=port.longitude,
        coordinate_conflict=False,
        best_score=100.0,
        match_method="exact",
        best_id=port.registry_id,
    )


def _route() -> SeaRoute:
    port = _port()
    return SeaRoute(
        origin=port,
        destination=port,
        distance_nmi=1.0,
        great_circle_nmi=1.0,
        detour_ratio=1.0,
        quality_flag="ok",
        geometry={"type": "LineString", "coordinates": [[34.65, 36.8], [34.65, 36.8]]},
        engine="searoute",
        engine_version="1.6.0",
        algorithm="astar",
        backend="networkx",
        restrictions=("northwest",),
    )


MODEL_DICTS = [
    _port().to_dict(),
    PortSearchResult(_port(), "Mersin", "exact_alias", 100.0).to_dict(),
    NearbyPortResult(_port(), 1.5).to_dict(),
    _group().to_dict(),
    NearbyPortGroup(_group(), 1.5).to_dict(),
    BatchMatchResult(
        "Mersin", "TR", MatchStatus.AUTO_RESOLVED, ConfidenceTier.A, "WPI:1", "reason"
    ).to_dict(),
    _route().summary(),
]


@pytest.mark.parametrize("payload", MODEL_DICTS)
def test_model_dict_is_json_native_and_stable(payload) -> None:
    # A dict that survives a JSON round-trip unchanged holds no tuples, enums,
    # numpy scalars, or other values the envelope cannot serialize faithfully.
    assert json.loads(json.dumps(payload)) == payload


def test_port_round_trips_through_its_dict() -> None:
    port = _port()
    assert Port(**port.to_dict()) == port
