import asyncio
import json
import random
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
)
from .settings import settings
from .stream import EventStore

store = EventStore()
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
    SHUTDOWN_EVENT.clear()
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


app = FastAPI(title="LLM Observability API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/events")
async def ingest_event(event: TelemetryEvent) -> dict[str, str]:
    store.append(event)
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
    t0 = perf_counter()

    # Stage 1: model armor
    if random.random() < 0.04:
        event = TelemetryEvent(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            user_id=payload.user_id,
            model_id=model_id,
            tenant_id=payload.tenant_id,
            provider=meta["provider"],
            region=meta["region"],
            service="armor",
            status="failure",
            status_code=403,
            error="policy_violation",
        )
        store.append(event)
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

    store.append(
        TelemetryEvent(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            user_id=payload.user_id,
            model_id=model_id,
            tenant_id=payload.tenant_id,
            provider=meta["provider"],
            region=meta["region"],
            service="armor",
            status="success",
            status_code=200,
        )
    )

    # Stage 2: persistence sidecar event
    db_service = "oracle" if payload.use_oracle else "mongo"
    store.append(
        TelemetryEvent(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            user_id=payload.user_id,
            model_id=model_id,
            tenant_id=payload.tenant_id,
            provider=meta["provider"],
            region=meta["region"],
            service=db_service,
            status="success",
            status_code=200,
            latency_ms=random.randint(8, 35),
        )
    )

    # Stage 3: router -> model call
    output, input_tokens, output_tokens, failed = await MODEL_HANDLERS[model_id](payload.prompt)
    latency_ms = int((perf_counter() - t0) * 1000)
    status = "failure" if failed else "success"
    total_tokens = input_tokens + output_tokens
    cost_usd = (total_tokens / 1000.0) * TOKEN_COST_PER_1K.get(model_id, 0.0)

    store.append(
        TelemetryEvent(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            user_id=payload.user_id,
            model_id=model_id,
            tenant_id=payload.tenant_id,
            provider=meta["provider"],
            region=meta["region"],
            service="router",
            status=status,
            status_code=504 if failed else 200,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            error="upstream_timeout" if failed else None,
        )
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
    return list(store.events)[-limit:][::-1]


@app.get("/api/summary", response_model=DashboardSummary)
async def summary() -> DashboardSummary:
    events = list(store.events)
    success_count = sum(1 for e in events if e.status == "success")
    failure_count = len(events) - success_count
    return DashboardSummary(
        total_events=len(events),
        success_count=success_count,
        failure_count=failure_count,
        total_input_tokens=sum(e.input_tokens for e in events),
        total_output_tokens=sum(e.output_tokens for e in events),
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
    for event in store.events:
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
    user_id: str | None = Query(default=None),
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
        for e in store.events
        if _matches_event_filters(
            e,
            user_id=user_id,
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
                store.append(TelemetryEvent(**payload))
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
        store.append(event)


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


def _matches_event_filters(
    event: TelemetryEvent,
    user_id: str | None = None,
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
    if user_id and event.user_id != user_id:
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
