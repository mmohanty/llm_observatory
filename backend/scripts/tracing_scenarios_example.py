#!/usr/bin/env python3
"""Standalone examples for traced threaded execution.

This script demonstrates:
1) Linear success flow
2) Parallel branches from one parent
3) Worker thread exception capture
4) Nested child spans
5) Reliable close of spans in finally

Run:
  python backend/scripts/tracing_scenarios_example.py
"""

from __future__ import annotations

import json
import random
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from backend.app.models import TelemetryEvent
from backend.app.tracing import (
    TraceEventContext,
    bind_trace_event_context,
    current_trace_id_hex,
    run_traced_thread,
)


def _iso(ts: datetime | None) -> str:
    if not ts:
        return "-"
    return ts.astimezone(UTC).isoformat()


class DemoEmitter:
    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    def append(self, event: TelemetryEvent) -> None:
        self.events.append(event)

    def emit_inline(
        self,
        *,
        ctx: TraceEventContext,
        stage: str,
        service: str,
        parent_span_id: str | None,
        latency_ms: int,
        status: str = "success",
        status_code: int = 200,
        error: str | None = None,
        details: dict | None = None,
    ) -> str:
        span_id = uuid.uuid4().hex[:16]
        end_ts = datetime.now(UTC)
        start_ts = end_ts - timedelta(milliseconds=max(0, latency_ms))
        self.append(
            TelemetryEvent(
                request_id=ctx.request_id,
                trace_id=ctx.trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                stage=stage,
                component=service,
                timestamp=end_ts,
                start_ts=start_ts,
                end_ts=end_ts,
                usecase_id=ctx.usecase_id,
                user_id=ctx.user_id,
                model_id=ctx.model_id,
                tenant_id=ctx.tenant_id,
                provider=ctx.provider,
                region=ctx.region,
                service=service,
                status=status,  # type: ignore[arg-type]
                status_code=status_code,
                latency_ms=latency_ms,
                error=error,
                details=details or {},
            )
        )
        return span_id


def worker_sleep(delay_ms: int, value: str) -> dict:
    time.sleep(delay_ms / 1000.0)
    return {"value": value, "delay_ms": delay_ms}


def worker_fails(delay_ms: int) -> dict:
    time.sleep(delay_ms / 1000.0)
    raise RuntimeError("simulated_upstream_error")


def run_demo_trace() -> list[TelemetryEvent]:
    emitter = DemoEmitter()
    request_id = str(uuid.uuid4())
    trace_id = current_trace_id_hex(default=request_id) or request_id
    ctx = TraceEventContext(
        request_id=request_id,
        trace_id=trace_id,
        user_id="alice",
        model_id="gpt-4.1",
        tenant_id="tenant-a",
        provider="openai",
        region="us-east-1",
        usecase_id="demo-trace",
    )

    with bind_trace_event_context(ctx):
        # 1) Root
        root = emitter.emit_inline(
            ctx=ctx,
            stage="validation",
            service="orchestrator",
            parent_span_id=None,
            latency_ms=8,
            details={"checks": ["auth", "schema", "quota"]},
        )

        # 2) Parallel branches (same parent -> true branching)
        armor = run_traced_thread(
            context=ctx,
            parent_span_id=root,
            stage="model_armor",
            service="armor",
            target=worker_sleep,
            args=(20, "armor_ok"),
            append_event=emitter.append,
            latency_ms_hint=20,
            base_details={"policy": "default"},
        )

        mongo = run_traced_thread(
            context=ctx,
            parent_span_id=root,
            stage="config_read",
            service="mongo",
            target=worker_sleep,
            args=(35, "config_ok"),
            append_event=emitter.append,
            latency_ms_hint=35,
            base_details={"collection": "routing_config"},
        )

        oracle = run_traced_thread(
            context=ctx,
            parent_span_id=root,
            stage="datasource_read",
            service="oracle",
            target=worker_sleep,
            args=(52, "policy_ok"),
            append_event=emitter.append,
            latency_ms_hint=52,
            base_details={"table": "tenant_policy"},
        )

        # Wait for parallel children to finish.
        armor.join()
        mongo.join()
        oracle.join()

        # 3) Nested child from mongo branch.
        rest = run_traced_thread(
            context=ctx,
            parent_span_id=mongo.span_id,
            stage="rest_call",
            service="policy-api",
            target=worker_sleep,
            args=(70, "rest_ok"),
            append_event=emitter.append,
            latency_ms_hint=70,
            base_details={"endpoint": "/v1/policies/evaluate"},
        )
        rest.join()

        # 4) Failure scenario in child thread (exception captured + span closed)
        model = run_traced_thread(
            context=ctx,
            parent_span_id=rest.span_id,
            stage="model_call",
            service="router",
            target=worker_fails if random.random() < 0.75 else worker_sleep,
            args=(120,) if random.random() < 0.75 else (120, "model_ok"),
            append_event=emitter.append,
            latency_ms_hint=120,
            failure_status_code=504,
            base_details={"target_model": ctx.model_id},
        )
        model.join()

        # 5) Final response stage always emitted.
        if model.error:
            emitter.emit_inline(
                ctx=ctx,
                stage="response_write",
                service="orchestrator",
                parent_span_id=model.span_id,
                latency_ms=5,
                status="failure",
                status_code=504,
                error="upstream_timeout",
                details={"reason": str(model.error)},
            )
        else:
            emitter.emit_inline(
                ctx=ctx,
                stage="response_write",
                service="orchestrator",
                parent_span_id=model.span_id,
                latency_ms=5,
                status="success",
                status_code=200,
                details={"result": "ok"},
            )

    # Sort by start time for display.
    return sorted(
        emitter.events,
        key=lambda e: (e.start_ts or e.timestamp, e.timestamp),
    )


def print_summary(events: list[TelemetryEvent]) -> None:
    print(f"trace_id={events[0].trace_id} request_id={events[0].request_id}")
    by_parent: dict[str | None, list[TelemetryEvent]] = defaultdict(list)
    for e in events:
        by_parent[e.parent_span_id].append(e)

    branch_parents = [pid for pid, kids in by_parent.items() if pid and len(kids) > 1]
    print(f"total_spans={len(events)} branched_parents={len(branch_parents)}")

    for e in events:
        print(
            f"{e.stage:15} parent={str(e.parent_span_id)[:8]:8} "
            f"span={str(e.span_id)[:8]:8} status={e.status:7} "
            f"lat={e.latency_ms:4}ms error={e.error or '-'}"
        )

    print("\nExample event JSON:")
    print(json.dumps(events[-1].model_dump(mode="json"), indent=2))


def main() -> None:
    events = run_demo_trace()
    print_summary(events)


if __name__ == "__main__":
    main()
