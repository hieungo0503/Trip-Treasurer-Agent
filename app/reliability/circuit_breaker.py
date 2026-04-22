"""
Circuit Breaker — 3 state: CLOSED → OPEN → HALF_OPEN.

Singletons per service: llm_circuit, sheets_circuit, drive_circuit, zalo_circuit.

Usage:
    if not llm_circuit.can_attempt():
        # fallback path
        ...
    try:
        result = await call_llm(...)
        llm_circuit.record_success()
    except RetriableError:
        llm_circuit.record_failure()
        raise
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Optional

import structlog

log = structlog.get_logger()


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    failure_window_seconds: int = 60
    cooldown_seconds: int = 120
    half_open_max_probes: int = 1

    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failures: list[float] = field(default_factory=list, init=False, repr=False)
    _opened_at: float = field(default=0.0, init=False)
    _half_open_probes: int = field(default=0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def is_open(self) -> bool:
        with self._lock:
            self._tick()
            return self.state == CircuitState.OPEN

    def can_attempt(self) -> bool:
        with self._lock:
            self._tick()
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.HALF_OPEN:
                if self._half_open_probes < self.half_open_max_probes:
                    self._half_open_probes += 1
                    return True
            return False

    def record_success(self) -> None:
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.CLOSED, "probe succeeded")
            self._failures.clear()

    def record_failure(self) -> None:
        with self._lock:
            now = time.time()
            if self.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN, "probe failed")
                self._opened_at = now
                return

            self._failures.append(now)
            cutoff = now - self.failure_window_seconds
            self._failures = [f for f in self._failures if f >= cutoff]

            if len(self._failures) >= self.failure_threshold:
                self._transition(CircuitState.OPEN, f"threshold {self.failure_threshold} reached")
                self._opened_at = now

    def reset(self) -> None:
        """Force reset về CLOSED — dùng cho admin /resume_bot."""
        with self._lock:
            self._transition(CircuitState.CLOSED, "manual reset")
            self._failures.clear()

    def _tick(self) -> None:
        if self.state == CircuitState.OPEN:
            if time.time() - self._opened_at >= self.cooldown_seconds:
                self._transition(CircuitState.HALF_OPEN, "cooldown elapsed")
                self._half_open_probes = 0

    def _transition(self, new_state: CircuitState, reason: str) -> None:
        old = self.state
        self.state = new_state
        log.info(
            "circuit_breaker.transition",
            name=self.name,
            from_state=old.value,
            to_state=new_state.value,
            reason=reason,
        )


class CircuitOpenError(Exception):
    def __init__(self, circuit_name: str) -> None:
        super().__init__(f"Circuit '{circuit_name}' is OPEN — service unavailable")
        self.circuit_name = circuit_name


# ── Singletons per service ───────────────────────────────────────────────────

llm_circuit = CircuitBreaker(
    name="llm",
    failure_threshold=5,
    failure_window_seconds=60,
    cooldown_seconds=120,
    half_open_max_probes=1,
)

sheets_circuit = CircuitBreaker(
    name="sheets",
    failure_threshold=5,
    failure_window_seconds=60,
    cooldown_seconds=300,
    half_open_max_probes=1,
)

drive_circuit = CircuitBreaker(
    name="drive",
    failure_threshold=3,
    failure_window_seconds=60,
    cooldown_seconds=300,
    half_open_max_probes=1,
)

zalo_circuit = CircuitBreaker(
    name="zalo_send",
    failure_threshold=10,
    failure_window_seconds=60,
    cooldown_seconds=60,
    half_open_max_probes=2,
)
