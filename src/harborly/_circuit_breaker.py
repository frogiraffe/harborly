"""Internal thread-safe circuit breaker state machine for routing backends."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from harborly.exceptions import RoutingError, RoutingErrorReason


class _CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class CircuitBreakerPolicy:
    """Configuration policy for backend circuit breaker behavior."""

    failure_threshold: int = 5
    recovery_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if not isfinite(self.recovery_seconds) or self.recovery_seconds <= 0.0:
            raise ValueError("recovery_seconds must be finite and positive")


class CircuitBreaker:
    """Thread-safe circuit breaker protecting against backend cascade failures."""

    def __init__(
        self,
        policy: CircuitBreakerPolicy,
        *,
        _clock: Callable[[], float] | None = None,
    ) -> None:
        self.policy = policy
        self._clock = _clock if _clock is not None else time.monotonic
        self._lock = threading.Lock()
        self._state = _CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float = 0.0
        self._half_open_probe_active = False

    @property
    def state(self) -> _CircuitState:
        with self._lock:
            if (
                self._state == _CircuitState.OPEN
                and self._clock() - self._opened_at >= self.policy.recovery_seconds
            ):
                return _CircuitState.HALF_OPEN
            return self._state

    def check(self) -> None:
        """Check if call is allowed. Raises RoutingError if breaker is open."""
        with self._lock:
            now = self._clock()

            if self._state == _CircuitState.OPEN:
                elapsed = now - self._opened_at
                if elapsed < self.policy.recovery_seconds:
                    remaining = self.policy.recovery_seconds - elapsed
                    raise RoutingError(
                        f"circuit breaker is open (recovers in {remaining:.1f}s)",
                        reason=RoutingErrorReason.CIRCUIT_BREAKER_OPEN,
                    )
                # Recovery window passed: transition to HALF_OPEN and allow single probe
                self._state = _CircuitState.HALF_OPEN
                self._half_open_probe_active = True
                return

            if self._state == _CircuitState.HALF_OPEN:
                if self._half_open_probe_active:
                    raise RoutingError(
                        "circuit breaker is half-open (probe in progress)",
                        reason=RoutingErrorReason.CIRCUIT_BREAKER_OPEN,
                    )
                self._half_open_probe_active = True
                return

    def record_success(self) -> None:
        """Record successful backend execution."""
        with self._lock:
            self._failure_count = 0
            self._state = _CircuitState.CLOSED
            self._half_open_probe_active = False

    def record_failure(self, transient: bool) -> None:
        """Record a backend execution failure."""
        if not transient:
            return

        with self._lock:
            now = self._clock()
            self._failure_count += 1

            if self._state == _CircuitState.HALF_OPEN:
                self._state = _CircuitState.OPEN
                self._opened_at = now
                self._half_open_probe_active = False
            elif self._state == _CircuitState.CLOSED:
                if self._failure_count >= self.policy.failure_threshold:
                    self._state = _CircuitState.OPEN
                    self._opened_at = now
