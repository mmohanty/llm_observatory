from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "model-events"
    kafka_group_id: str = "llm-observability-dashboard"
    kafka_enabled: bool = False
    simulate_traffic: bool = False
    otel_enabled: bool = True
    otel_service_name: str = "llm-observability-api"
    otel_exporter_otlp_endpoint: str | None = None
    otel_exporter_otlp_insecure: bool = True
    telemetry_db_path: str = "backend/data/telemetry_history.db"
    telemetry_queue_size: int = 10000

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
