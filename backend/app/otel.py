from __future__ import annotations

from typing import Any

from .settings import settings


def configure_otel(app: Any) -> None:
    """Configure OpenTelemetry SDK + FastAPI instrumentation.

    No-op if OTel packages are unavailable or disabled.
    """

    if not settings.otel_enabled:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:
        return

    # Avoid duplicate initialization in reload/multi-import scenarios.
    provider = trace.get_tracer_provider()
    if provider.__class__.__name__ == "TracerProvider":
        try:
            FastAPIInstrumentor().instrument_app(app)
        except Exception:
            pass
        return

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": "1.0.0",
            "deployment.environment": "production",
        }
    )
    tracer_provider = TracerProvider(resource=resource)

    exporter_kwargs: dict[str, Any] = {}
    if settings.otel_exporter_otlp_endpoint:
        exporter_kwargs["endpoint"] = settings.otel_exporter_otlp_endpoint
    exporter = OTLPSpanExporter(**exporter_kwargs)
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(tracer_provider)
    FastAPIInstrumentor().instrument_app(app)

