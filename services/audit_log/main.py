from __future__ import annotations

import json
from datetime import datetime

from fastapi import FastAPI, Query
from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncEngine

from services.common.aiops_common.audit import AuditEventRecord, get_engine, init_audit_db

app = FastAPI(title="audit-log", version="0.1.0")


@app.on_event("startup")
async def startup() -> None:
    app.state.engine = get_engine()
    await init_audit_db(app.state.engine)


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.engine.dispose()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/events")
async def list_events(
    event_type: str | None = None,
    actor: str | None = None,
    since: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    engine: AsyncEngine = app.state.engine
    stmt: Select = select(AuditEventRecord).order_by(desc(AuditEventRecord.created_at)).limit(limit)
    if event_type:
        stmt = stmt.where(AuditEventRecord.event_type == event_type)
    if actor:
        stmt = stmt.where(AuditEventRecord.actor == actor)
    if since:
        stmt = stmt.where(AuditEventRecord.created_at >= since)

    async with engine.connect() as conn:
        rows = (await conn.execute(stmt)).scalars().all()
    return [
        {
            "event_id": row.event_id,
            "event_type": row.event_type,
            "actor": row.actor,
            "payload": json.loads(row.payload_json),
            "created_at": row.created_at,
        }
        for row in rows
    ]
