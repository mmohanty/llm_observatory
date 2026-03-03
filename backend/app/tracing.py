from __future__ import annotations

import contextvars
import threading
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Iterator

from .models import TelemetryEvent

try:
    from opentelemetry import context as otel_context
    from opentelemetry import trace as otel_trace
    from opentelemetry.trace import Status, StatusCode
except Exception:  # pragma: no cover - optional dependency fallback
    otel_context = None
    otel_trace = None
    Status = None
    StatusCode = None


@dataclass(frozen=True)
class TraceEventContext:
    request_id: str
    trace_id: str
    user_id: str
    model_id: str
    tenant_id: str
    provider: str
    region: str
    usecase_id: str


_TRACE_EVENT_CTX: contextvars.ContextVar[TraceEventContext | None] = contextvars.ContextVar(
    "trace_event_context", default=None
)


@dataclass
class TracedThreadHandle:
    thread: threading.Thread
    seed_span_id: str
    state: dict[str, Any]

    @property
    def span_id(self) -> str:
        # Returns actual emitted span_id when available; otherwise seed.
        return self.state.get("span_id") or self.seed_span_id

    @property
    def error(self) -> BaseException | None:
        return self.state.get("error")

    @property
    def error_stack(self) -> str | None:
        return self.state.get("error_stack")

    def join(self, timeout: float | None = None) -> Any:
        self.thread.join(timeout=timeout)
        return self.state.get("result")


def _to_hex_trace_id(value: int) -> str:
    return f"{value:032x}"


def _to_hex_span_id(value: int) -> str:
    return f"{value:016x}"


def current_trace_id_hex(default: str | None = None) -> str | None:
    if otel_trace is None:
        return default
    span = otel_trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return default
    return _to_hex_trace_id(ctx.trace_id)


def current_span_id_hex(default: str | None = None) -> str | None:
    if otel_trace is None:
        return default
    span = otel_trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return default
    return _to_hex_span_id(ctx.span_id)


@contextmanager
def bind_trace_event_context(ctx: TraceEventContext) -> Iterator[None]:
    token = _TRACE_EVENT_CTX.set(ctx)
    try:
        yield
    finally:
        _TRACE_EVENT_CTX.reset(token)


def get_bound_trace_event_context() -> TraceEventContext | None:
    return _TRACE_EVENT_CTX.get()


def run_traced_thread(
    *,
    context: TraceEventContext,
    parent_span_id: str | None,
    stage: str,
    service: str,
    component: str | None = None,
    target: Callable[..., Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    append_event: Callable[[TelemetryEvent], None],
    latency_ms_hint: int | None = None,
    success_status_code: int = 200,
    failure_status_code: int = 500,
    base_details: dict[str, Any] | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    daemon: bool = True,
) -> TracedThreadHandle:
    """Run target in a thread and emit one child span event reliably.

    Production behavior:
    - Propagates OpenTelemetry context into the worker thread.
    - Creates child span for the worker stage.
    - Records exceptions on span and in telemetry event details.
    - Emits end event from finally so spans always close.
    """

    state: dict[str, Any] = {"result": None, "error": None, "error_stack": None}
    payload_details = dict(base_details or {})
    thread_kwargs = dict(kwargs or {})
    parent_ctx = otel_context.get_current() if otel_context is not None else None
    tracer = otel_trace.get_tracer("app.tracing") if otel_trace is not None else None

    seed_span_id = uuid.uuid4().hex[:16]

    def _runner() -> None:
        token = None
        if otel_context is not None and parent_ctx is not None:
            token = otel_context.attach(parent_ctx)

        start_ts = datetime.now(UTC)
        status = "success"
        status_code = success_status_code
        error: str | None = None
        latency_ms = max(0, int(latency_ms_hint or 0))
        trace_id = context.trace_id
        span_id = seed_span_id
        effective_parent_span_id = parent_span_id

        try:
            if tracer is not None:
                with tracer.start_as_current_span(f"{service}.{stage}") as span:
                    span_ctx = span.get_span_context()
                    if span_ctx and span_ctx.is_valid:
                        trace_id = _to_hex_trace_id(span_ctx.trace_id)
                        span_id = _to_hex_span_id(span_ctx.span_id)
                    if hasattr(span, "parent") and span.parent and span.parent.is_valid:
                        effective_parent_span_id = _to_hex_span_id(span.parent.span_id)

                    try:
                        state["result"] = target(*args, **thread_kwargs)
                    except Exception as exc:  # noqa: BLE001
                        status = "failure"
                        status_code = failure_status_code
                        error = str(exc)
                        state["error"] = exc
                        state["error_stack"] = traceback.format_exc()
                        payload_details["exception_type"] = exc.__class__.__name__
                        payload_details["stack"] = state["error_stack"]
                        if Status is not None and StatusCode is not None:
                            span.set_status(Status(StatusCode.ERROR, str(exc)))
                        span.record_exception(exc)
            else:
                state["result"] = target(*args, **thread_kwargs)
        except Exception as exc:  # noqa: BLE001
            status = "failure"
            status_code = failure_status_code
            error = str(exc)
            state["error"] = exc
            state["error_stack"] = traceback.format_exc()
            payload_details["exception_type"] = exc.__class__.__name__
            payload_details["stack"] = state["error_stack"]
        finally:
            end_ts = datetime.now(UTC)
            if latency_ms <= 0:
                latency_ms = int(max(0.0, (end_ts - start_ts).total_seconds() * 1000))
            else:
                start_ts = end_ts - timedelta(milliseconds=latency_ms)

            append_event(
                TelemetryEvent(
                    request_id=context.request_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=effective_parent_span_id,
                    stage=stage,
                    component=component or service,
                    timestamp=end_ts,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    usecase_id=context.usecase_id,
                    user_id=context.user_id,
                    model_id=context.model_id,
                    tenant_id=context.tenant_id,
                    provider=context.provider,
                    region=context.region,
                    service=service,
                    status=status,  # type: ignore[arg-type]
                    status_code=status_code,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    cost_usd=cost_usd,
                    error=error,
                    details=payload_details,
                )
            )
            state["span_id"] = span_id
            if token is not None and otel_context is not None:
                otel_context.detach(token)

    thread = threading.Thread(target=_runner, name=f"trace-{stage}-{seed_span_id[:6]}", daemon=daemon)
    thread.start()
    return TracedThreadHandle(thread=thread, seed_span_id=seed_span_id, state=state)
