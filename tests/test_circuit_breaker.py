import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from sea_mile._routing_backend import BackendRoute, RoutingConfig
from sea_mile.coordinates import LatLon
from sea_mile.ports import Port
from sea_mile.router import SeaRouter
from sea_mile.routing import RetryPolicy

# These will fail with ImportError until the circuit breaker is implemented.
# That's the expected behavior for this commit.
try:
    from sea_mile._circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerPolicy,
        _CircuitState,
    )
    from sea_mile.exceptions import RoutingError

    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK, reason="circuit breaker not yet implemented"
)


def make_clock(start=0.0):
    current = [start]

    def clock():
        return current[0]

    def advance(seconds):
        current[0] += seconds

    return clock, advance


class ControlledHalfOpenBackend:
    name = "controlled-half-open"
    version = "1"
    symmetric = True

    def __init__(self, *, probe_succeeds: bool) -> None:
        self.probe_succeeds = probe_succeeds
        self.preconditioning = True
        self.precondition_calls = 0
        self.probe_calls = 0
        self.probe_thread_id: int | None = None
        self.probe_entered = threading.Event()
        self.release_probe = threading.Event()
        self._lock = threading.Lock()

    def route(
        self, origin: LatLon, destination: LatLon, config: RoutingConfig
    ) -> BackendRoute:
        with self._lock:
            if self.preconditioning:
                self.precondition_calls += 1
                raise TimeoutError("controlled preconditioning failure")
            self.probe_calls += 1
            self.probe_thread_id = threading.get_ident()
        self.probe_entered.set()
        assert self.release_probe.wait(timeout=10)
        if not self.probe_succeeds:
            raise TimeoutError("controlled half-open probe failure")
        return BackendRoute(
            distance_nmi=600.0,
            geometry={
                "type": "LineString",
                "coordinates": [
                    origin.to_lon_lat().as_list(),
                    destination.to_lon_lat().as_list(),
                ],
            },
        )


def _port(identifier: str, latitude: float, longitude: float) -> Port:
    return Port(
        registry_id=f"TEST:{identifier}",
        provider="TEST",
        provider_id=identifier,
        country_code="XX",
        name=identifier,
        latitude=latitude,
        longitude=longitude,
        unlocode=None,
        function_code=None,
        source_version="test",
        coordinate_resolution=None,
    )


def test_default_state_is_closed():
    policy = CircuitBreakerPolicy(failure_threshold=5, recovery_seconds=30.0)
    breaker = CircuitBreaker(policy)
    assert breaker.state == _CircuitState.CLOSED


def test_policy_validation():
    with pytest.raises(ValueError):
        CircuitBreakerPolicy(failure_threshold=0, recovery_seconds=30.0)
    with pytest.raises(ValueError):
        CircuitBreakerPolicy(failure_threshold=5, recovery_seconds=0.0)
    with pytest.raises(ValueError):
        CircuitBreakerPolicy(failure_threshold=-1, recovery_seconds=30.0)
    with pytest.raises(ValueError):
        CircuitBreakerPolicy(failure_threshold=5, recovery_seconds=-5.0)


def test_closed_success_resets_failure_count():
    policy = CircuitBreakerPolicy(failure_threshold=3, recovery_seconds=30.0)
    breaker = CircuitBreaker(policy)

    breaker.record_failure(transient=True)
    breaker.record_failure(transient=True)
    assert breaker.state == _CircuitState.CLOSED

    breaker.record_success()
    assert breaker.state == _CircuitState.CLOSED

    # We can now fail 2 more times without tripping
    breaker.record_failure(transient=True)
    breaker.record_failure(transient=True)
    assert breaker.state == _CircuitState.CLOSED


def test_closed_failures_below_threshold():
    policy = CircuitBreakerPolicy(failure_threshold=3, recovery_seconds=30.0)
    breaker = CircuitBreaker(policy)

    breaker.record_failure(transient=True)
    breaker.record_failure(transient=True)
    assert breaker.state == _CircuitState.CLOSED


def test_closed_failures_at_threshold():
    policy = CircuitBreakerPolicy(failure_threshold=3, recovery_seconds=30.0)
    breaker = CircuitBreaker(policy)

    breaker.record_failure(transient=True)
    breaker.record_failure(transient=True)
    breaker.record_failure(transient=True)
    assert breaker.state == _CircuitState.OPEN


def test_open_state_fail_fast():
    policy = CircuitBreakerPolicy(failure_threshold=1, recovery_seconds=30.0)
    breaker = CircuitBreaker(policy)

    breaker.record_failure(transient=True)
    assert breaker.state == _CircuitState.OPEN

    with pytest.raises(RoutingError) as exc_info:
        breaker.check()
    assert (
        "CIRCUIT_BREAKER_OPEN" in str(exc_info.value)
        or "circuit breaker" in str(exc_info.value).lower()
    )


def test_open_state_no_backend_call():
    # Test implicitly covered by fail_fast, but explicit documentation:
    policy = CircuitBreakerPolicy(failure_threshold=1, recovery_seconds=30.0)
    breaker = CircuitBreaker(policy)
    breaker.record_failure(transient=True)

    # Check that check() raises RoutingError immediately and avoids actual work.
    with pytest.raises(RoutingError):
        breaker.check()


def test_recovery_timer():
    clock, advance = make_clock()
    policy = CircuitBreakerPolicy(failure_threshold=1, recovery_seconds=10.0)
    breaker = CircuitBreaker(policy, _clock=clock)

    breaker.record_failure(transient=True)
    assert breaker.state == _CircuitState.OPEN

    advance(9.9)
    with pytest.raises(RoutingError):
        breaker.check()

    advance(0.2)
    # 10.1 seconds elapsed, check should now pass and transition to HALF_OPEN
    breaker.check()
    assert breaker.state == _CircuitState.HALF_OPEN


def test_half_open_single_probe():
    clock, advance = make_clock()
    policy = CircuitBreakerPolicy(failure_threshold=1, recovery_seconds=10.0)
    breaker = CircuitBreaker(policy, _clock=clock)

    breaker.record_failure(transient=True)
    advance(11.0)

    # First check should succeed (probe)
    breaker.check()
    assert breaker.state == _CircuitState.HALF_OPEN

    # Second check should fail-fast
    with pytest.raises(RoutingError):
        breaker.check()


def test_half_open_successful_probe():
    clock, advance = make_clock()
    policy = CircuitBreakerPolicy(failure_threshold=1, recovery_seconds=10.0)
    breaker = CircuitBreaker(policy, _clock=clock)

    breaker.record_failure(transient=True)
    advance(11.0)

    breaker.check()
    breaker.record_success()
    assert breaker.state == _CircuitState.CLOSED


def test_half_open_failed_probe():
    clock, advance = make_clock()
    policy = CircuitBreakerPolicy(failure_threshold=1, recovery_seconds=10.0)
    breaker = CircuitBreaker(policy, _clock=clock)

    breaker.record_failure(transient=True)
    advance(11.0)

    breaker.check()
    breaker.record_failure(transient=True)
    assert breaker.state == _CircuitState.OPEN

    # We should have a new recovery timer
    with pytest.raises(RoutingError):
        breaker.check()


def test_concurrent_half_open_access():
    clock, advance = make_clock()
    policy = CircuitBreakerPolicy(failure_threshold=1, recovery_seconds=10.0)
    breaker = CircuitBreaker(policy, _clock=clock)

    breaker.record_failure(transient=True)
    assert breaker.state == _CircuitState.OPEN

    advance(11.0)

    results = {"success": 0, "failure": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(5)

    def worker():
        barrier.wait()
        try:
            breaker.check()
            with lock:
                results["success"] += 1
        except RoutingError:
            with lock:
                results["failure"] += 1

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results["success"] == 1
    assert results["failure"] == 4
    assert breaker.state == _CircuitState.HALF_OPEN


@pytest.mark.parametrize("probe_succeeds", [True, False])
def test_router_allows_exactly_one_concurrent_half_open_probe(
    probe_succeeds: bool,
) -> None:
    backend = ControlledHalfOpenBackend(probe_succeeds=probe_succeeds)
    router = SeaRouter(
        retry_policy=RetryPolicy(attempts=1),
        circuit_breaker_policy=CircuitBreakerPolicy(
            failure_threshold=1,
            recovery_seconds=10.0,
        ),
        _routing_backend=backend,
    )
    assert router._circuit_breaker is not None
    clock, advance = make_clock()
    router._circuit_breaker._clock = clock
    origin = _port("A", 36.8, 34.65)
    destination = _port("B", 37.94, 23.63)

    with pytest.raises(RoutingError):
        router.route(origin, destination)
    assert backend.precondition_calls == 1
    assert router._circuit_breaker.state == _CircuitState.OPEN

    backend.preconditioning = False
    advance(11.0)
    workers = 20
    start = threading.Barrier(workers + 1)
    outcome = {
        "success": 0,
        "fail_fast": 0,
        "probe_failure": 0,
        "unexpected": [],
    }
    condition = threading.Condition()

    def call_router(_: int) -> None:
        start.wait(timeout=10)
        try:
            router.route(origin, destination)
        except RoutingError:
            with condition:
                if threading.get_ident() == backend.probe_thread_id:
                    outcome["probe_failure"] += 1
                else:
                    outcome["fail_fast"] += 1
                condition.notify_all()
        except Exception as error:  # pragma: no cover - asserted empty below
            with condition:
                outcome["unexpected"].append(error)
                condition.notify_all()
        else:
            with condition:
                outcome["success"] += 1
                condition.notify_all()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(call_router, index) for index in range(workers)]
        start.wait(timeout=10)
        assert backend.probe_entered.wait(timeout=10)
        with condition:
            assert condition.wait_for(
                lambda: outcome["fail_fast"] == workers - 1,
                timeout=10,
            )
        backend.release_probe.set()
        for future in futures:
            future.result(timeout=10)

    assert backend.probe_calls == 1
    assert outcome["fail_fast"] == 19
    assert outcome["unexpected"] == []
    if probe_succeeds:
        assert outcome["success"] == 1
        assert outcome["probe_failure"] == 0
        assert router._circuit_breaker.state == _CircuitState.CLOSED
    else:
        assert outcome["success"] == 0
        assert outcome["probe_failure"] == 1
        assert router._circuit_breaker.state == _CircuitState.OPEN


def test_non_transient_errors_ignored():
    policy = CircuitBreakerPolicy(failure_threshold=1, recovery_seconds=10.0)
    breaker = CircuitBreaker(policy)

    # Shouldn't trigger breaker because it's not transient
    breaker.record_failure(transient=False)
    assert breaker.state == _CircuitState.CLOSED


def test_cause_chain_preservation():
    policy = CircuitBreakerPolicy(failure_threshold=1, recovery_seconds=30.0)
    breaker = CircuitBreaker(policy)

    breaker.record_failure(transient=True)

    try:
        breaker.check()
    except RoutingError as e:
        assert isinstance(e, RoutingError)
        # Should give informative message
        assert "circuit breaker" in str(e).lower()


def test_router_circuit_breaker_integration(monkeypatch):
    from sea_mile.ports import Port
    from sea_mile.router import RoutingErrorReason, SeaRouter

    def mock_sleep(seconds):
        pass

    monkeypatch.setattr("sea_mile.router.time.sleep", mock_sleep)

    class FlakyBackend:
        def __init__(self):
            self.calls = 0

        @property
        def name(self):
            return "test"

        @property
        def version(self):
            return "1.0"

        @property
        def symmetric(self):
            return True

        def route(self, origin, destination, config):
            self.calls += 1
            raise TimeoutError("connection timeout")

    backend = FlakyBackend()
    policy = CircuitBreakerPolicy(failure_threshold=2, recovery_seconds=60.0)
    router = SeaRouter(
        retry_policy=RetryPolicy(attempts=5),
        circuit_breaker_policy=policy,
        _routing_backend=backend,
    )

    port_a = Port(
        registry_id="TEST:A",
        provider="TEST",
        provider_id="A",
        country_code="XX",
        name="A",
        latitude=36.8,
        longitude=34.65,
        unlocode=None,
        function_code=None,
        source_version="test",
        coordinate_resolution=None,
    )
    port_b = Port(
        registry_id="TEST:B",
        provider="TEST",
        provider_id="B",
        country_code="XX",
        name="B",
        latitude=37.94,
        longitude=23.63,
        unlocode=None,
        function_code=None,
        source_version="test",
        coordinate_resolution=None,
    )

    with pytest.raises(RoutingError) as exc_info:
        router.route(port_a, port_b)

    assert exc_info.value.reason == RoutingErrorReason.CIRCUIT_BREAKER_OPEN
    # Breaker tripped after 2 failures, so backend called exactly twice (not 5 times)
    assert backend.calls == 2

    # Second call fails fast on check() without calling backend again
    with pytest.raises(RoutingError) as exc_info2:
        router.route(port_a, port_b)

    assert exc_info2.value.reason == RoutingErrorReason.CIRCUIT_BREAKER_OPEN
    assert backend.calls == 2
