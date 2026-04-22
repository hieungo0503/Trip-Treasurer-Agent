"""Prometheus metrics — business, cost, reliability."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Business ─────────────────────────────────────────────────────────────────

trips_created_total = Counter(
    "agent_trips_created_total",
    "Number of trips created",
)
expenses_committed_total = Counter(
    "agent_expenses_committed_total",
    "Number of expenses committed",
    ["category"],
)
contributions_committed_total = Counter(
    "agent_contributions_committed_total",
    "Number of contributions committed",
    ["kind"],
)
active_trips_gauge = Gauge(
    "agent_active_trips_count",
    "Number of trips in ACTIVE state",
)

# ── Cost ──────────────────────────────────────────────────────────────────────

llm_tokens_total = Counter(
    "agent_llm_tokens_total",
    "LLM tokens consumed",
    ["direction", "model"],  # direction = input|output
)
sheet_api_calls_total = Counter(
    "agent_sheet_api_calls_total",
    "Google Sheet API calls",
    ["operation"],
)

# ── Reliability ───────────────────────────────────────────────────────────────

circuit_state_gauge = Gauge(
    "agent_circuit_state",
    "Circuit breaker state: 0=closed, 1=half_open, 2=open",
    ["name"],
)
outbox_pending_gauge = Gauge(
    "agent_sheet_outbox_pending_count",
    "Number of pending sheet_outbox items",
)
webhook_latency_histogram = Histogram(
    "agent_webhook_latency_seconds",
    "Webhook processing latency",
    ["intent"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0],
)
parse_accuracy_gauge = Gauge(
    "agent_parse_accuracy",
    "Parser accuracy on golden dataset",
    ["intent"],
)

# ── Requests ──────────────────────────────────────────────────────────────────

messages_received_total = Counter(
    "agent_messages_received_total",
    "Total messages received from Zalo",
)
messages_replied_total = Counter(
    "agent_messages_replied_total",
    "Total messages replied to user",
    ["status"],  # status = ok|error
)
