import asyncio
import json
from collections import deque
from typing import AsyncIterator

from .models import TelemetryEvent

MAX_EVENTS = 5000


class EventStore:
    def __init__(self) -> None:
        self.events: deque[TelemetryEvent] = deque(maxlen=MAX_EVENTS)
        self.subscribers: set[asyncio.Queue[TelemetryEvent]] = set()

    def append(self, event: TelemetryEvent) -> None:
        self.events.append(event)
        for queue in list(self.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue[TelemetryEvent]:
        queue: asyncio.Queue[TelemetryEvent] = asyncio.Queue(maxsize=500)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[TelemetryEvent]) -> None:
        self.subscribers.discard(queue)

    async def sse_stream(
        self,
        queue: asyncio.Queue[TelemetryEvent],
        user_id: str | None,
        model_id: str | None,
        service: str | None,
        status: str | None,
        shutdown_event: asyncio.Event | None = None,
    ) -> AsyncIterator[str]:
        heartbeat_seconds = 10
        while not (shutdown_event and shutdown_event.is_set()):
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                if _matches_filters(event, user_id, model_id, service, status):
                    payload = json.dumps(event.model_dump(mode="json"))
                    yield f"event: telemetry\\ndata: {payload}\\n\\n"
            except asyncio.TimeoutError:
                if shutdown_event and shutdown_event.is_set():
                    break
                yield "event: heartbeat\\ndata: {}\\n\\n"
            except asyncio.CancelledError:
                break


def _matches_filters(
    event: TelemetryEvent,
    user_id: str | None,
    model_id: str | None,
    service: str | None,
    status: str | None,
) -> bool:
    if user_id and event.user_id != user_id:
        return False
    if model_id and event.model_id != model_id:
        return False
    if service and event.service != service:
        return False
    if status and event.status != status:
        return False
    return True
