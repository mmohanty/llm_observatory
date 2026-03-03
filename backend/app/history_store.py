from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .models import TelemetryEvent


class HistoryStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    trace_id TEXT,
                    span_id TEXT,
                    parent_span_id TEXT,
                    stage TEXT,
                    component TEXT,
                    timestamp TEXT NOT NULL,
                    start_ts TEXT,
                    end_ts TEXT,
                    usecase_id TEXT,
                    user_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    tenant_id TEXT,
                    provider TEXT,
                    region TEXT,
                    service TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_code INTEGER,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    latency_ms INTEGER,
                    cost_usd REAL,
                    error TEXT,
                    details_json TEXT
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_ts ON telemetry_events(timestamp)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_trace ON telemetry_events(trace_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_user ON telemetry_events(user_id)"
            )
            self._conn.commit()

    def append(self, event: TelemetryEvent) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO telemetry_events (
                    request_id, trace_id, span_id, parent_span_id, stage, component,
                    timestamp, start_ts, end_ts, usecase_id,
                    user_id, model_id, tenant_id, provider, region,
                    service, status, status_code, input_tokens, output_tokens,
                    latency_ms, cost_usd, error, details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.request_id,
                    event.trace_id,
                    event.span_id,
                    event.parent_span_id,
                    event.stage,
                    event.component,
                    event.timestamp.isoformat(),
                    event.start_ts.isoformat() if event.start_ts else None,
                    event.end_ts.isoformat() if event.end_ts else None,
                    event.usecase_id,
                    event.user_id,
                    event.model_id,
                    event.tenant_id,
                    event.provider,
                    event.region,
                    event.service,
                    event.status,
                    event.status_code,
                    event.input_tokens,
                    event.output_tokens,
                    event.latency_ms,
                    event.cost_usd,
                    event.error,
                    json.dumps(event.details or {}),
                ),
            )
            self._conn.commit()

    def list_events(
        self,
        *,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> list[TelemetryEvent]:
        where: list[str] = []
        args: list[str | int] = []
        if time_from:
            where.append("timestamp >= ?")
            args.append(time_from.isoformat())
        if time_to:
            where.append("timestamp <= ?")
            args.append(time_to.isoformat())
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        order_sql = "DESC" if newest_first else "ASC"
        limit_sql = " LIMIT ?" if limit is not None else ""
        if limit is not None:
            args.append(int(limit))

        query = f"""
            SELECT * FROM telemetry_events
            {where_sql}
            ORDER BY timestamp {order_sql}, id {order_sql}
            {limit_sql}
        """
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _row_to_event(self, row: sqlite3.Row) -> TelemetryEvent:
        details = {}
        raw_details = row["details_json"]
        if raw_details:
            try:
                details = json.loads(raw_details)
            except Exception:
                details = {}
        return TelemetryEvent(
            request_id=row["request_id"],
            trace_id=row["trace_id"],
            span_id=row["span_id"],
            parent_span_id=row["parent_span_id"],
            stage=row["stage"],
            component=row["component"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            start_ts=datetime.fromisoformat(row["start_ts"]) if row["start_ts"] else None,
            end_ts=datetime.fromisoformat(row["end_ts"]) if row["end_ts"] else None,
            usecase_id=row["usecase_id"],
            user_id=row["user_id"],
            model_id=row["model_id"],
            tenant_id=row["tenant_id"] or "default",
            provider=row["provider"] or "unknown",
            region=row["region"] or "us-central",
            service=row["service"],
            status=row["status"],
            status_code=row["status_code"],
            input_tokens=int(row["input_tokens"] or 0),
            output_tokens=int(row["output_tokens"] or 0),
            latency_ms=int(row["latency_ms"] or 0),
            cost_usd=float(row["cost_usd"] or 0.0),
            error=row["error"],
            details=details,
        )

