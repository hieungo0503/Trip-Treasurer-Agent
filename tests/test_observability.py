"""
Tests cho app/observability/ — logging, tracing, metrics.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ── Logging ───────────────────────────────────────────────────────────────────

class TestLogging:
    def test_setup_logging_runs_without_error(self):
        """setup_logging chạy không crash và gọi structlog.configure."""
        from app.observability.logging import setup_logging
        with patch("structlog.configure"), patch("logging.basicConfig"):
            setup_logging("WARNING")

    def test_setup_logging_debug_level(self):
        from app.observability.logging import setup_logging
        with patch("structlog.configure"), patch("logging.basicConfig"):
            setup_logging("DEBUG")

    def test_bind_and_clear_request_context(self):
        from app.observability.logging import bind_request_context, clear_request_context
        bind_request_context(
            trace_id="trace-123",
            zalo_user_id="user-456",
            trip_id="TRIP-001",
            member_id="M001",
        )
        clear_request_context()

    def test_bind_partial_context(self):
        """bind_request_context không bắt buộc tất cả fields."""
        from app.observability.logging import bind_request_context, clear_request_context
        bind_request_context(trace_id="abc")
        clear_request_context()

    def test_bind_empty_context(self):
        from app.observability.logging import bind_request_context, clear_request_context
        bind_request_context()
        clear_request_context()

    def test_add_trace_context_no_otel(self):
        """_add_trace_context phải graceful nếu opentelemetry không có active span."""
        from app.observability.logging import _add_trace_context
        event_dict = {"event": "test"}
        result = _add_trace_context(None, "info", event_dict)
        assert result is event_dict

    def test_add_trace_context_with_recording_span(self):
        """_add_trace_context inject trace_id khi span đang record."""
        from app.observability.logging import _add_trace_context

        mock_ctx = MagicMock()
        mock_ctx.trace_id = 0xDEADBEEF
        mock_ctx.span_id = 0xCAFEBABE

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_span.get_span_context.return_value = mock_ctx

        with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
            event_dict = {"event": "test"}
            result = _add_trace_context(None, "info", event_dict)

        assert "trace_id" in result
        assert "span_id" in result

    def test_add_trace_context_span_not_recording(self):
        """_add_trace_context không inject khi span không record."""
        from app.observability.logging import _add_trace_context

        mock_span = MagicMock()
        mock_span.is_recording.return_value = False

        with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
            event_dict = {"event": "test"}
            result = _add_trace_context(None, "info", event_dict)

        assert "trace_id" not in result

    def test_add_trace_context_import_error(self):
        """_add_trace_context graceful nếu opentelemetry import fail."""
        from app.observability.logging import _add_trace_context

        with patch("opentelemetry.trace.get_current_span", side_effect=Exception("import fail")):
            event_dict = {"event": "test"}
            result = _add_trace_context(None, "info", event_dict)

        assert result is event_dict


# ── Tracing ───────────────────────────────────────────────────────────────────

class TestTracing:
    def setup_method(self):
        """Reset global _tracer trước mỗi test."""
        import app.observability.tracing as tracing_mod
        tracing_mod._tracer = None

    def test_setup_tracing_none(self):
        """otel_exporter='none' → không crash."""
        from app.observability.tracing import setup_tracing
        with patch("app.observability.tracing.log"):
            setup_tracing(otel_exporter="none")

    def test_setup_tracing_console(self):
        from app.observability.tracing import setup_tracing
        with patch("app.observability.tracing.log"):
            setup_tracing(otel_exporter="console")

    def test_setup_tracing_jaeger_import_error(self):
        """jaeger exporter không có → warning, không crash."""
        from app.observability.tracing import setup_tracing
        with patch("app.observability.tracing.log"), \
             patch.dict("sys.modules", {
                 "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None
             }):
            setup_tracing(otel_exporter="jaeger", otel_endpoint="localhost:4317")

    def test_get_tracer_after_setup(self):
        from app.observability.tracing import setup_tracing, get_tracer
        with patch("app.observability.tracing.log"):
            setup_tracing(otel_exporter="none")
        tracer = get_tracer()
        assert tracer is not None

    def test_get_tracer_without_setup(self):
        """get_tracer() khi _tracer=None → khởi tạo tự động."""
        import app.observability.tracing as tracing_mod
        tracing_mod._tracer = None

        from app.observability.tracing import get_tracer
        tracer = get_tracer()
        assert tracer is not None

    def test_get_tracer_returns_same_instance(self):
        """Gọi get_tracer() 2 lần → cùng instance."""
        from app.observability.tracing import setup_tracing, get_tracer
        with patch("app.observability.tracing.log"):
            setup_tracing(otel_exporter="none")
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2


# ── Metrics ───────────────────────────────────────────────────────────────────

class TestMetrics:
    def test_metrics_importable(self):
        from app.observability.metrics import messages_received_total, messages_replied_total
        assert messages_received_total is not None
        assert messages_replied_total is not None

    def test_counter_increment(self):
        from app.observability.metrics import messages_received_total
        messages_received_total.inc()

    def test_replied_labels(self):
        from app.observability.metrics import messages_replied_total
        messages_replied_total.labels(status="ok").inc()
        messages_replied_total.labels(status="error").inc()
