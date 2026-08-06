import math

import httpx
import pytest

from harborly import RetryPolicy
from harborly._routing_backend import BackendRoute
from harborly.exceptions import RoutingError, RoutingErrorReason
from harborly.ports import Port
from harborly.router import SeaRouter, _is_transient_backend_error


def _fake_port(label="A", lat=None, lon=None):
    if lat is None:
        lat = 36.8 if label == "A" else 37.94
    if lon is None:
        lon = 34.65 if label == "A" else 23.63
    return Port(
        registry_id=f"TEST:{label}",
        provider="TEST",
        provider_id=label,
        country_code="XX",
        name=label,
        latitude=lat,
        longitude=lon,
        unlocode=None,
        function_code=None,
        source_version="test",
        coordinate_resolution=None,
    )


class CountingBackend:
    def __init__(self, responses):
        """responses: list of BackendRoute or Exception instances."""
        self._responses = list(responses)
        self.call_count = 0

    @property
    def name(self):
        return "test"

    @property
    def version(self):
        return "0.0"

    @property
    def symmetric(self):
        return True

    def route(self, origin, destination, config):
        self.call_count += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


_VALID_ROUTE = BackendRoute(
    distance_nmi=1000.0,
    geometry={"type": "LineString", "coordinates": [[34.65, 36.8], [23.63, 37.94]]},
)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"attempts": 0},
        {"attempts": 10},
        {"base_backoff_seconds": -1.0},
        {"base_backoff_seconds": math.nan},
        {"base_backoff_seconds": math.inf},
        {"base_backoff_seconds": 10.0, "max_backoff_seconds": 5.0},
        {"max_backoff_seconds": math.nan},
        {"jitter_ratio": 1.5},
    ],
)
def test_retry_policy_validation(kwargs):
    """Validation belongs to the policy now that it is the only way to set this."""

    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)


def test_first_call_success(monkeypatch):
    sleep_called = False

    def mock_sleep(seconds):
        nonlocal sleep_called
        sleep_called = True

    monkeypatch.setattr("harborly.router.time.sleep", mock_sleep)

    backend = CountingBackend([_VALID_ROUTE])
    router = SeaRouter(retry_policy=RetryPolicy(attempts=3), _routing_backend=backend)

    port_a = _fake_port("A")
    port_b = _fake_port("B")

    result = router.route(port_a, port_b)

    assert backend.call_count == 1
    assert not sleep_called
    assert result.distance_nmi == 1000.0


def test_transient_then_success(monkeypatch):
    sleep_calls = []

    def mock_sleep(seconds):
        sleep_calls.append(seconds)

    def mock_random(_self):
        return 0.5

    monkeypatch.setattr("harborly.router.time.sleep", mock_sleep)
    monkeypatch.setattr("harborly.router.secrets.SystemRandom.random", mock_random)

    backend = CountingBackend([TimeoutError("timeout"), _VALID_ROUTE])
    router = SeaRouter(
        retry_policy=RetryPolicy(attempts=3, base_backoff_seconds=0.25),
        _routing_backend=backend,
    )

    port_a = _fake_port("A")
    port_b = _fake_port("B")

    result = router.route(port_a, port_b)

    assert backend.call_count == 2
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 0.25
    assert result.distance_nmi == 1000.0


def test_retry_exhaustion(monkeypatch):
    sleep_calls = []

    def mock_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("harborly.router.time.sleep", mock_sleep)

    error1 = TimeoutError("1")
    error2 = ConnectionError("2")
    error3 = TimeoutError("3")

    backend = CountingBackend([error1, error2, error3])
    router = SeaRouter(retry_policy=RetryPolicy(attempts=3), _routing_backend=backend)

    port_a = _fake_port("A")
    port_b = _fake_port("B")

    with pytest.raises(RoutingError) as exc_info:
        router.route(port_a, port_b)

    assert exc_info.value.__cause__ is error3
    assert backend.call_count == 3
    assert len(sleep_calls) == 2


def test_non_transient_no_retry(monkeypatch):
    sleep_called = False

    def mock_sleep(seconds):
        nonlocal sleep_called
        sleep_called = True

    monkeypatch.setattr("harborly.router.time.sleep", mock_sleep)

    error = ValueError("bad data")
    backend = CountingBackend([error, _VALID_ROUTE])
    router = SeaRouter(retry_policy=RetryPolicy(attempts=3), _routing_backend=backend)

    port_a = _fake_port("A")
    port_b = _fake_port("B")

    with pytest.raises(RoutingError) as exc_info:
        router.route(port_a, port_b)

    assert exc_info.value.__cause__ is error
    assert backend.call_count == 1
    assert not sleep_called


def test_exact_retry_count(monkeypatch):
    def mock_sleep(seconds):
        pass

    monkeypatch.setattr("harborly.router.time.sleep", mock_sleep)

    errors = [TimeoutError("err")] * 5
    backend = CountingBackend(errors)
    router = SeaRouter(retry_policy=RetryPolicy(attempts=4), _routing_backend=backend)

    port_a = _fake_port("A")
    port_b = _fake_port("B")

    with pytest.raises(RoutingError):
        router.route(port_a, port_b)

    assert backend.call_count == 4


class _FakeClock:
    """A clock that only moves when the retry loop sleeps.

    Backoff is the whole point of the budget, so simulating it is enough to
    exercise the decision without making the test wait in real time.
    """

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr("harborly.router.time.monotonic", clock.monotonic)
    monkeypatch.setattr("harborly.router.time.sleep", clock.sleep)
    monkeypatch.setattr(
        "harborly.router.secrets.SystemRandom.random", lambda _self: 0.5
    )
    return clock


def test_the_budget_refuses_a_backoff_it_cannot_afford(fake_clock):
    """Without a budget these four attempts sleep 0.25 + 0.5 + 1.0 seconds.

    The point of the budget is that the caller's worker is not held for the
    full ladder, so the loop has to stop where the next wait no longer fits.
    """

    backend = CountingBackend([TimeoutError("boom")] * 4)
    router = SeaRouter(
        retry_policy=RetryPolicy(
            attempts=4, base_backoff_seconds=0.25, overall_timeout_seconds=0.6
        ),
        _routing_backend=backend,
    )

    with pytest.raises(RoutingError) as exc_info:
        router.route(_fake_port("A"), _fake_port("B"))

    assert exc_info.value.reason is RoutingErrorReason.TIMEOUT_BUDGET_EXHAUSTED
    assert backend.call_count == 2
    assert fake_clock.now == 0.25


def test_a_budget_that_fits_the_whole_ladder_changes_nothing(fake_clock):
    backend = CountingBackend([TimeoutError("boom"), _VALID_ROUTE])
    router = SeaRouter(
        retry_policy=RetryPolicy(
            attempts=4, base_backoff_seconds=0.25, overall_timeout_seconds=30.0
        ),
        _routing_backend=backend,
    )

    result = router.route(_fake_port("A"), _fake_port("B"))

    assert result.distance_nmi == 1000.0
    assert backend.call_count == 2


def test_an_exhausted_budget_still_names_the_failure_that_caused_it(fake_clock):
    """The budget explains why we stopped, not why the call was failing."""

    last = TimeoutError("second")
    backend = CountingBackend([TimeoutError("first"), last])
    router = SeaRouter(
        retry_policy=RetryPolicy(
            attempts=4, base_backoff_seconds=0.25, overall_timeout_seconds=0.6
        ),
        _routing_backend=backend,
    )

    with pytest.raises(RoutingError) as exc_info:
        router.route(_fake_port("A"), _fake_port("B"))

    assert exc_info.value.__cause__ is last


def test_a_non_transient_failure_is_not_relabelled_as_a_budget_timeout(fake_clock):
    backend = CountingBackend([ValueError("bad data")])
    router = SeaRouter(
        retry_policy=RetryPolicy(attempts=4, overall_timeout_seconds=0.0001),
        _routing_backend=backend,
    )

    with pytest.raises(RoutingError) as exc_info:
        router.route(_fake_port("A"), _fake_port("B"))

    assert exc_info.value.reason is not RoutingErrorReason.TIMEOUT_BUDGET_EXHAUSTED
    assert backend.call_count == 1


def test_the_overall_timeout_is_validated():
    with pytest.raises(ValueError):
        RetryPolicy(overall_timeout_seconds=0.0)

    with pytest.raises(ValueError):
        RetryPolicy(overall_timeout_seconds=-1.0)

    with pytest.raises(ValueError):
        RetryPolicy(overall_timeout_seconds=math.inf)

    assert RetryPolicy().overall_timeout_seconds is None


class DummyResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class DummyErrorWithResponse(Exception):
    def __init__(self, response):
        self.response = response


def test_is_transient_backend_error():
    assert _is_transient_backend_error(TimeoutError())
    assert _is_transient_backend_error(ConnectionError())
    assert _is_transient_backend_error(httpx.TimeoutException("timeout"))
    assert _is_transient_backend_error(httpx.TransportError("transport"))

    assert _is_transient_backend_error(DummyErrorWithResponse(DummyResponse(429)))
    assert _is_transient_backend_error(DummyErrorWithResponse(DummyResponse(500)))
    assert _is_transient_backend_error(DummyErrorWithResponse(DummyResponse(502)))
    assert _is_transient_backend_error(DummyErrorWithResponse(DummyResponse(599)))

    assert not _is_transient_backend_error(ValueError())
    assert not _is_transient_backend_error(TypeError())
    assert not _is_transient_backend_error(DummyErrorWithResponse(DummyResponse(400)))
    assert not _is_transient_backend_error(DummyErrorWithResponse(DummyResponse(404)))

    try:
        raise TimeoutError()
    except Exception as inner:
        try:
            raise ValueError() from inner
        except Exception as outer:
            assert _is_transient_backend_error(outer)
