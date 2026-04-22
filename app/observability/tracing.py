"""OpenTelemetry tracing setup."""

from __future__ import annotations

import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

log = structlog.get_logger()

_tracer: trace.Tracer | None = None


def setup_tracing(otel_exporter: str = "console", otel_endpoint: str = "") -> None:
    global _tracer
    provider = TracerProvider()

    if otel_exporter == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif otel_exporter == "jaeger":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=otel_endpoint))
            )
        except ImportError:
            log.warning("tracing.jaeger_exporter_not_installed")
    # "none" → no exporter

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("trip-treasurer")
    log.info("tracing.initialized", exporter=otel_exporter)


def get_tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer("trip-treasurer")
    return _tracer
