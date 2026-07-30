"""Public exceptions raised by registry and routing APIs."""

from enum import StrEnum


class SeaMileError(Exception):
    """Base exception for recoverable sea-mile errors."""

    code = "sea_mile_error"


class RegistryDataError(SeaMileError):
    """The local registry files are missing or violate their schema."""

    code = "registry_data_error"


class SourceDataError(SeaMileError):
    """A public reference snapshot could not be downloaded or read."""

    code = "source_data_error"


class PortNotFoundError(SeaMileError):
    """No port satisfies the requested identifier or exact name."""

    code = "port_not_found"


class AmbiguousPortError(SeaMileError):
    """More than one independent port identity satisfies a request."""

    code = "ambiguous_port"


class PortCoordinateError(SeaMileError):
    """A selected port has no usable routing coordinate."""

    code = "port_coordinate"


class RoutingErrorReason(StrEnum):
    """Stable reason tokens that tell the routing failure modes apart."""

    BACKEND_CALL_FAILED = "backend_call_failed"
    CACHE_ACCESS_FAILED = "cache_access_failed"
    MALFORMED_BACKEND_RESULT = "malformed_backend_result"
    IMPLAUSIBLE_ROUTE = "implausible_route"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    TIMEOUT_BUDGET_EXHAUSTED = "timeout_budget_exhausted"


class RoutingError(SeaMileError):
    """Routing or its persistent cache failed to produce a usable route."""

    code = "routing_error"

    def __init__(self, message: str, *, reason: RoutingErrorReason) -> None:
        super().__init__(message)
        self.reason = reason
