#!/usr/bin/env python3
"""Generate branched trace demo data for Trace Explorer.

Usage:
  python backend/scripts/produce_trace_demo.py --base-url http://localhost:8000 --traces 12
"""

from __future__ import annotations

import argparse
import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from urllib import request


MODELS = [
    ("gpt-4.1", "openai", "us-east-1"),
    ("claude-sonnet", "anthropic", "us-west-2"),
    ("gemini-2.5-pro", "google", "us-central1"),
    ("llama-3.3", "meta", "us-central-1"),
]

USERS = ["alice", "bob", "charlie", "diana"]
USECASES = ["support-triage", "kyc-screening", "fraud-check", "doc-summarization"]


def _post_event(base_url: str, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url.rstrip('/')}/api/events",
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=10):
        return


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat()


def _emit(
    *,
    base_url: str,
    request_id: str,
    trace_id: str,
    user_id: str,
    usecase_id: str,
    tenant_id: str,
    model_id: str,
    provider: str,
    region: str,
    stage: str,
    service: str,
    parent_span_id: str | None,
    start_ts: datetime,
    latency_ms: int,
    status: str = "success",
    status_code: int = 200,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    error: str | None = None,
    details: dict | None = None,
) -> str:
    span_id = uuid.uuid4().hex[:16]
    end_ts = start_ts + timedelta(milliseconds=latency_ms)
    payload = {
        "request_id": request_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "stage": stage,
        "component": service,
        "timestamp": _iso(end_ts),
        "start_ts": _iso(start_ts),
        "end_ts": _iso(end_ts),
        "usecase_id": usecase_id,
        "user_id": user_id,
        "model_id": model_id,
        "tenant_id": tenant_id,
        "provider": provider,
        "region": region,
        "service": service,
        "status": status,
        "status_code": status_code,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "cost_usd": round(cost_usd, 6),
        "error": error,
        "details": details or {},
    }
    _post_event(base_url, payload)
    return span_id


def generate_trace(base_url: str, seed_ts: datetime) -> None:
    request_id = str(uuid.uuid4())
    trace_id = request_id
    user_id = random.choice(USERS)
    usecase_id = random.choice(USECASES)
    tenant_id = random.choice(["tenant-a", "tenant-b"])
    model_id, provider, region = random.choice(MODELS)

    # Root
    validation = _emit(
        base_url=base_url,
        request_id=request_id,
        trace_id=trace_id,
        user_id=user_id,
        usecase_id=usecase_id,
        tenant_id=tenant_id,
        model_id=model_id,
        provider=provider,
        region=region,
        stage="validation",
        service="orchestrator",
        parent_span_id=None,
        start_ts=seed_ts,
        latency_ms=random.randint(4, 18),
        details={"check": ["auth", "schema", "quota"]},
    )

    # Parallel branches under validation
    mongo = _emit(
        base_url=base_url,
        request_id=request_id,
        trace_id=trace_id,
        user_id=user_id,
        usecase_id=usecase_id,
        tenant_id=tenant_id,
        model_id=model_id,
        provider=provider,
        region=region,
        stage="config_read",
        service="mongo",
        parent_span_id=validation,
        start_ts=seed_ts + timedelta(milliseconds=20),
        latency_ms=random.randint(15, 55),
        details={"collection": "routing_config"},
    )
    oracle = _emit(
        base_url=base_url,
        request_id=request_id,
        trace_id=trace_id,
        user_id=user_id,
        usecase_id=usecase_id,
        tenant_id=tenant_id,
        model_id=model_id,
        provider=provider,
        region=region,
        stage="datasource_read",
        service="oracle",
        parent_span_id=validation,
        start_ts=seed_ts + timedelta(milliseconds=24),
        latency_ms=random.randint(25, 80),
        details={"table": "tenant_policy"},
    )
    armor = _emit(
        base_url=base_url,
        request_id=request_id,
        trace_id=trace_id,
        user_id=user_id,
        usecase_id=usecase_id,
        tenant_id=tenant_id,
        model_id=model_id,
        provider=provider,
        region=region,
        stage="model_armor",
        service="armor",
        parent_span_id=validation,
        start_ts=seed_ts + timedelta(milliseconds=16),
        latency_ms=random.randint(10, 36),
        status="failure" if random.random() < 0.14 else "success",
        status_code=403 if random.random() < 0.14 else 200,
        details={"policy": "default-guardrail"},
    )

    # Another branch under mongo to show deeper branching
    rest = _emit(
        base_url=base_url,
        request_id=request_id,
        trace_id=trace_id,
        user_id=user_id,
        usecase_id=usecase_id,
        tenant_id=tenant_id,
        model_id=model_id,
        provider=provider,
        region=region,
        stage="rest_call",
        service="policy-api",
        parent_span_id=mongo,
        start_ts=seed_ts + timedelta(milliseconds=95),
        latency_ms=random.randint(30, 90),
        details={"endpoint": "/v1/policies/evaluate"},
    )

    failed_model = random.random() < 0.2
    in_tok = random.randint(120, 550)
    out_tok = random.randint(80, 460)
    total_cost = (in_tok + out_tok) / 1000.0 * random.uniform(0.0015, 0.012)

    model_span = _emit(
        base_url=base_url,
        request_id=request_id,
        trace_id=trace_id,
        user_id=user_id,
        usecase_id=usecase_id,
        tenant_id=tenant_id,
        model_id=model_id,
        provider=provider,
        region=region,
        stage="model_call",
        service="router",
        parent_span_id=rest,
        start_ts=seed_ts + timedelta(milliseconds=180),
        latency_ms=random.randint(220, 760),
        status="failure" if failed_model else "success",
        status_code=504 if failed_model else 200,
        input_tokens=in_tok,
        output_tokens=0 if failed_model else out_tok,
        cost_usd=0.0 if failed_model else total_cost,
        error="upstream_timeout" if failed_model else None,
        details={"target_model": model_id},
    )

    _emit(
        base_url=base_url,
        request_id=request_id,
        trace_id=trace_id,
        user_id=user_id,
        usecase_id=usecase_id,
        tenant_id=tenant_id,
        model_id=model_id,
        provider=provider,
        region=region,
        stage="response_write",
        service="orchestrator",
        parent_span_id=model_span,
        start_ts=seed_ts + timedelta(milliseconds=990),
        latency_ms=random.randint(4, 18),
        status="failure" if failed_model else "success",
        status_code=504 if failed_model else 200,
        error="upstream_timeout" if failed_model else None,
        details={"result": "error" if failed_model else "ok"},
    )

    # Keep the variables used to avoid "unused" lint if copied.
    _ = (oracle, armor)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate branched trace demo data.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--traces", type=int, default=10, help="Number of traces to generate")
    args = parser.parse_args()

    now = datetime.now(UTC)
    for i in range(max(1, args.traces)):
        seed = now - timedelta(seconds=max(0, (args.traces - i)) * random.uniform(2.5, 6.0))
        generate_trace(args.base_url, seed)

    print(f"Generated {args.traces} branched traces to {args.base_url}/api/events")


if __name__ == "__main__":
    main()

