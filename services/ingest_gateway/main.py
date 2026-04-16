from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from threading import Lock

from fastapi import Depends, FastAPI, Header, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from services.common.aiops_common.audit import append_audit_event, get_engine, init_audit_db
from services.common.aiops_common.config import Settings, get_settings
from services.common.aiops_common.detection import normalize_event
from services.common.aiops_common.queue import get_redis_client, publish_stream
from services.common.aiops_common.schemas import AuditEvent, TelemetryEvent
from services.ingest_gateway.adapters import (
    from_cloudwatch_alarm,
    from_datadog_event,
    from_prometheus_alert,
)

app = FastAPI(title="ingest-gateway", version="0.1.0")
_rate_cache: dict[str, list[int]] = defaultdict(list)
_rate_cache_lock = Lock()


@app.on_event("startup")
async def startup() -> None:
    app.state.redis = get_redis_client()
    app.state.audit_engine = get_engine()
    await init_audit_db(app.state.audit_engine)


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.redis.close()
    await app.state.audit_engine.dispose()


def get_redis() -> Redis:
    return app.state.redis


def get_audit_engine() -> AsyncEngine:
    return app.state.audit_engine


def check_rate_limit(client_id: str, settings: Settings) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    window_start = now - 60
    with _rate_cache_lock:
        bucket = [ts for ts in _rate_cache[client_id] if ts >= window_start]
        if len(bucket) >= settings.ingest_rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        bucket.append(now)
        _rate_cache[client_id] = bucket


async def check_idempotency(redis: Redis, event: TelemetryEvent) -> None:
    if not event.idempotency_key:
        return
    key = f"idempotency:{event.idempotency_key}"
    inserted = await redis.setnx(key, "1")
    if not inserted:
        raise HTTPException(status_code=409, detail="Duplicate idempotency key")
    await redis.expire(key, 3600)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _queue_event(
    event: TelemetryEvent,
    client_id: str,
    redis: Redis,
    audit_engine: AsyncEngine,
    settings: Settings,
) -> str:
    check_rate_limit(client_id, settings)
    await check_idempotency(redis, event)
    normalized = normalize_event(event)
    await publish_stream(redis, "signals.raw", normalized.model_dump(mode="json"))
    await append_audit_event(
        audit_engine,
        AuditEvent(
            event_type="signal_ingested",
            actor=f"gateway:{client_id}",
            payload=normalized.model_dump(mode="json"),
        ),
    )
    return normalized.signal_id


@app.post("/ingest")
async def ingest_event(
    event: TelemetryEvent,
    x_client_id: str = Header(default="unknown-client"),
    redis: Redis = Depends(get_redis),
    audit_engine: AsyncEngine = Depends(get_audit_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    signal_id = await _queue_event(event, x_client_id, redis, audit_engine, settings)
    return {"status": "queued", "signal_id": signal_id}


@app.post("/ingest/bulk")
async def ingest_bulk(
    events: list[TelemetryEvent],
    x_client_id: str = Header(default="unknown-client"),
    redis: Redis = Depends(get_redis),
    audit_engine: AsyncEngine = Depends(get_audit_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    queued = 0
    for event in events:
        await _queue_event(event, x_client_id, redis, audit_engine, settings)
        queued += 1
    await append_audit_event(
        audit_engine,
        AuditEvent(
            event_type="bulk_ingest_completed",
            actor=f"gateway:{x_client_id}",
            payload={"queued": queued},
        ),
    )
    return {"queued": queued}


@app.post("/ingest/source/{source_name}")
async def ingest_from_source(
    source_name: str,
    payload: dict,
    x_client_id: str = Header(default="unknown-client"),
    redis: Redis = Depends(get_redis),
    audit_engine: AsyncEngine = Depends(get_audit_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    adapter_map = {
        "prometheus": from_prometheus_alert,
        "datadog": from_datadog_event,
        "cloudwatch": from_cloudwatch_alarm,
    }
    if source_name not in adapter_map:
        raise HTTPException(status_code=400, detail=f"Unsupported source '{source_name}'")
    event = adapter_map[source_name](payload)
    signal_id = await _queue_event(event, x_client_id, redis, audit_engine, settings)
    return {"status": "queued", "signal_id": signal_id, "source": source_name}
