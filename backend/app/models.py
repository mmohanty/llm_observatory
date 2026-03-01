from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


Status = Literal["success", "failure"]


class TelemetryEvent(BaseModel):
    request_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: str
    model_id: str
    tenant_id: str = "default"
    provider: str = "unknown"
    region: str = "us-central"
    service: str
    status: Status
    status_code: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    error: str | None = None


class DashboardSummary(BaseModel):
    total_events: int
    success_count: int
    failure_count: int
    total_input_tokens: int
    total_output_tokens: int


class InferenceRequest(BaseModel):
    user_id: str
    prompt: str
    use_oracle: bool = False
    tenant_id: str = "default"


class InferenceResponse(BaseModel):
    request_id: str
    model_id: str
    provider: str
    region: str
    tenant_id: str
    status: Status
    output: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float


class ModelMetric(BaseModel):
    model_id: str
    provider: str
    region: str
    request_count: int
    failure_count: int
    total_input_tokens: int
    total_output_tokens: int
    request_rate_rps: float
    token_rate_tps: float
    failure_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    avg_cost_usd: float
    cost_rate_usd_s: float
    risk_score: float
    health_color: str
    edge_width: float


class ModelMetricsResponse(BaseModel):
    window_seconds: int
    generated_at: datetime
    models: list[ModelMetric]


class ModelCatalogItem(BaseModel):
    model_id: str
    provider: str
    region: str
    on_prem: bool = False


class ModelCatalogResponse(BaseModel):
    generated_at: datetime
    models: list[ModelCatalogItem]
    providers: list[str]
