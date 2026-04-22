"""
Circuit Breaker cho 4 external services.
Copy module này vào app/reliability/circuit_breaker.py
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Optional

import structlog
from prometheus_client import Gauge

log = structlog.get_logger()

# Prometheus gauge cho circuit state (0=closed, 1=half_open, 2=open)
_circuit_state_gauge = Gauge(
    "agent_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half_open, 2=open)",
    ["service"],
)


class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Blocking calls
    HALF_OPEN = "half_open" # Probing


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    failure_window_seconds: int = 60
    cooldown_seconds: int = 120
    half_open_max_probes: int = 1

    state: CircuitState = CircuitState.CLOSED
    _failures: list[float] = field(default_factory=list)
    _opened_at: float = 0.0
    _half_open_probes: int = 0
    _lock: Lock = field(default_factory=Lock)

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
            return False  # OPEN

    def record_success(self):
        with self._lock:
            if self.state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                self._transition(CircuitState.CLOSED, "success")
            self._failures.clear()

    def record_failure(self):
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
                self._transition(CircuitState.OPEN, f"threshold {self.failure_threshold}")
                self._opened_at = now

    def _tick(self):
        """Auto-transition OPEN → HALF_OPEN khi cooldown hết."""
        if (self.state == CircuitState.OPEN
                and time.time() - self._opened_at >= self.cooldown_seconds):
            self._transition(CircuitState.HALF_OPEN, "cooldown elapsed")
            self._half_open_probes = 0

    def _transition(self, new_state: CircuitState, reason: str):
        old = self.state
        self.state = new_state
        log.info("circuit_breaker.transition",
                 service=self.name,
                 from_state=old.value,
                 to_state=new_state.value,
                 reason=reason)
        _circuit_state_gauge.labels(service=self.name).set(
            {"closed": 0, "half_open": 1, "open": 2}[new_state.value]
        )

    @property
    def user_facing_message(self) -> Optional[str]:
        """Message gửi user khi circuit OPEN. None nếu CLOSED."""
        if self.state == CircuitState.OPEN:
            msgs = {
                "llm": "Bot đang xử lý chậm, thử lại sau vài phút.",
                "sheets": None,   # Sheet dùng outbox, không cần thông báo user
                "drive": None,
                "zalo_send": None,
            }
            return msgs.get(self.name)
        return None


# ─── Singletons ───────────────────────────────────────────────────────────────

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


# ─── Usage ────────────────────────────────────────────────────────────────────

"""
from app.reliability.circuit_breaker import llm_circuit
from app.reliability.retry import RetriableError

async def call_llm_with_breaker(prompt: str) -> dict:
    if not llm_circuit.can_attempt():
        # Fallback khi LLM circuit OPEN
        msg = llm_circuit.user_facing_message
        if msg:
            raise ServiceUnavailableError(msg)
        # Không có message → dùng rule-based fallback âm thầm
        return rule_parse_fallback(prompt)

    try:
        result = await call_llm(prompt)  # đã có @llm_retry
        llm_circuit.record_success()
        return result
    except Exception:
        llm_circuit.record_failure()
        raise
"""
