from __future__ import annotations

import asyncio
import threading

import pytest

from harborly import AsyncSeaRouter, Port


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


class _PausedEdgeRouter:
    def __init__(self) -> None:
        self.waiting = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()

    def iter_distance_edges(self, _ports, *, max_workers=None):
        try:
            yield (0, 1, 12.5)
            self.waiting.set()
            self.release.wait()
            yield (1, 0, 21.5)
        finally:
            self.closed.set()


class _ManyEdgeRouter:
    def __init__(self) -> None:
        self.steps = 0
        self.third_step = threading.Event()
        self.closed = threading.Event()

    def iter_distance_edges(self, _ports, *, max_workers=None):
        try:
            while True:
                self.steps += 1
                if self.steps == 3:
                    self.third_step.set()
                yield (self.steps, self.steps + 1, float(self.steps))
        finally:
            self.closed.set()


class _FailingEdgeRouter:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def iter_distance_edges(self, _ports, *, max_workers=None):
        yield (0, 1, 12.5)
        yield (1, 0, 21.5)
        raise self.error


class _ParityRouter:
    def __init__(self, result: object, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, ...]] = []

    def route_ids(self, registry, origin_id, destination_id):
        self.calls.append(("route_ids", registry, origin_id, destination_id))
        if self.error is not None:
            raise self.error
        return self.result

    def route_many(self, pairs):
        self.calls.append(("route_many", pairs))
        if self.error is not None:
            raise self.error
        return self.result

    def route_sequence(self, ports, *, speed_knots=None):
        self.calls.append(("route_sequence", ports, speed_knots))
        if self.error is not None:
            raise self.error
        return self.result


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
async def test_async_edge_iteration_yields_before_a_paused_producer_completes() -> None:
    sync_router = _PausedEdgeRouter()
    stream = AsyncSeaRouter(sync_router).iter_distance_edges([])
    first_edge = asyncio.create_task(anext(stream))
    heartbeat = asyncio.Event()

    try:
        await asyncio.wait_for(asyncio.to_thread(sync_router.waiting.wait), timeout=1)
        await asyncio.create_task(asyncio.sleep(0, result=heartbeat.set()))

        assert heartbeat.is_set()
        assert not sync_router.release.is_set()
        assert await asyncio.wait_for(asyncio.shield(first_edge), timeout=1) == (
            0,
            1,
            12.5,
        )
    finally:
        sync_router.release.set()
        await first_edge
        await stream.aclose()


@pytest.mark.anyio
async def test_async_edge_cancellation_does_not_wait_for_blocked_sync_next() -> None:
    sync_router = _PausedEdgeRouter()
    stream = AsyncSeaRouter(sync_router).iter_distance_edges([])

    try:
        assert await asyncio.wait_for(anext(stream), timeout=1) == (0, 1, 12.5)
        await asyncio.wait_for(asyncio.to_thread(sync_router.waiting.wait), timeout=1)

        blocked_read = asyncio.create_task(anext(stream))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(blocked_read), timeout=0.01)
        blocked_read.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(blocked_read, timeout=0.1)
    finally:
        sync_router.release.set()
        await asyncio.wait_for(asyncio.to_thread(sync_router.closed.wait), timeout=1)
        await stream.aclose()


@pytest.mark.anyio
async def test_async_edge_iteration_is_bounded_and_stops_after_close() -> None:
    sync_router = _ManyEdgeRouter()
    stream = AsyncSeaRouter(sync_router).iter_distance_edges([])

    assert await asyncio.wait_for(anext(stream), timeout=1) == (1, 2, 1.0)
    await asyncio.wait_for(asyncio.to_thread(sync_router.third_step.wait), timeout=1)
    assert sync_router.steps == 3

    await stream.aclose()
    await asyncio.wait_for(asyncio.to_thread(sync_router.closed.wait), timeout=1)

    assert sync_router.steps == 3


@pytest.mark.anyio
async def test_async_edge_iteration_preserves_order_and_exception_identity() -> None:
    error = RuntimeError("edge producer failed")
    stream = AsyncSeaRouter(_FailingEdgeRouter(error)).iter_distance_edges([])

    assert await anext(stream) == (0, 1, 12.5)
    assert await anext(stream) == (1, 0, 21.5)
    with pytest.raises(RuntimeError) as exc_info:
        await anext(stream)

    assert exc_info.value is error


@pytest.mark.anyio
async def test_async_router_route_ids_delegates_once_with_exact_result() -> None:
    registry = object()
    result = object()
    sync_router = _ParityRouter(result)

    assert (
        await AsyncSeaRouter(sync_router).route_ids(registry, "origin", "target")
        is result
    )
    assert sync_router.calls == [("route_ids", registry, "origin", "target")]


@pytest.mark.anyio
async def test_async_router_route_many_delegates_once_and_preserves_order() -> None:
    pairs = ((object(), object()), (object(), object()))
    result = [object(), object()]
    sync_router = _ParityRouter(result)

    assert await AsyncSeaRouter(sync_router).route_many(pairs) is result
    assert sync_router.calls == [("route_many", pairs)]


@pytest.mark.anyio
async def test_async_router_parity_delegates_preserve_exception_identity() -> None:
    route_ids_error = RuntimeError("route ids failed")
    with pytest.raises(RuntimeError) as route_ids_exc:
        await AsyncSeaRouter(_ParityRouter(object(), route_ids_error)).route_ids(
            object(), "origin", "target"
        )
    assert route_ids_exc.value is route_ids_error

    route_many_error = RuntimeError("route many failed")
    with pytest.raises(RuntimeError) as route_many_exc:
        await AsyncSeaRouter(_ParityRouter(object(), route_many_error)).route_many(())
    assert route_many_exc.value is route_many_error


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


@pytest.mark.anyio
async def test_async_router_route_sequence_delegates_once_with_exact_result() -> None:
    ports = (object(), object(), object())
    result = object()
    sync_router = _ParityRouter(result)

    assert (
        await AsyncSeaRouter(sync_router).route_sequence(ports, speed_knots=14.0)
        is result
    )
    assert sync_router.calls == [("route_sequence", ports, 14.0)]


@pytest.mark.anyio
async def test_async_router_route_sequence_preserves_exception_identity() -> None:
    error = RuntimeError("sequence failed")

    with pytest.raises(RuntimeError) as exc_info:
        await AsyncSeaRouter(_ParityRouter(object(), error)).route_sequence(())

    assert exc_info.value is error
