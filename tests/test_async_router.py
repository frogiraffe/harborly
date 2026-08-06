from __future__ import annotations

import pytest

from sea_mile import AsyncSeaRouter, Port


def make_port(registry_id: str, name: str, latitude: float, longitude: float) -> Port:
    return Port(
        registry_id=registry_id,
        provider="TEST",
        provider_id=registry_id,
        country_code="TR",
        name=name,
        latitude=latitude,
        longitude=longitude,
        unlocode=None,
        function_code="port",
        source_version="test",
        coordinate_resolution="test",
    )


@pytest.mark.anyio
async def test_async_router_route() -> None:
    origin = make_port("TEST:1", "Mersin", 36.8, 34.65)
    destination = make_port("TEST:2", "Piraeus", 37.94, 23.63)

    async_router = AsyncSeaRouter()
    route = await async_router.route(origin, destination)

    assert route.distance_nmi > 0
    assert route.great_circle_nmi > 0


@pytest.mark.anyio
async def test_async_router_route_coordinates() -> None:
    async_router = AsyncSeaRouter()
    route = await async_router.route_coordinates(36.8, 34.65, 37.94, 23.63)

    assert route.distance_nmi > 0


@pytest.mark.anyio
async def test_async_router_distance_matrix() -> None:
    origin = make_port("TEST:1", "Mersin", 36.8, 34.65)
    destination = make_port("TEST:2", "Piraeus", 37.94, 23.63)

    async_router = AsyncSeaRouter()
    matrix = await async_router.distance_matrix([origin, destination])

    assert len(matrix) == 2
    assert matrix[0][0] == 0.0
    assert matrix[1][1] == 0.0
    assert matrix[0][1] > 0


@pytest.mark.anyio
async def test_async_router_iter_distance_edges() -> None:
    origin = make_port("TEST:1", "Mersin", 36.8, 34.65)
    destination = make_port("TEST:2", "Piraeus", 37.94, 23.63)

    async_router = AsyncSeaRouter()
    edges = []
    async for edge in async_router.iter_distance_edges([origin, destination]):
        edges.append(edge)

    assert len(edges) == 1
    row, col, dist = edges[0]
    assert (row, col) == (0, 1)
    assert dist > 0


@pytest.mark.anyio
async def test_async_router_check_ready() -> None:
    async_router = AsyncSeaRouter()
    checks = await async_router.check_ready()

    assert len(checks) >= 2


@pytest.mark.anyio
async def test_async_router_route_sequence() -> None:
    port_a = make_port("TEST:1", "Mersin", 36.8, 34.65)
    port_b = make_port("TEST:2", "Piraeus", 37.94, 23.63)
    port_c = make_port("TEST:3", "Istanbul", 41.0, 28.97)

    async_router = AsyncSeaRouter()
    seq = await async_router.route_sequence([port_a, port_b, port_c])

    assert len(seq.legs) == 2
    assert seq.total_distance_nmi > 0
