from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from services.common.aiops_common.audit import append_audit_event, get_engine, init_audit_db
from services.common.aiops_common.config import get_settings
from services.common.aiops_common.detection import suppression_score
from services.common.aiops_common.queue import consume_stream, get_redis_client, publish_stream
from services.common.aiops_common.schemas import AuditEvent, Incident, NormalizedSignal


async def process_signal(redis, signal: NormalizedSignal, dedup_window_seconds: int) -> Incident | None:
    now = int(datetime.now(timezone.utc).timestamp())
    dedup_key = f"dedup:{signal.fingerprint}"
    created = await redis.setnx(dedup_key, str(now))
    if created:
        await redis.expire(dedup_key, dedup_window_seconds)
        incident = Incident(
            fingerprint=signal.fingerprint,
            host=signal.host,
            metric=signal.metric,
            severity=signal.severity,
            correlated_signals=[signal.signal_id],
            context={"latest_value": signal.value, "source": signal.source.value},
        )
        incident.suppression_score = suppression_score(incident)
        await redis.set(
            f"incident:{incident.incident_id}",
            incident.model_dump_json(),
            ex=dedup_window_seconds * 4,
        )
        return incident

    incident_ids = await redis.keys("incident:*")
    if not incident_ids:
        return None

    for key in incident_ids:
        raw = await redis.get(key)
        if not raw:
            continue
        incident = Incident.model_validate_json(raw)
        if incident.fingerprint != signal.fingerprint:
            continue
        incident.event_count += 1
        incident.last_seen = datetime.now(timezone.utc)
        incident.correlated_signals.append(signal.signal_id)
        incident.suppression_score = suppression_score(incident)
        await redis.set(key, incident.model_dump_json(), ex=dedup_window_seconds * 4)
        return incident
    return None


async def main() -> None:
    settings = get_settings()
    redis = get_redis_client()
    audit_engine = get_engine()
    await init_audit_db(audit_engine)
    last_id = "0-0"

    try:
        while True:
            last_id, events = await consume_stream(redis, "signals.raw", last_id=last_id)
            for event in events:
                signal = NormalizedSignal.model_validate(event)
                incident = await process_signal(redis, signal, settings.dedup_window_seconds)
                if not incident:
                    continue
                suppressed = incident.suppression_score >= settings.suppression_score_threshold
                await publish_stream(
                    redis,
                    "incidents.created",
                    {
                        **incident.model_dump(mode="json"),
                        "suppressed": suppressed,
                    },
                )
                await append_audit_event(
                    audit_engine,
                    AuditEvent(
                        event_type="incident_correlated",
                        actor="correlation-engine",
                        payload={
                            "incident_id": incident.incident_id,
                            "suppressed": suppressed,
                            "suppression_score": incident.suppression_score,
                            "event_count": incident.event_count,
                        },
                    ),
                )
            await asyncio.sleep(0.1)
    finally:
        await redis.close()
        await audit_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
