from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from services.common.aiops_common.config import get_settings
from services.common.aiops_common.schemas import AuditEvent


class Base(DeclarativeBase):
    pass


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    payload_json: Mapped[str] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.audit_db_url, future=True)


async def init_audit_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def append_audit_event(engine: AsyncEngine, event: AuditEvent) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine) as session:
        row = AuditEventRecord(
            event_id=event.event_id,
            event_type=event.event_type,
            actor=event.actor,
            payload_json=json.dumps(event.payload, default=str),
            created_at=event.created_at.astimezone(timezone.utc),
        )
        session.add(row)
        await session.commit()
