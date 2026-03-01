import json
import uuid
from datetime import datetime, timezone

from kafka import KafkaProducer

BOOTSTRAP = "localhost:9092"
TOPIC = "model-events"

producer = KafkaProducer(bootstrap_servers=BOOTSTRAP)

event = {
    "request_id": str(uuid.uuid4()),
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "user_id": "alice",
    "model_id": "gpt-4.1",
    "tenant_id": "tenant-a",
    "provider": "openai",
    "region": "us-east-1",
    "service": "router",
    "status": "success",
    "status_code": 200,
    "input_tokens": 440,
    "output_tokens": 201,
    "latency_ms": 320,
    "cost_usd": 0.0064,
    "error": None,
}

producer.send(TOPIC, value=json.dumps(event).encode("utf-8"))
producer.flush()
print("sent", event["request_id"])
