"""The HTTP error contract has to be usable by a program, not just a person.

The domain layer already carries machine-readable codes: every exception class
has a `code`, and `RoutingError` also carries a `RoutingErrorReason`. They were
flattened into a prose `detail` string at the boundary, so a client could not
tell a missing port from an ambiguous one without parsing English.
"""

from __future__ import annotations

from typing import NoReturn

import httpx
import pytest

pytest.importorskip("fastapi", reason="tests the optional 'api' extra")

from test_ports import alias_frame, registry_frame  # noqa: E402

from harborly import Port, PortRegistry  # noqa: E402
from harborly.api import create_app  # noqa: E402
from harborly.exceptions import RoutingError, RoutingErrorReason  # noqa: E402


class _FailingRouter:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def route(self, origin: Port, destination: Port) -> NoReturn:
        raise self._error


@pytest.fixture
def registry() -> PortRegistry:
    return PortRegistry(registry_frame(), alias_frame())


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _get(app, path: str, **params):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, params=params)


@pytest.mark.anyio
async def test_an_unknown_port_reports_a_stable_error_code(registry) -> None:
    app = create_app(registry=registry, router=_FailingRouter(RuntimeError()))

    response = await _get(app, "/v1/route", origin="missing", destination="WPI:2")
    body = response.json()

    assert response.status_code == 404
    assert body["error"]["code"] == "port_not_found"
    assert body["error"]["retryable"] is False
    assert body["schema_version"] == "1"
    assert body["error"]["message"]


@pytest.mark.anyio
async def test_a_transient_backend_failure_is_marked_retryable(registry) -> None:
    error = RoutingError(
        "backend exploded", reason=RoutingErrorReason.BACKEND_CALL_FAILED
    )
    app = create_app(registry=registry, router=_FailingRouter(error))

    response = await _get(app, "/v1/route", origin="WPI:1", destination="WPI:2")
    body = response.json()

    assert response.status_code == 502
    assert body["error"]["code"] == "routing_error"
    assert body["error"]["details"]["reason"] == "backend_call_failed"
    assert body["error"]["retryable"] is True
    assert response.headers["retry-after"]


@pytest.mark.anyio
async def test_an_implausible_route_is_not_retryable(registry) -> None:
    error = RoutingError("nonsense", reason=RoutingErrorReason.IMPLAUSIBLE_ROUTE)
    app = create_app(registry=registry, router=_FailingRouter(error))

    response = await _get(app, "/v1/route", origin="WPI:1", destination="WPI:2")
    body = response.json()

    assert body["error"]["details"]["reason"] == "implausible_route"
    assert body["error"]["retryable"] is False
    assert "retry-after" not in response.headers


@pytest.mark.anyio
async def test_an_exhausted_time_budget_asks_the_client_to_come_back(registry) -> None:
    """Giving up on time is this service declining, not the upstream misbehaving."""

    error = RoutingError(
        "budget exhausted", reason=RoutingErrorReason.TIMEOUT_BUDGET_EXHAUSTED
    )
    app = create_app(registry=registry, router=_FailingRouter(error))

    response = await _get(app, "/v1/route", origin="WPI:1", destination="WPI:2")
    body = response.json()

    assert response.status_code == 503
    assert body["error"]["details"]["reason"] == "timeout_budget_exhausted"
    assert body["error"]["retryable"] is True
    assert response.headers["retry-after"]


@pytest.mark.anyio
async def test_a_missing_routing_extra_reports_its_own_code(registry) -> None:
    app = create_app(
        registry=registry, router=_FailingRouter(ImportError("needs 'routing'"))
    )

    response = await _get(app, "/v1/route", origin="WPI:1", destination="WPI:2")
    body = response.json()

    assert response.status_code == 503
    assert body["error"]["code"] == "routing_unavailable"
    assert body["error"]["retryable"] is False
