"""Liveness answers "is the process up"; readiness answers "can it serve".

Liveness only ever answers the first question, so a server missing the
routing extra reported itself healthy and then failed every route request with
a 503. A supervisor watching that endpoint had no way to tell the difference.
"""

from __future__ import annotations

from typing import NoReturn

import httpx
import pytest

from harborly.router import SeaRouter
from harborly.routing import CacheFailurePolicy, ReadinessCheck

pytest.importorskip("fastapi", reason="tests the optional 'api' extra")

from test_ports import alias_frame, registry_frame  # noqa: E402

from harborly import PortRegistry  # noqa: E402
from harborly.api import create_app  # noqa: E402


class _WorkingBackend:
    name = "test"
    version = "1.2.3"
    graph_version = "1.2.3"
    symmetric = True

    def route(self, origin, destination, config) -> NoReturn:
        raise AssertionError("readiness must not compute a route")


class _UninstalledBackend:
    name = "searoute"
    graph_version = "0"
    symmetric = True

    @property
    def version(self) -> NoReturn:
        raise ImportError("routing requires the 'routing' extra")

    def route(self, origin, destination, config) -> NoReturn:
        raise ImportError("routing requires the 'routing' extra")


class _UnreachableCache:
    def key(self, **_kwargs: object) -> str:
        return "k"

    def get(self, key: str) -> NoReturn:
        raise OSError("disk is gone")

    def put(self, key: str, result: object) -> None: ...

    def delete(self, key: str) -> None: ...


def _named(checks: tuple[ReadinessCheck, ...], name: str) -> ReadinessCheck:
    return next(check for check in checks if check.name == name)


def test_a_router_whose_backend_is_not_installed_is_not_ready() -> None:
    checks = SeaRouter(_routing_backend=_UninstalledBackend()).check_ready()

    backend = _named(checks, "routing_backend")
    assert backend.passed is False
    assert "routing" in backend.detail


def test_a_working_backend_reports_the_version_it_would_route_with() -> None:
    checks = SeaRouter(_routing_backend=_WorkingBackend()).check_ready()

    assert _named(checks, "routing_backend").passed is True
    assert "1.2.3" in _named(checks, "routing_backend").detail


def test_readiness_does_not_claim_a_cache_that_was_never_configured() -> None:
    checks = SeaRouter(_routing_backend=_WorkingBackend()).check_ready()

    assert _named(checks, "route_cache").passed is True
    assert "not configured" in _named(checks, "route_cache").detail


def test_a_broken_cache_blocks_readiness_only_where_it_blocks_requests(
    monkeypatch,
) -> None:
    """Readiness has to agree with the cache failure policy, not guess.

    Under STRICT an unreachable cache fails every request, so the process is
    genuinely not ready. Under BEST_EFFORT the same cache costs nothing but
    speed, and reporting not-ready would take a working server out of rotation.
    """

    monkeypatch.setattr("harborly.router.RouteCache", lambda _path: _UnreachableCache())

    strict = SeaRouter(
        cache_path="stubbed",
        _routing_backend=_WorkingBackend(),
        cache_failure_policy=CacheFailurePolicy.STRICT,
    ).check_ready()
    best_effort = SeaRouter(
        cache_path="stubbed",
        _routing_backend=_WorkingBackend(),
        cache_failure_policy=CacheFailurePolicy.BEST_EFFORT,
    ).check_ready()

    assert _named(strict, "route_cache").passed is False
    assert _named(best_effort, "route_cache").passed is True
    assert "disk is gone" in _named(best_effort, "route_cache").detail


@pytest.fixture
def registry() -> PortRegistry:
    return PortRegistry(registry_frame(), alias_frame())


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _get(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.anyio
async def test_liveness_answers_while_dependencies_are_broken(registry) -> None:
    """A process that cannot route is still a process worth not restarting."""

    app = create_app(
        registry=registry, router=SeaRouter(_routing_backend=_UninstalledBackend())
    )

    response = await _get(app, "/v1/livez")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_readiness_reports_every_dependency_it_checked(registry) -> None:
    app = create_app(
        registry=registry, router=SeaRouter(_routing_backend=_WorkingBackend())
    )

    response = await _get(app, "/v1/readyz")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ready"
    assert {check["name"] for check in body["checks"]} == {
        "port_registry",
        "routing_backend",
        "route_cache",
    }
    assert all(check["passed"] for check in body["checks"])


@pytest.mark.anyio
async def test_readiness_refuses_traffic_when_routing_is_unavailable(registry) -> None:
    app = create_app(
        registry=registry, router=SeaRouter(_routing_backend=_UninstalledBackend())
    )

    response = await _get(app, "/v1/readyz")
    body = response.json()

    assert response.status_code == 503
    assert body["status"] == "not_ready"
    failed = [check for check in body["checks"] if not check["passed"]]
    assert [check["name"] for check in failed] == ["routing_backend"]
