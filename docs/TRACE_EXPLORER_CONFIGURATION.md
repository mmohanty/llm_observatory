# Trace Explorer Configuration Guide (Production)

This document explains how to configure and operate Trace Explorer for a production-grade application with existing services.

## Start Here (Copy/Paste Path)

If you are integrating into an existing app, follow this exact order:

1. Add backend config (`backend/.env`)
2. Send infer request with `usecase_id`
3. Emit root + child spans/events
4. Use traced thread helper for background work
5. Verify with Trace Explorer APIs

### 1) Backend .env

```env
SIMULATE_TRAFFIC=false
KAFKA_ENABLED=false
TELEMETRY_QUEUE_SIZE=10000
TELEMETRY_DB_PATH=backend/data/telemetry_history.db

OTEL_ENABLED=true
OTEL_SERVICE_NAME=llm-observability-api
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
```

### 2) Infer API Request (must include usecase_id)

```bash
curl -X POST "http://localhost:8000/api/router/infer" \
  -H "content-type: application/json" \
  -H "model_id: gpt-4.1" \
  -d '{
    "usecase_id": "claims-pricing",
    "tenant_id": "tenant-a",
    "prompt": "Summarize policy updates",
    "use_oracle": true
  }'
```

### 3) Emit trace events in your Python flow

```python
from datetime import datetime, timezone, timedelta
import uuid
from app.models import TelemetryEvent
from app.main import publish_event

def emit_stage(
    *,
    request_id: str,
    trace_id: str,
    usecase_id: str,
    model_id: str,
    stage: str,
    service: str,
    status: str,
    latency_ms: int,
    parent_span_id: str | None = None,
):
    end_ts = datetime.now(timezone.utc)
    start_ts = end_ts - timedelta(milliseconds=max(0, latency_ms))
    span_id = uuid.uuid4().hex[:16]
    publish_event(
        TelemetryEvent(
            request_id=request_id,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            stage=stage,
            component=service,
            timestamp=end_ts,
            start_ts=start_ts,
            end_ts=end_ts,
            usecase_id=usecase_id,
            user_id=usecase_id,  # compatibility field
            model_id=model_id,
            service=service,
            status=status,
            latency_ms=latency_ms,
        )
    )
    return span_id

# Example
request_id = str(uuid.uuid4())
trace_id = request_id
usecase_id = "claims-pricing"
root = emit_stage(
    request_id=request_id,
    trace_id=trace_id,
    usecase_id=usecase_id,
    model_id="gpt-4.1",
    stage="validation",
    service="orchestrator",
    status="success",
    latency_ms=6,
)
emit_stage(
    request_id=request_id,
    trace_id=trace_id,
    usecase_id=usecase_id,
    model_id="gpt-4.1",
    stage="model_call",
    service="router",
    status="success",
    latency_ms=210,
    parent_span_id=root,
)
```

### 4) Background thread instrumentation (recommended)

```python
from app.tracing import TraceEventContext, run_traced_thread
from app.main import publish_event

ctx = TraceEventContext(
    request_id=request_id,
    trace_id=trace_id,
    user_id=usecase_id,   # compatibility field
    model_id="gpt-4.1",
    tenant_id="tenant-a",
    provider="openai",
    region="us-east-1",
    usecase_id=usecase_id,
)

def read_config():
    # your blocking I/O
    return {"source": "oracle", "table": "routing_config"}

handle = run_traced_thread(
    context=ctx,
    parent_span_id=root,
    stage="config_read",
    service="oracle",
    target=read_config,
    append_event=publish_event,
    success_status_code=200,
    failure_status_code=503,
)
handle.join(timeout=2.0)
if handle.error:
    print("config_read failed:", handle.error)
```

### 5) API verification (what UI calls)

```bash
curl "http://localhost:8000/api/traces/usecases?limit=50"
curl "http://localhost:8000/api/traces/requests?usecase_id=claims-pricing&limit=50"
curl "http://localhost:8000/api/traces/requests?usecase_id=claims-pricing&request_id=<request-id>"
curl "http://localhost:8000/api/traces/<trace-id>"
```

## 1. Purpose

Trace Explorer helps answer:
- Which requests are failing for a given `usecase_id`?
- Where is time spent in the request path?
- Which stage/component failed?
- What branch path was executed in parallel flows?

It is designed for:
- real-time triage
- short-term forensic analysis
- branch-aware request tracing

## 2. Core Concepts

- `trace_id`: Groups all spans for one end-to-end request graph.
- `request_id`: External request identifier shown in UI and APIs.
- `span_id`: Unique node id for a stage execution.
- `parent_span_id`: Parent relationship for DAG/tree rendering.
- `usecase_id`: Business/use-case partition key used across filters.
- `service`: Runtime service emitting event (`router`, `armor`, `mongo`, `oracle`, etc).
- `stage`: Logical step (`validation`, `config_read`, `rest_call`, `model_call`, etc).

## 3. Event Contract

Trace Explorer relies on telemetry events with these required fields:

```json
{
  "request_id": "uuid",
  "trace_id": "uuid-or-otel-trace-id",
  "span_id": "16hex",
  "parent_span_id": "16hex-or-null",
  "timestamp": "2026-03-02T12:00:00Z",
  "start_ts": "2026-03-02T11:59:59.900Z",
  "end_ts": "2026-03-02T12:00:00Z",
  "usecase_id": "claims-pricing",
  "user_id": "claims-pricing",
  "service": "router",
  "stage": "model_call",
  "status": "success",
  "latency_ms": 100,
  "model_id": "gpt-4.1",
  "provider": "openai",
  "region": "us-east-1",
  "details": {}
}
```

Notes:
- `usecase_id` is the primary business key.
- `user_id` is still stored for backward compatibility in current schema and should mirror `usecase_id`.
- `parent_span_id` enables branch rendering.

## 4. API Endpoints Used by Trace Explorer

- `GET /api/traces/usecases`
  - list usecases with request counts and last activity
  - filters: `q`, `time_from`, `time_to`, `limit`
- `GET /api/traces/requests`
  - list requests for selected usecase
  - filters: `usecase_id`, `request_id`, `model_id`, `status`, `time_from`, `time_to`, `limit`
- `GET /api/traces/{trace_id}`
  - full span graph + metadata for one trace

Compatibility:
- `GET /api/traces/users` currently maps to usecases and is deprecated.

## 5. Backend Configuration

Path: `backend/app/settings.py`

Critical settings:
- `TELEMETRY_DB_PATH`
  - durable SQLite history path
- `TELEMETRY_QUEUE_SIZE`
  - in-memory async queue size for non-blocking ingestion
- `SIMULATE_TRAFFIC`
  - should be `false` in production
- `KAFKA_ENABLED`
  - set `true` when ingesting from Kafka consumer

Recommended production defaults:
- `SIMULATE_TRAFFIC=false`
- `TELEMETRY_QUEUE_SIZE=10000` (or higher under load test)
- `TELEMETRY_DB_PATH` on persistent volume

## 5.1 How To Configure (Step-by-Step)

Use this as the implementation checklist for an existing production application.

1. Configure backend runtime
   Create/update `backend/.env`:
   ```env
   SIMULATE_TRAFFIC=false
   KAFKA_ENABLED=false
   TELEMETRY_QUEUE_SIZE=10000
   TELEMETRY_DB_PATH=backend/data/telemetry_history.db

   OTEL_ENABLED=true
   OTEL_SERVICE_NAME=llm-observability-api
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
   ```

2. Ensure every request sets `usecase_id`
   - `POST /api/router/infer` payload must include `usecase_id`.
   - Keep `tenant_id` for tenant partitioning.
   - Example:
   ```json
   {
     "usecase_id": "claims-pricing",
     "tenant_id": "tenant-a",
     "prompt": "Summarize policy deltas",
     "use_oracle": true
   }
   ```

3. Emit stage telemetry with parent-child links
   - Root stage: `validation` (or your ingress stage).
   - For each downstream call, emit a child span/event with:
     - `trace_id`, `span_id`, `parent_span_id`
     - `service`, `stage`, `status`, `latency_ms`
     - `usecase_id`, `request_id`
   - For parallel calls, use same `parent_span_id` to create branches.

4. Use traced thread wrapper for async/threaded work
   - For spawned threads, use `run_traced_thread(...)`.
   - This guarantees:
     - child span creation
     - exception capture + failure telemetry
     - reliable span close

5. Validate Trace Explorer APIs
   - Usecase list:
     - `GET /api/traces/usecases?limit=300`
   - Request list by usecase:
     - `GET /api/traces/requests?usecase_id=claims-pricing&limit=300`
   - Request-id filter:
     - `GET /api/traces/requests?usecase_id=claims-pricing&request_id=<uuid>`
   - Full trace:
     - `GET /api/traces/{trace_id}`

6. Configure frontend API target
   - Set frontend env:
   ```env
   VITE_API_BASE=http://localhost:8000
   ```
   - Trace Explorer uses:
     - usecase search + pagination
     - request pagination
     - request-id filter
     - time/status filters

7. Production hardening checks
   - Confirm queue does not overflow under peak traffic.
   - Confirm shutdown drains queue and persists final events.
   - Confirm durable history file path is on persistent storage.
   - Confirm OTLP exporter is reachable (or disable explicitly).

## 6. Trace Instrumentation Pattern

Emit one event per stage with:
- stage name
- component/service
- status
- latency
- parent-child relation

For threaded/background steps, use traced helper (`run_traced_thread`) so child spans are created and failures are captured with stack traces.

Expected behavior:
- Every request starts with root span (`validation` or equivalent).
- Downstream calls set `parent_span_id` to previous logical stage.
- Parallel calls share same parent and branch naturally.

## 7. Branching Model (How DAG Is Captured)

Single-path:
- `validation -> model_armor -> config_read -> model_call -> response_write`

Branched-path example:
- `validation`
- child A: `model_armor`
- child B: `config_read(mongo)`
- child C: `config_read(oracle)`
- child D: `rest_call(policy-api)`
- join to `model_call`
- `response_write`

Implementation rule:
- For parallel tasks, assign the same `parent_span_id`.
- Do not overwrite span ids between retries; create new span for each attempt.

## 8. Existing App Integration (No Signature Changes)

For large existing codebases:
- Use context propagation (`contextvars`) to hold `trace_id`, `request_id`, `usecase_id`.
- Initialize context at request entry (middleware/router boundary).
- Access context in deep functions/classes without adding parameters to every signature.

When new threads are spawned:
- Use traced thread wrapper so context is copied, child span is emitted, and exceptions are telemetry-visible.

## 8.1 Existing Code Integration Playbook (Minimal Refactor)

If your codebase is already large, do this in phases so you do not break existing APIs.

### Phase 1: Capture root context at request entry

At your API boundary (FastAPI route/middleware), set:
- `request_id`
- `trace_id`
- `usecase_id`
- `model_id`

Use `TraceEventContext` + `bind_trace_event_context(...)` once at entry, then keep business methods unchanged.

```python
from app.tracing import TraceEventContext, bind_trace_event_context, current_trace_id_hex
import uuid

request_id = str(uuid.uuid4())
trace_id = current_trace_id_hex(default=request_id) or request_id
usecase_id = payload.usecase_id

ctx = TraceEventContext(
    request_id=request_id,
    trace_id=trace_id,
    user_id=usecase_id,  # compatibility field
    model_id=model_id,
    tenant_id=payload.tenant_id,
    provider=provider,
    region=region,
    usecase_id=usecase_id,
)

with bind_trace_event_context(ctx):
    # existing orchestrator call chain (unchanged signatures)
    result = service.execute(payload)
```

### Phase 2: Add stage spans around existing methods

Wrap existing operations with a tiny helper that emits telemetry before returning.

```python
from time import perf_counter
from app.main import publish_event
from app.models import TelemetryEvent
from datetime import datetime, timezone, timedelta
import uuid

def trace_stage(*, request_id, trace_id, usecase_id, model_id, service, stage, parent_span_id=None):
    def decorator(fn):
        def wrapped(*args, **kwargs):
            t0 = perf_counter()
            status = "success"
            err = None
            try:
                return fn(*args, **kwargs)
            except Exception as ex:
                status = "failure"
                err = str(ex)
                raise
            finally:
                latency_ms = int((perf_counter() - t0) * 1000)
                end_ts = datetime.now(timezone.utc)
                start_ts = end_ts - timedelta(milliseconds=max(0, latency_ms))
                publish_event(TelemetryEvent(
                    request_id=request_id,
                    trace_id=trace_id,
                    span_id=uuid.uuid4().hex[:16],
                    parent_span_id=parent_span_id,
                    usecase_id=usecase_id,
                    user_id=usecase_id,
                    model_id=model_id,
                    service=service,
                    stage=stage,
                    component=service,
                    status=status,
                    error=err,
                    timestamp=end_ts,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    latency_ms=latency_ms,
                ))
        return wrapped
    return decorator
```

Use it around existing methods (no method signature changes required).

### Phase 3: Parallel/Threaded calls

For thread-based work, do not create raw threads directly. Use `run_traced_thread(...)`.

```python
handle = run_traced_thread(
    context=ctx,
    parent_span_id=parent_span_id,
    stage="config_read",
    service="oracle",
    target=load_config,
    append_event=publish_event,
    success_status_code=200,
    failure_status_code=503,
)
handle.join(timeout=2.0)
if handle.error:
    # decide retry/fallback
    ...
```

This gives:
- child span creation
- exception capture
- failure telemetry with stack
- reliable close

### Phase 4: Branch modeling in existing workflows

When one stage calls multiple downstream systems in parallel:
- give all child spans the same `parent_span_id`
- emit each branch as separate span
- join with a follow-up stage (for example `model_call` or `response_write`)

This is what Trace Explorer uses to render branch DAG/tree.

### Phase 5: Migrate old `user_id` logic safely

If old code expects `user_id`:
- keep writing `user_id = usecase_id` in telemetry for compatibility
- use `usecase_id` for all new filters and UI
- remove old `user_id` dependencies incrementally

### Practical rollout for existing service classes

1. Add tracing at one API endpoint only.
2. Instrument 3-5 critical stages first (`validation`, `config_read`, `rest_call`, `model_call`, `response_write`).
3. Confirm trace graph correctness in UI.
4. Expand to all endpoints/usecases.
5. Enforce a stage naming convention (no ad-hoc names in prod).

## 9. Error and Retry Semantics

Failure event requirements:
- `status="failure"`
- `status_code` (if available)
- `error` string
- stack/details in `details`

Retry modeling:
- Emit separate span per attempt.
- Include `details.attempt` and `details.max_attempts`.
- Final failure should be explicit on terminal stage.

## 10. Performance and Data Retention

Current design:
- request path is non-blocking via queue
- persistence is async via dispatcher
- UI reads durable history from SQLite

Production recommendations:
- Move long-term history to OLAP/warehouse (ClickHouse/BigQuery/OpenSearch).
- Keep SQLite only for local/dev or short retention.
- Add periodic compaction/TTL job for `telemetry_events`.

Suggested retention split:
- hot (UI): 1-7 days
- warm (ops): 30-90 days
- cold (audit): object storage/archive

## 11. OpenTelemetry Alignment

Use OTEL as source of truth for distributed traces:
- inbound HTTP auto-instrumentation
- propagate context to downstream calls
- export to OTLP collector

Keep custom telemetry events for:
- dashboard-specific fields (`usecase_id`, token stats, model/provider tags)
- real-time animated UI

Best practice:
- map OTEL span ids to telemetry `span_id` where possible for cross-tool correlation.

## 12. UI Behavior and Filters

Trace Explorer supports:
- usecase search/filter
- request-id filter
- time window filter (`15m`, `1h`, `6h`, `24h`, `custom`, `all`)
- status filter
- pagination on Usecase and Requests panels
- collapsed/expanded side panels

Request id display:
- shows `...last4` in grid for space management
- full value on hover tooltip

## 13. SLO/SLA and Alerting Guidance

Trace Explorer itself is diagnostic; health alerting is computed in model metrics.
Use trace data to validate:
- p95 stage latencies
- failure concentration by stage
- external dependency impact (`mongo`, `oracle`, `rest_call`)

Operational thresholds to define:
- max acceptable `model_call` p95 latency
- max acceptable `config_read` p95 latency
- failure-rate by stage

## 14. Rollout Plan

1. Enable trace events on one usecase only.
2. Validate DAG correctness in Trace Explorer.
3. Add parallel-stage instrumentation.
4. Enable durable history and load test queue depth.
5. Roll out to more usecases progressively.
6. Decommission deprecated `/api/traces/users` clients.

## 15. Validation Checklist

- Every request has one `trace_id`.
- Every non-root span has a valid `parent_span_id`.
- `usecase_id` is present on all events.
- Failure spans include error detail.
- Request list and trace detail counts match for same time window.
- No queue overflow under expected peak.
- Shutdown drains queue cleanly.

## 16. Example Production Request

```bash
curl -X POST "http://localhost:8000/api/router/infer" \
  -H "content-type: application/json" \
  -H "model_id: gpt-4.1" \
  -d '{
    "usecase_id": "claims-pricing",
    "tenant_id": "tenant-a",
    "prompt": "Summarize these policy changes",
    "use_oracle": true
  }'
```

## 17. Troubleshooting

- Requests visible but no spans:
  - verify `trace_id/span_id/parent_span_id` emission
- Requests visible but wrong usecase grouping:
  - verify `usecase_id` is populated consistently
- Missing branch visualization:
  - check whether all spans are emitted with same parent for parallel tasks
- Stale data:
  - verify durable store writes and time window filters
