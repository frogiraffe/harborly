"""A broken cache should not have to mean a broken answer.

The persistent route cache is an optimisation: every route it holds can be
recomputed. Today any cache failure — an unwritable directory, a corrupt file,
a full disk — turns into a `RoutingError` and the caller gets nothing, even
though the route itself was computed successfully. That is the right default
for a reproducibility-sensitive SDK call, and the wrong one for a long-running
service that would rather be slow than down.

`CacheFailurePolicy` makes the choice explicit instead of implicit.
"""

from __future__ import annotations

import logging

import pytest

from sea_mile._routing_backend import BackendRoute
from sea_mile.exceptions import RoutingError, RoutingErrorReason
from sea_mile.ports import Port
from sea_mile.router import SeaRouter
from sea_mile.routing import CacheFailurePolicy

_VALID_ROUTE = BackendRoute(
    distance_nmi=1000.0,
    geometry={"type": "LineString", "coordinates": [[34.65, 36.8], [23.63, 37.94]]},
)

# Shorter than the great-circle distance between the two ports, so the
# plausibility check rejects it and the router tries to evict the cache entry.
_IMPLAUSIBLE_ROUTE = BackendRoute(
    distance_nmi=1.0,
    geometry={"type": "LineString", "coordinates": [[34.65, 36.8], [23.63, 37.94]]},
)


def _port(label: str) -> Port:
    latitude, longitude = (36.8, 34.65) if label == "A" else (37.94, 23.63)
    return Port(
        registry_id=f"TEST:{label}",
        provider="TEST",
        provider_id=label,
        country_code="XX",
        name=label,
        latitude=latitude,
        longitude=longitude,
        unlocode=None,
        function_code=None,
        source_version="test",
        coordinate_resolution=None,
    )


class _StubBackend:
    def __init__(self, result: BackendRoute = _VALID_ROUTE) -> None:
        self._result = result
        self.call_count = 0

    name = "test"
    version = "0.0"
    graph_version = "0.0"
    symmetric = True

    def route(self, origin, destination, config) -> BackendRoute:
        self.call_count += 1
        return self._result


class _BrokenCache:
    """A cache whose chosen operations raise, standing in for a bad disk."""

    def __init__(self, *failing: str, stored: BackendRoute | None = None) -> None:
        self._failing = set(failing)
        self._stored = stored
        self.deleted: list[str] = []

    def key(self, **_kwargs: object) -> str:
        return "cache-key"

    def _maybe_fail(self, action: str) -> None:
        if action in self._failing:
            raise OSError(f"{action} failed")

    def get(self, key: str) -> BackendRoute | None:
        self._maybe_fail("get")
        return self._stored

    def put(self, key: str, result: BackendRoute) -> None:
        self._maybe_fail("put")

    def delete(self, key: str) -> None:
        self._maybe_fail("delete")
        self.deleted.append(key)


@pytest.fixture
def install_cache(monkeypatch):
    def install(cache: _BrokenCache) -> None:
        monkeypatch.setattr("sea_mile.router.RouteCache", lambda _path: cache)

    return install


def _router(backend: _StubBackend, policy: CacheFailurePolicy | None = None):
    kwargs = {} if policy is None else {"cache_failure_policy": policy}
    return SeaRouter(
        cache_path="ignored-by-the-stub", _routing_backend=backend, **kwargs
    )


def test_strict_is_the_default_so_todays_callers_see_no_change(install_cache):
    install_cache(_BrokenCache("get"))
    backend = _StubBackend()

    with pytest.raises(RoutingError) as exc_info:
        _router(backend).route(_port("A"), _port("B"))

    assert exc_info.value.reason is RoutingErrorReason.CACHE_ACCESS_FAILED
    assert backend.call_count == 0


def test_best_effort_treats_an_unreadable_cache_as_a_miss(install_cache):
    install_cache(_BrokenCache("get"))
    backend = _StubBackend()

    result = _router(backend, CacheFailurePolicy.BEST_EFFORT).route(
        _port("A"), _port("B")
    )

    assert result.distance_nmi == 1000.0
    assert backend.call_count == 1


def test_best_effort_still_returns_a_route_it_could_not_store(install_cache):
    install_cache(_BrokenCache("put"))
    backend = _StubBackend()

    result = _router(backend, CacheFailurePolicy.BEST_EFFORT).route(
        _port("A"), _port("B")
    )

    assert result.distance_nmi == 1000.0


def test_best_effort_says_out_loud_what_it_swallowed(install_cache, caplog):
    install_cache(_BrokenCache("put"))

    with caplog.at_level(logging.WARNING, logger="sea_mile.router"):
        _router(_StubBackend(), CacheFailurePolicy.BEST_EFFORT).route(
            _port("A"), _port("B")
        )

    assert "put failed" in caplog.text


def test_best_effort_does_not_let_a_failed_eviction_mask_the_real_failure(
    install_cache,
):
    """The route was rejected as implausible. That is what the caller needs.

    The cache entry could not be evicted afterwards, which matters to an
    operator reading logs but tells the caller nothing about their request.
    """

    install_cache(_BrokenCache("delete", stored=_IMPLAUSIBLE_ROUTE))

    with pytest.raises(RoutingError) as exc_info:
        _router(_StubBackend(), CacheFailurePolicy.BEST_EFFORT).route(
            _port("A"), _port("B")
        )

    assert exc_info.value.reason is RoutingErrorReason.IMPLAUSIBLE_ROUTE


def test_a_healthy_cache_is_used_under_both_policies(install_cache):
    for policy in (CacheFailurePolicy.STRICT, CacheFailurePolicy.BEST_EFFORT):
        install_cache(_BrokenCache(stored=_VALID_ROUTE))
        backend = _StubBackend()

        result = _router(backend, policy).route(_port("A"), _port("B"))

        assert result.distance_nmi == 1000.0
        assert backend.call_count == 0, f"{policy} recomputed a cached route"
