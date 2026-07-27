import math

import httpx
import pytest

from sea_mile import RetryPolicy
from sea_mile._routing_backend import BackendRoute
from sea_mile.exceptions import RoutingError
from sea_mile.ports import Port
from sea_mile.router import SeaRouter, _is_transient_backend_error


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


def test_retry_policy_validation():
    with pytest.raises(ValueError):
        SeaRouter(retry_attempts=0)

    with pytest.raises(ValueError):
        SeaRouter(retry_attempts=9)

    with pytest.raises(ValueError):
        SeaRouter(backoff_seconds=-1.0)

    with pytest.raises(ValueError):
        SeaRouter(backoff_seconds=9.0)

    with pytest.raises(ValueError):
        SeaRouter(backoff_seconds=math.nan)

    with pytest.raises(ValueError):
        SeaRouter(backoff_seconds=math.inf)

    # Direct RetryPolicy tests
    with pytest.raises(ValueError):
        RetryPolicy(attempts=0)

    with pytest.raises(ValueError):
        RetryPolicy(attempts=10)

    with pytest.raises(ValueError):
        RetryPolicy(base_backoff_seconds=10.0, max_backoff_seconds=5.0)

    with pytest.raises(ValueError):
        RetryPolicy(jitter_ratio=1.5)


def test_first_call_success(monkeypatch):
    sleep_called = False

    def mock_sleep(seconds):
        nonlocal sleep_called
        sleep_called = True

    monkeypatch.setattr("sea_mile.router.time.sleep", mock_sleep)

    backend = CountingBackend([_VALID_ROUTE])
    router = SeaRouter(retry_attempts=3, _routing_backend=backend)

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

    monkeypatch.setattr("sea_mile.router.time.sleep", mock_sleep)
    monkeypatch.setattr("sea_mile.router.secrets.SystemRandom.random", mock_random)

    backend = CountingBackend([TimeoutError("timeout"), _VALID_ROUTE])
    router = SeaRouter(retry_attempts=3, backoff_seconds=0.25, _routing_backend=backend)

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

    monkeypatch.setattr("sea_mile.router.time.sleep", mock_sleep)

    error1 = TimeoutError("1")
    error2 = ConnectionError("2")
    error3 = TimeoutError("3")

    backend = CountingBackend([error1, error2, error3])
    router = SeaRouter(retry_attempts=3, _routing_backend=backend)

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

    monkeypatch.setattr("sea_mile.router.time.sleep", mock_sleep)

    error = ValueError("bad data")
    backend = CountingBackend([error, _VALID_ROUTE])
    router = SeaRouter(retry_attempts=3, _routing_backend=backend)

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

    monkeypatch.setattr("sea_mile.router.time.sleep", mock_sleep)

    errors = [TimeoutError("err")] * 5
    backend = CountingBackend(errors)
    router = SeaRouter(retry_attempts=4, _routing_backend=backend)

    port_a = _fake_port("A")
    port_b = _fake_port("B")

    with pytest.raises(RoutingError):
        router.route(port_a, port_b)

    assert backend.call_count == 4


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
