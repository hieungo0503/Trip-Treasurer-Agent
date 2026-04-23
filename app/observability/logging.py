"""
structlog setup — JSON output với trace_id, trip_id, zalo_user_id trên mọi log.
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(log_level: str = "INFO") -> None:
    """Gọi 1 lần khi khởi động app."""
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_trace_context,
    ]

    structlog.configure(
        processors=shared_processors + [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Cũng config stdlib logging để bắt log từ thư viện khác
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.getLevelName(log_level.upper()),
    )


def _add_trace_context(
    logger: object, method: str, event_dict: dict
) -> dict:
    """Inject OpenTelemetry trace_id/span_id vào log nếu có."""
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span.is_recording():
            ctx = span.get_span_context()
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except Exception:
        pass
    return event_dict


# Helpers để bind request-scoped context vào log
def bind_request_context(
    trace_id: str | None = None,
    zalo_user_id: str | None = None,
    trip_id: str | None = None,
    member_id: str | None = None,
) -> None:
    ctx = {}
    if trace_id:
        ctx["trace_id"] = trace_id
    if zalo_user_id:
        ctx["zalo_user_id"] = zalo_user_id
    if trip_id:
        ctx["trip_id"] = trip_id
    if member_id:
        ctx["member_id"] = member_id
    structlog.contextvars.bind_contextvars(**ctx)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()
