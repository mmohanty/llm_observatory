from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "model-events"
    kafka_group_id: str = "llm-observability-dashboard"
    kafka_enabled: bool = False
    simulate_traffic: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
