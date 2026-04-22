"""Tests cho CircuitBreaker."""

import time
import pytest
from app.reliability.circuit_breaker import CircuitBreaker, CircuitState, CircuitOpenError


def make_cb(**kwargs) -> CircuitBreaker:
    defaults = dict(
        name="test",
        failure_threshold=3,
        failure_window_seconds=60,
        cooldown_seconds=1,  # ngắn để test transition
        half_open_max_probes=1,
    )
    defaults.update(kwargs)
    return CircuitBreaker(**defaults)


class TestCircuitBreakerClosed:
    def test_initial_state_closed(self):
        cb = make_cb()
        assert cb.state == CircuitState.CLOSED

    def test_can_attempt_when_closed(self):
        cb = make_cb()
        assert cb.can_attempt() is True

    def test_is_not_open_when_closed(self):
        cb = make_cb()
        assert cb.is_open() is False

    def test_success_keeps_closed(self):
        cb = make_cb()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_single_failure_stays_closed(self):
        cb = make_cb(failure_threshold=3)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_failures_below_threshold_stay_closed(self):
        cb = make_cb(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerOpen:
    def test_opens_at_threshold(self):
        cb = make_cb(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_cannot_attempt_when_open(self):
        cb = make_cb(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.can_attempt() is False

    def test_is_open_returns_true(self):
        cb = make_cb(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open() is True

    def test_success_clears_failure_count(self):
        cb = make_cb(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # reset
        cb.record_failure()  # start fresh
        assert cb.state == CircuitState.CLOSED  # chưa đủ threshold


class TestCircuitBreakerHalfOpen:
    def test_transitions_to_half_open_after_cooldown(self):
        cb = make_cb(failure_threshold=2, cooldown_seconds=0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Trigger tick by calling can_attempt (or is_open)
        time.sleep(0.01)  # cooldown=0 → đã hết ngay
        cb.can_attempt()
        assert cb.state == CircuitState.HALF_OPEN

    def test_probe_success_closes(self):
        cb = make_cb(failure_threshold=2, cooldown_seconds=0)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.01)
        cb.can_attempt()  # → HALF_OPEN, probe used
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_probe_failure_reopens(self):
        cb = make_cb(failure_threshold=2, cooldown_seconds=0)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.01)
        cb.can_attempt()  # → HALF_OPEN
        cb.record_failure()  # probe failed
        assert cb.state == CircuitState.OPEN

    def test_half_open_max_probes(self):
        cb = make_cb(failure_threshold=2, cooldown_seconds=0, half_open_max_probes=1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.01)
        assert cb.can_attempt() is True   # first probe OK
        assert cb.can_attempt() is False  # max reached


class TestCircuitBreakerReset:
    def test_reset_to_closed(self):
        cb = make_cb(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_attempt() is True


class TestCircuitBreakerWindowExpiry:
    def test_old_failures_expire_from_window(self):
        cb = make_cb(failure_threshold=3, failure_window_seconds=1)
        cb.record_failure()
        cb.record_failure()
        # Simulate window expiry by time manipulation
        cb._failures = [f - 2 for f in cb._failures]  # shift to past
        cb.record_failure()  # trigger cleanup
        # Sau cleanup, chỉ còn 1 failure (trong window)
        assert cb.state == CircuitState.CLOSED


class TestCircuitOpenError:
    def test_error_has_circuit_name(self):
        err = CircuitOpenError("llm")
        assert err.circuit_name == "llm"
        assert "llm" in str(err)
