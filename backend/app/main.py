import asyncio
import json
import random
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from statistics import mean
from time import perf_counter

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .models import (
    DashboardSummary,
    InferenceRequest,
    InferenceResponse,
    ModelCatalogItem,
    ModelCatalogResponse,
    ModelMetric,
    ModelMetricsResponse,
    TelemetryEvent,
    TraceDetailResponse,
    TraceRequestSummary,
    TraceSpan,
    TraceUsecaseSummary,
)
from .history_store import HistoryStore
from .otel import configure_otel
from .settings import settings
from .stream import EventStore
from .tracing import (
    TraceEventContext,
    bind_trace_event_context,
    current_trace_id_hex,
    run_traced_thread,
)

store = EventStore()
history_store = HistoryStore(settings.telemetry_db_path)
TELEMETRY_QUEUE: asyncio.Queue[TelemetryEvent] = asyncio.Queue(maxsize=settings.telemetry_queue_size)
MAIN_LOOP: asyncio.AbstractEventLoop | None = None
BACKGROUND_TASKS: list[asyncio.Task] = []
SHUTDOWN_EVENT = asyncio.Event()
MODEL_ALIASES = {
    "gpt4": "gpt-4.1",
    "gpt-4": "gpt-4.1",
    "gpt-4.1": "gpt-4.1",
    "gpt4o-mini": "gpt-4o-mini",
    "gpt-4o-mini": "gpt-4o-mini",
    "claude sonnet": "claude-sonnet",
    "claude-sonnet": "claude-sonnet",
    "llama 3.3": "llama-3.3",
    "llama-3.3": "llama-3.3",
    "gemini pro": "gemini-2.5-pro",
    "gemini flash": "gemini-2.5-flash",
    "gemini 2.5 pro": "gemini-2.5-pro",
    "gemini 2.5 flash": "gemini-2.5-flash",
    "gemini-2.5-pro": "gemini-2.5-pro",
    "gemini-2.5-flash": "gemini-2.5-flash",
    "gemini 1.5 pro": "gemini-1.5-pro",
    "gemini 1.5 flash": "gemini-1.5-flash",
    "gemini-1.5-pro": "gemini-1.5-pro",
    "gemini-1.5-flash": "gemini-1.5-flash",
    "claude opus": "claude-opus",
    "claude haiku": "claude-haiku",
    "claude-opus": "claude-opus",
    "claude-haiku": "claude-haiku",
    "mistral large": "mistral-large",
    "mixtral 8x7b": "mixtral-8x7b",
    "mistral-large": "mistral-large",
    "mixtral-8x7b": "mixtral-8x7b",
    "deepseek r1": "deepseek-r1",
    "deepseek v3": "deepseek-v3",
    "deepseek-r1": "deepseek-r1",
    "deepseek-v3": "deepseek-v3",
    "qwen 2.5 72b": "qwen-2.5-72b",
    "qwen 2.5 32b": "qwen-2.5-32b",
    "qwen-2.5-72b": "qwen-2.5-72b",
    "qwen-2.5-32b": "qwen-2.5-32b",
    "cohere command r": "cohere-command-r",
    "cohere command r plus": "cohere-command-r-plus",
    "cohere-command-r": "cohere-command-r",
    "cohere-command-r-plus": "cohere-command-r-plus",
    "onprem coder 14b": "onprem-coder-14b",
    "onprem reasoner 32b": "onprem-reasoner-32b",
    "onprem-coder-14b": "onprem-coder-14b",
    "onprem-reasoner-32b": "onprem-reasoner-32b",
}
MODEL_CATALOG = {
    "gpt-4.1": {"provider": "openai", "region": "us-east-1"},
    "gpt-4o-mini": {"provider": "openai", "region": "us-east-1"},
    "gpt-4.5": {"provider": "openai", "region": "us-east-1"},
    "o3-mini": {"provider": "openai", "region": "us-east-1"},
    "o4-mini": {"provider": "openai", "region": "us-east-1"},
    "claude-sonnet": {"provider": "anthropic", "region": "us-west-2"},
    "claude-opus": {"provider": "anthropic", "region": "us-west-2"},
    "claude-haiku": {"provider": "anthropic", "region": "us-west-2"},
    "llama-3.3": {"provider": "meta", "region": "us-central-1"},
    "llama-3.1-70b": {"provider": "meta", "region": "us-central-1"},
    "llama-3.1-8b": {"provider": "meta", "region": "us-central-1"},
    "gemini-2.5-pro": {"provider": "google", "region": "us-central1"},
    "gemini-2.5-flash": {"provider": "google", "region": "us-central1"},
    "gemini-1.5-pro": {"provider": "google", "region": "us-central1"},
    "gemini-1.5-flash": {"provider": "google", "region": "us-central1"},
    "mistral-large": {"provider": "mistral", "region": "eu-west-1"},
    "mixtral-8x7b": {"provider": "mistral", "region": "eu-west-1"},
    "deepseek-r1": {"provider": "deepseek", "region": "ap-southeast-1"},
    "deepseek-v3": {"provider": "deepseek", "region": "ap-southeast-1"},
    "qwen-2.5-72b": {"provider": "alibaba", "region": "ap-southeast-1"},
    "qwen-2.5-32b": {"provider": "alibaba", "region": "ap-southeast-1"},
    "cohere-command-r": {"provider": "cohere", "region": "us-east-1"},
    "cohere-command-r-plus": {"provider": "cohere", "region": "us-east-1"},
    "onprem-coder-14b": {"provider": "on-prem", "region": "dc-1"},
    "onprem-reasoner-32b": {"provider": "on-prem", "region": "dc-1"},
}
TOKEN_COST_PER_1K = {
    "gpt-4.1": 0.01,
    "gpt-4o-mini": 0.002,
    "gpt-4.5": 0.012,
    "o3-mini": 0.006,
    "o4-mini": 0.007,
    "claude-sonnet": 0.008,
    "claude-opus": 0.015,
    "claude-haiku": 0.004,
    "llama-3.3": 0.0015,
    "llama-3.1-70b": 0.0018,
    "llama-3.1-8b": 0.0009,
    "gemini-2.5-pro": 0.007,
    "gemini-2.5-flash": 0.0018,
    "gemini-1.5-pro": 0.006,
    "gemini-1.5-flash": 0.0015,
    "mistral-large": 0.004,
    "mixtral-8x7b": 0.0022,
    "deepseek-r1": 0.0014,
    "deepseek-v3": 0.0012,
    "qwen-2.5-72b": 0.0016,
    "qwen-2.5-32b": 0.0013,
    "cohere-command-r": 0.003,
    "cohere-command-r-plus": 0.0045,
    "onprem-coder-14b": 0.0003,
    "onprem-reasoner-32b": 0.0005,
}
DEFAULT_LATENCY_SLO_MS = 1200.0
DEFAULT_TOKEN_SLO_TPS = 120.0


@asynccontextmanager
async def lifespan(_: FastAPI):
    global MAIN_LOOP
    SHUTDOWN_EVENT.clear()
    MAIN_LOOP = asyncio.get_running_loop()
    BACKGROUND_TASKS.append(asyncio.create_task(telemetry_dispatcher()))
    if settings.simulate_traffic:
        BACKGROUND_TASKS.append(asyncio.create_task(simulate_traffic()))
    if settings.kafka_enabled:
        BACKGROUND_TASKS.append(asyncio.create_task(consume_kafka()))
    yield
    SHUTDOWN_EVENT.set()
    for task in BACKGROUND_TASKS:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    BACKGROUND_TASKS.clear()
    MAIN_LOOP = None


app = FastAPI(title="LLM Observability API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
configure_otel(app)


def _enqueue_event_nonblocking(event: TelemetryEvent) -> None:
    if TELEMETRY_QUEUE.full():
        with suppress(asyncio.QueueEmpty):
            TELEMETRY_QUEUE.get_nowait()
    with suppress(asyncio.QueueFull):
        TELEMETRY_QUEUE.put_nowait(event)


def publish_event(event: TelemetryEvent) -> None:
    # Can be called from async context or worker threads.
    if MAIN_LOOP and MAIN_LOOP.is_running():
        MAIN_LOOP.call_soon_threadsafe(_enqueue_event_nonblocking, event)
    else:
        _enqueue_event_nonblocking(event)


async def telemetry_dispatcher() -> None:
    while not SHUTDOWN_EVENT.is_set() or not TELEMETRY_QUEUE.empty():
        try:
            event = await asyncio.wait_for(TELEMETRY_QUEUE.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        try:
            store.append(event)
            await asyncio.to_thread(history_store.append, event)
        except Exception:
            # Best effort path: keep stream alive even if persistence fails transiently.
            pass


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/events")
async def ingest_event(event: TelemetryEvent) -> dict[str, str]:
    publish_event(event)
    return {"result": "accepted"}


@app.post("/api/router/infer", response_model=InferenceResponse)
async def route_inference(
    request: Request,
    payload: InferenceRequest,
    model_id: str | None = Header(default=None),
):
    model_id = model_id or request.headers.get("model_id") or request.headers.get("model-id")
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id header is required")
    model_id = MODEL_ALIASES.get(model_id.strip().lower(), model_id)
    if model_id not in MODEL_HANDLERS:
        raise HTTPException(status_code=400, detail=f"unsupported model_id: {model_id}")
    meta = MODEL_CATALOG.get(model_id, {"provider": "unknown", "region": "us-central"})

    request_id = str(uuid.uuid4())
    trace_id = current_trace_id_hex(default=request_id) or request_id
    t0 = perf_counter()
    usecase_id = payload.usecase_id or payload.tenant_id
    ctx = TraceEventContext(
        request_id=request_id,
        trace_id=trace_id,
        user_id=usecase_id,
        model_id=model_id,
        tenant_id=payload.tenant_id,
        provider=meta["provider"],
        region=meta["region"],
        usecase_id=usecase_id,
    )

    def emit_event(
        *,
        service: str,
        stage: str,
        status: str,
        latency_ms: int = 0,
        status_code: int | None = None,
        error: str | None = None,
        parent_span_id: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        details: dict | None = None,
    ) -> str:
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
                user_id=usecase_id,
                model_id=model_id,
                tenant_id=payload.tenant_id,
                provider=meta["provider"],
                region=meta["region"],
                service=service,
                status=status,  # type: ignore[arg-type]
                status_code=status_code,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                error=error,
                details=details or {},
            )
        )
        return span_id

    with bind_trace_event_context(ctx):
        validation_span = emit_event(
            service="orchestrator",
            stage="validation",
            status="success",
            latency_ms=random.randint(2, 9),
            status_code=200,
            details={"prompt_chars": len(payload.prompt), "header_model_id": model_id},
        )

        # Stage 1: model armor
        if random.random() < 0.04:
            armor_span = emit_event(
                service="armor",
                stage="model_armor",
                status="failure",
                latency_ms=random.randint(4, 18),
                status_code=403,
                error="policy_violation",
                parent_span_id=validation_span,
                details={"policy": "default-guardrail"},
            )
            emit_event(
                service="orchestrator",
                stage="response_write",
                status="failure",
                latency_ms=random.randint(1, 5),
                status_code=403,
                error="blocked_by_model_armor",
                parent_span_id=armor_span,
            )
            return InferenceResponse(
                request_id=request_id,
                model_id=model_id,
                provider=meta["provider"],
                region=meta["region"],
                tenant_id=payload.tenant_id,
                status="failure",
                output="blocked by model armor",
                input_tokens=0,
                output_tokens=0,
                latency_ms=int((perf_counter() - t0) * 1000),
                cost_usd=0.0,
            )

        armor_span = emit_event(
            service="armor",
            stage="model_armor",
            status="success",
            latency_ms=random.randint(4, 16),
            status_code=200,
            parent_span_id=validation_span,
            details={"policy": "default-guardrail"},
        )

        # Stage 2: persistence sidecar event
        db_service = "oracle" if payload.use_oracle else "mongo"
        config_latency = random.randint(8, 35)

        def _config_read_worker(delay_ms: int) -> dict:
            # Simulates blocking I/O in a worker thread.
            time.sleep(delay_ms / 1000.0)
            if random.random() < 0.03:
                raise RuntimeError(f"{db_service}_read_failed")
            return {"source": db_service, "query": "routing_config"}

        config_handle = run_traced_thread(
            context=ctx,
            parent_span_id=armor_span,
            stage="config_read",
            service=db_service,
            target=_config_read_worker,
            args=(config_latency,),
            append_event=publish_event,
            latency_ms_hint=config_latency,
            success_status_code=200,
            failure_status_code=503,
            base_details={"source": db_service, "query": "routing_config"},
        )
        config_handle.join(timeout=2.0)
        config_span = config_handle.span_id

        if config_handle.error:
            emit_event(
                service="orchestrator",
                stage="response_write",
                status="failure",
                status_code=503,
                latency_ms=random.randint(1, 6),
                error="config_read_failed",
                parent_span_id=config_span,
                details={"thread_error": str(config_handle.error)},
            )
            return InferenceResponse(
                request_id=request_id,
                model_id=model_id,
                provider=meta["provider"],
                region=meta["region"],
                tenant_id=payload.tenant_id,
                status="failure",
                output=f"config read failed: {db_service}",
                input_tokens=0,
                output_tokens=0,
                latency_ms=int((perf_counter() - t0) * 1000),
                cost_usd=0.0,
            )

        # Stage 3: router -> model call
        output, input_tokens, output_tokens, failed = await MODEL_HANDLERS[model_id](payload.prompt)
        latency_ms = int((perf_counter() - t0) * 1000)
        status = "failure" if failed else "success"
        total_tokens = input_tokens + output_tokens
        cost_usd = (total_tokens / 1000.0) * TOKEN_COST_PER_1K.get(model_id, 0.0)

        model_span = emit_event(
            service="router",
            stage="model_call",
            status=status,
            status_code=504 if failed else 200,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            error="upstream_timeout" if failed else None,
            parent_span_id=config_span,
            details={"target_model": model_id, "provider": meta["provider"]},
        )
        emit_event(
            service="orchestrator",
            stage="response_write",
            status=status,
            status_code=504 if failed else 200,
            latency_ms=random.randint(1, 6),
            error="upstream_timeout" if failed else None,
            parent_span_id=model_span,
            details={"output_preview": output[:120]},
        )

    return InferenceResponse(
        request_id=request_id,
        model_id=model_id,
        provider=meta["provider"],
        region=meta["region"],
        tenant_id=payload.tenant_id,
        status=status,
        output=output,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )


@app.get("/api/events/recent", response_model=list[TelemetryEvent])
async def recent_events(limit: int = Query(default=50, le=300)) -> list[TelemetryEvent]:
    return _load_events(limit=limit, newest_first=True)


@app.get("/api/summary", response_model=DashboardSummary)
async def summary() -> DashboardSummary:
    events = _load_events()
    success_count = sum(1 for e in events if e.status == "success")
    failure_count = len(events) - success_count
    return DashboardSummary(
        total_events=len(events),
        success_count=success_count,
        failure_count=failure_count,
        total_input_tokens=sum(e.input_tokens for e in events),
        total_output_tokens=sum(e.output_tokens for e in events),
    )


@app.get("/api/traces/usecases", response_model=list[TraceUsecaseSummary])
async def trace_usecases(
    q: str | None = Query(default=None),
    time_from: datetime | None = Query(default=None),
    time_to: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[TraceUsecaseSummary]:
    usecases: dict[str, dict] = {}
    query = (q or "").strip().lower()
    time_from = _as_utc(time_from)
    time_to = _as_utc(time_to)
    for event in _load_events(time_from=time_from, time_to=time_to):
        usecase_id = event.usecase_id or event.tenant_id or "default"
        if query and query not in usecase_id.lower():
            continue
        if time_from and event.timestamp < time_from:
            continue
        if time_to and event.timestamp > time_to:
            continue
        row = usecases.setdefault(usecase_id, {"request_ids": set(), "last_seen": event.timestamp})
        row["request_ids"].add(event.request_id)
        if event.timestamp > row["last_seen"]:
            row["last_seen"] = event.timestamp

    result = [
        TraceUsecaseSummary(
            usecase_id=usecase_id,
            request_count=len(data["request_ids"]),
            last_seen=data["last_seen"],
        )
        for usecase_id, data in usecases.items()
    ]
    result.sort(key=lambda r: r.last_seen, reverse=True)
    return result[:limit]


@app.get("/api/traces/users", response_model=list[TraceUsecaseSummary], deprecated=True)
async def trace_users_compat(
    q: str | None = Query(default=None),
    time_from: datetime | None = Query(default=None),
    time_to: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[TraceUsecaseSummary]:
    return await trace_usecases(q=q, time_from=time_from, time_to=time_to, limit=limit)


@app.get("/api/traces/requests", response_model=list[TraceRequestSummary])
async def trace_requests(
    usecase_id: str | None = Query(default=None),
    model_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    time_from: datetime | None = Query(default=None),
    time_to: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[TraceRequestSummary]:
    time_from = _as_utc(time_from)
    time_to = _as_utc(time_to)
    traces = _collect_traces(
        usecase_id=usecase_id,
        model_id=model_id,
        status=status,
        request_id=request_id,
        time_from=time_from,
        time_to=time_to,
    )
    summaries = [_build_trace_summary(trace_id, events) for trace_id, events in traces.items()]
    summaries.sort(key=lambda t: t.started_at, reverse=True)
    return summaries[:limit]


@app.get("/api/traces/{trace_id}", response_model=TraceDetailResponse)
async def trace_detail(trace_id: str) -> TraceDetailResponse:
    traces = _collect_traces()
    events = traces.get(trace_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"trace not found: {trace_id}")
    summary = _build_trace_summary(trace_id, events)
    spans = [_event_to_span(event, idx) for idx, event in enumerate(sorted(events, key=lambda e: _event_started_at(e)))]
    return TraceDetailResponse(
        trace_id=summary.trace_id,
        request_id=summary.request_id,
        user_id=summary.user_id,
        usecase_id=summary.usecase_id,
        model_id=summary.model_id,
        provider=summary.provider,
        region=summary.region,
        status=summary.status,
        started_at=summary.started_at,
        ended_at=summary.ended_at,
        duration_ms=summary.duration_ms,
        spans=spans,
    )


@app.get("/api/models/catalog", response_model=ModelCatalogResponse)
async def model_catalog() -> ModelCatalogResponse:
    catalog: dict[str, dict[str, str | bool]] = {}

    for model_id in sorted(set(MODEL_HANDLERS.keys()) | set(MODEL_CATALOG.keys())):
        meta = MODEL_CATALOG.get(model_id, {"provider": "unknown", "region": "us-central"})
        provider = str(meta.get("provider", "unknown"))
        region = str(meta.get("region", "us-central"))
        catalog[model_id] = {
            "provider": provider,
            "region": region,
            "on_prem": provider in {"on-prem", "onprem", "self-hosted", "selfhosted"},
        }

    # Include runtime-discovered models/providers from events.
    for event in _load_events(limit=50000, newest_first=True):
        if event.model_id not in catalog:
            provider = event.provider or "unknown"
            region = event.region or "us-central"
            catalog[event.model_id] = {
                "provider": provider,
                "region": region,
                "on_prem": str(provider).lower() in {"on-prem", "onprem", "self-hosted", "selfhosted"},
            }

    models = [
        ModelCatalogItem(
            model_id=model_id,
            provider=str(meta["provider"]),
            region=str(meta["region"]),
            on_prem=bool(meta["on_prem"]),
        )
        for model_id, meta in sorted(catalog.items(), key=lambda item: item[0])
    ]
    providers = sorted({m.provider for m in models})

    return ModelCatalogResponse(
        generated_at=datetime.now(timezone.utc),
        models=models,
        providers=providers,
    )


@app.get("/api/models/metrics", response_model=ModelMetricsResponse)
async def model_metrics(
    window_seconds: int = Query(default=60, ge=10, le=3600),
    usecase_id: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    model_id: str | None = Query(default=None),
    service: str | None = Query(default=None),
    status: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    time_from: datetime | None = Query(default=None),
    time_to: datetime | None = Query(default=None),
    latency_slo_ms: float = Query(default=DEFAULT_LATENCY_SLO_MS, gt=0.0),
    token_slo_tps: float = Query(default=DEFAULT_TOKEN_SLO_TPS, gt=0.0),
    warm_threshold: float = Query(default=0.2, ge=0.0, le=1.0),
    degrading_threshold: float = Query(default=0.5, ge=0.0, le=1.0),
    critical_threshold: float = Query(default=0.8, ge=0.0, le=1.0),
) -> ModelMetricsResponse:
    if not (warm_threshold < degrading_threshold < critical_threshold):
        raise HTTPException(
            status_code=400,
            detail="thresholds must satisfy warm_threshold < degrading_threshold < critical_threshold",
        )
    time_from = _as_utc(time_from)
    time_to = _as_utc(time_to)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=window_seconds)
    events = [
        e
        for e in _load_events(
            time_from=max(window_start, time_from) if time_from else window_start,
            time_to=time_to,
        )
        if _matches_event_filters(
            e,
            usecase_id=usecase_id,
            request_id=request_id,
            model_id=model_id,
            service=service,
            status=status,
            provider=provider,
            tenant_id=tenant_id,
            time_from=max(window_start, time_from) if time_from else window_start,
            time_to=time_to,
            default_service="router",
        )
    ]
    grouped: dict[str, list[TelemetryEvent]] = defaultdict(list)
    for event in events:
        grouped[event.model_id].append(event)

    records: list[ModelMetric] = []
    for model_id, model_events in grouped.items():
        req_count = len(model_events)
        fail_count = sum(1 for e in model_events if e.status == "failure")
        in_tokens = sum(e.input_tokens for e in model_events)
        out_tokens = sum(e.output_tokens for e in model_events)
        total_cost = sum(e.cost_usd for e in model_events)
        latencies = sorted(e.latency_ms for e in model_events)
        p95_index = int(len(latencies) * 0.95) - 1
        p95_index = max(0, p95_index)
        p95 = float(latencies[p95_index]) if latencies else 0.0
        avg_lat = float(mean(latencies)) if latencies else 0.0
        req_rate = req_count / float(window_seconds)
        token_rate = (in_tokens + out_tokens) / float(window_seconds)
        cost_rate = total_cost / float(window_seconds)
        failure_rate = fail_count / float(req_count) if req_count else 0.0
        sample = model_events[-1]
        records.append(
            ModelMetric(
                model_id=model_id,
                provider=sample.provider,
                region=sample.region,
                request_count=req_count,
                failure_count=fail_count,
                total_input_tokens=in_tokens,
                total_output_tokens=out_tokens,
                request_rate_rps=round(req_rate, 3),
                token_rate_tps=round(token_rate, 2),
                failure_rate=round(failure_rate, 3),
                avg_latency_ms=round(avg_lat, 2),
                p95_latency_ms=round(p95, 2),
                avg_cost_usd=round(total_cost / req_count, 6) if req_count else 0.0,
                cost_rate_usd_s=round(cost_rate, 6),
                risk_score=0.0,
                health_color="#68f0c3",
                edge_width=4.0,
            )
        )

    # Second pass to compute normalized risk and style fields.
    for rec in records:
        token_norm = min(1.0, rec.token_rate_tps / token_slo_tps) if token_slo_tps else 0.0
        p95_norm = min(1.0, rec.p95_latency_ms / latency_slo_ms) if latency_slo_ms else 0.0
        risk = min(1.0, 0.5 * rec.failure_rate + 0.3 * p95_norm + 0.2 * token_norm)
        rec.risk_score = round(risk, 3)
        rec.health_color = risk_to_color(
            risk,
            warm_threshold=warm_threshold,
            degrading_threshold=degrading_threshold,
            critical_threshold=critical_threshold,
        )
        rec.edge_width = round(3.0 + (rec.request_rate_rps * 2.0), 2)

    records.sort(key=lambda r: (r.request_rate_rps, r.token_rate_tps), reverse=True)
    return ModelMetricsResponse(window_seconds=window_seconds, generated_at=now, models=records)


@app.get("/api/stream")
async def stream_events(
    request: Request,
    user_id: str | None = None,
    model_id: str | None = None,
    service: str | None = None,
    status: str | None = None,
):
    queue = store.subscribe()

    async def generator():
        try:
            async for chunk in store.sse_stream(
                queue, user_id, model_id, service, status, shutdown_event=SHUTDOWN_EVENT
            ):
                if await request.is_disconnected() or SHUTDOWN_EVENT.is_set():
                    break
                yield chunk
        finally:
            store.unsubscribe(queue)

    return StreamingResponse(generator(), media_type="text/event-stream")


async def consume_kafka() -> None:
    try:
        from aiokafka import AIOKafkaConsumer
    except Exception:
        return

    consumer = AIOKafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_group_id,
        auto_offset_reset="latest",
    )
    await consumer.start()
    try:
        async for msg in consumer:
            try:
                payload = json.loads(msg.value.decode("utf-8"))
                publish_event(TelemetryEvent(**payload))
            except Exception:
                continue
    finally:
        await consumer.stop()


async def simulate_traffic() -> None:
    users = ["alice", "bob", "charlie", "sre"]
    models = [
        "gpt-4.1",
        "gpt-4o-mini",
        "claude-sonnet",
        "llama-3.3",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
    ]

    while True:
        await asyncio.sleep(random.uniform(0.25, 1.1))
        is_failure = random.random() < 0.11
        model_id = random.choice(models)
        meta = MODEL_CATALOG.get(model_id, {"provider": "unknown", "region": "us-central"})
        event = TelemetryEvent(
            request_id=str(uuid.uuid4()),
            user_id=random.choice(users),
            usecase_id=random.choice(["chat-assist", "policy-review", "triage"]),
            model_id=model_id,
            tenant_id=random.choice(["tenant-a", "tenant-b", "tenant-c"]),
            provider=meta["provider"],
            region=meta["region"],
            service=random.choice(["router", "armor", "mongo", "oracle"]),
            status="failure" if is_failure else "success",
            status_code=500 if is_failure else 200,
            input_tokens=random.randint(50, 3200),
            output_tokens=random.randint(20, 2200),
            latency_ms=random.randint(80, 2000),
            cost_usd=round(random.uniform(0.0005, 0.03), 5),
            error="timeout" if is_failure else None,
        )
        publish_event(event)


async def _handler_gpt41(prompt: str) -> tuple[str, int, int, bool]:
    await asyncio.sleep(random.uniform(0.12, 0.45))
    failed = random.random() < 0.07
    in_t = max(1, len(prompt) // 4)
    out_t = random.randint(80, 420)
    return ("gpt-4.1 response" if not failed else "model timeout", in_t, out_t, failed)


async def _handler_gpt4omini(prompt: str) -> tuple[str, int, int, bool]:
    await asyncio.sleep(random.uniform(0.08, 0.3))
    failed = random.random() < 0.05
    in_t = max(1, len(prompt) // 4)
    out_t = random.randint(60, 280)
    return ("gpt-4o-mini response" if not failed else "model timeout", in_t, out_t, failed)


async def _handler_claude(prompt: str) -> tuple[str, int, int, bool]:
    await asyncio.sleep(random.uniform(0.15, 0.5))
    failed = random.random() < 0.06
    in_t = max(1, len(prompt) // 4)
    out_t = random.randint(90, 390)
    return ("claude-sonnet response" if not failed else "model timeout", in_t, out_t, failed)


async def _handler_llama(prompt: str) -> tuple[str, int, int, bool]:
    await asyncio.sleep(random.uniform(0.09, 0.36))
    failed = random.random() < 0.09
    in_t = max(1, len(prompt) // 4)
    out_t = random.randint(50, 320)
    return ("llama-3.3 response" if not failed else "model timeout", in_t, out_t, failed)


async def _handler_gemini_pro(prompt: str) -> tuple[str, int, int, bool]:
    await asyncio.sleep(random.uniform(0.12, 0.42))
    failed = random.random() > 0.06 # Have changed the condition to simulate negative scenario
    in_t = max(1, len(prompt) // 4)
    out_t = random.randint(100, 430)
    return ("gemini-2.5-pro response" if not failed else "model timeout", in_t, out_t, failed)


async def _handler_gemini_flash(prompt: str) -> tuple[str, int, int, bool]:
    await asyncio.sleep(random.uniform(0.07, 0.24))
    failed = random.random() < 0.05
    in_t = max(1, len(prompt) // 4)
    out_t = random.randint(55, 260)
    return ("gemini-2.5-flash response" if not failed else "model timeout", in_t, out_t, failed)


MODEL_HANDLERS = {
    "gpt-4.1": _handler_gpt41,
    "gpt-4o-mini": _handler_gpt4omini,
    "gpt-4.5": _handler_gpt41,
    "o3-mini": _handler_gpt41,
    "o4-mini": _handler_gpt41,
    "claude-sonnet": _handler_claude,
    "claude-opus": _handler_claude,
    "claude-haiku": _handler_claude,
    "llama-3.3": _handler_llama,
    "llama-3.1-70b": _handler_llama,
    "llama-3.1-8b": _handler_llama,
    "gemini-2.5-pro": _handler_gemini_pro,
    "gemini-2.5-flash": _handler_gemini_flash,
    "gemini-1.5-pro": _handler_gemini_pro,
    "gemini-1.5-flash": _handler_gemini_flash,
    "mistral-large": _handler_gpt4omini,
    "mixtral-8x7b": _handler_gpt4omini,
    "deepseek-r1": _handler_llama,
    "deepseek-v3": _handler_llama,
    "qwen-2.5-72b": _handler_llama,
    "qwen-2.5-32b": _handler_llama,
    "cohere-command-r": _handler_gpt4omini,
    "cohere-command-r-plus": _handler_gpt4omini,
    "onprem-coder-14b": _handler_llama,
    "onprem-reasoner-32b": _handler_llama,
}


def risk_to_color(
    risk: float,
    warm_threshold: float = 0.2,
    degrading_threshold: float = 0.5,
    critical_threshold: float = 0.8,
) -> str:
    if risk < warm_threshold:
        return "#68f0c3"
    if risk < degrading_threshold:
        return "#ffd166"
    if risk < critical_threshold:
        return "#ff9f43"
    return "#ff6b6b"


def _collect_traces(
    usecase_id: str | None = None,
    model_id: str | None = None,
    status: str | None = None,
    request_id: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
) -> dict[str, list[TelemetryEvent]]:
    traces: dict[str, list[TelemetryEvent]] = defaultdict(list)
    for event in _load_events(time_from=time_from, time_to=time_to):
        trace_key = event.trace_id or event.request_id
        if usecase_id and (event.usecase_id or event.tenant_id or "default") != usecase_id:
            continue
        if request_id and event.request_id != request_id:
            continue
        if model_id and event.model_id != model_id:
            continue
        if status and event.status != status:
            continue
        if time_from and event.timestamp < time_from:
            continue
        if time_to and event.timestamp > time_to:
            continue
        traces[trace_key].append(event)
    return traces


def _event_started_at(event: TelemetryEvent) -> datetime:
    if event.start_ts:
        return event.start_ts
    if event.latency_ms > 0:
        return event.timestamp - timedelta(milliseconds=event.latency_ms)
    return event.timestamp


def _event_ended_at(event: TelemetryEvent) -> datetime:
    return event.end_ts or event.timestamp


def _event_to_span(event: TelemetryEvent, index: int) -> TraceSpan:
    started_at = _event_started_at(event)
    ended_at = _event_ended_at(event)
    duration_ms = event.latency_ms or int(max(0.0, (ended_at - started_at).total_seconds() * 1000))
    return TraceSpan(
        trace_id=event.trace_id or event.request_id,
        request_id=event.request_id,
        span_id=event.span_id or f"{event.service}-{index}",
        parent_span_id=event.parent_span_id,
        stage=event.stage or event.service,
        component=event.component or event.service,
        service=event.service,
        status=event.status,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        model_id=event.model_id,
        provider=event.provider,
        region=event.region,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        latency_ms=event.latency_ms,
        cost_usd=event.cost_usd,
        status_code=event.status_code,
        error=event.error,
        details=event.details or {},
    )


def _build_trace_summary(trace_id: str, events: list[TelemetryEvent]) -> TraceRequestSummary:
    ordered = sorted(events, key=lambda e: _event_started_at(e))
    first = ordered[0]
    started_at = min(_event_started_at(e) for e in ordered)
    ended_at = max(_event_ended_at(e) for e in ordered)
    duration_ms = int(max(0.0, (ended_at - started_at).total_seconds() * 1000))
    failures = [e for e in ordered if e.status == "failure"]
    return TraceRequestSummary(
        trace_id=trace_id,
        request_id=first.request_id,
        user_id=first.user_id,
        usecase_id=first.usecase_id or first.tenant_id or "default",
        model_id=first.model_id,
        provider=first.provider,
        region=first.region,
        status="failure" if failures else "success",
        stage_count=len(ordered),
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        failure_stage=(failures[0].stage or failures[0].service) if failures else None,
    )


def _matches_event_filters(
    event: TelemetryEvent,
    usecase_id: str | None = None,
    request_id: str | None = None,
    model_id: str | None = None,
    service: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    tenant_id: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    default_service: str | None = None,
) -> bool:
    service_filter = service or default_service
    if usecase_id and (event.usecase_id or event.tenant_id or "default") != usecase_id:
        return False
    if request_id and event.request_id != request_id:
        return False
    if model_id and event.model_id != model_id:
        return False
    if service_filter and event.service != service_filter:
        return False
    if status and event.status != status:
        return False
    if provider and event.provider != provider:
        return False
    if tenant_id and event.tenant_id != tenant_id:
        return False
    if time_from and event.timestamp < time_from:
        return False
    if time_to and event.timestamp > time_to:
        return False
    return True


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_events(
    *,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    limit: int | None = None,
    newest_first: bool = False,
) -> list[TelemetryEvent]:
    events = history_store.list_events(
        time_from=time_from,
        time_to=time_to,
        limit=limit,
        newest_first=newest_first,
    )
    if events:
        return events
    # Fallback for startup edge cases before durable writer has persisted events.
    memory_events = list(store.events)
    if time_from:
        memory_events = [e for e in memory_events if e.timestamp >= time_from]
    if time_to:
        memory_events = [e for e in memory_events if e.timestamp <= time_to]
    if newest_first:
        memory_events = memory_events[::-1]
    if limit is not None:
        memory_events = memory_events[:limit]
    return memory_events
