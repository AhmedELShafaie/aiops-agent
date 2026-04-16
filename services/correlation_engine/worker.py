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
    incident_ttl_seconds = dedup_window_seconds * 4
    created = await redis.setnx(dedup_key, str(now))
    if created:
        incident = Incident(
            fingerprint=signal.fingerprint,
            host=signal.host,
            metric=signal.metric,
            severity=signal.severity,
            correlated_signals=[signal.signal_id],
            context={"latest_value": signal.value, "source": signal.source.value},
        )
        incident.suppression_score = suppression_score(incident)
        incident_key = f"incident:{incident.incident_id}"
        await redis.set(incident_key, incident.model_dump_json(), ex=incident_ttl_seconds)
        # Keep the dedup key for the full incident lifetime so new signals
        # route to the existing incident instead of creating duplicates.
        await redis.set(dedup_key, incident.incident_id, ex=incident_ttl_seconds)
        return incident

    incident_id = await redis.get(dedup_key)
    if not incident_id:
        # Dedup key can become stale across restarts or manual key eviction.
        # Recreate incident safely and reattach dedup state.
        incident = Incident(
            fingerprint=signal.fingerprint,
            host=signal.host,
            metric=signal.metric,
            severity=signal.severity,
            correlated_signals=[signal.signal_id],
            context={"latest_value": signal.value, "source": signal.source.value},
        )
        incident.suppression_score = suppression_score(incident)
        incident_key = f"incident:{incident.incident_id}"
        await redis.set(incident_key, incident.model_dump_json(), ex=incident_ttl_seconds)
        await redis.set(dedup_key, incident.incident_id, ex=incident_ttl_seconds)
        return incident

    incident_key = f"incident:{incident_id}"
    raw = await redis.get(incident_key)
    if not raw:
        return None

    incident = Incident.model_validate_json(raw)
    incident.event_count += 1
    incident.last_seen = datetime.now(timezone.utc)
    incident.correlated_signals.append(signal.signal_id)
    incident.suppression_score = suppression_score(incident)
    await redis.set(incident_key, incident.model_dump_json(), ex=incident_ttl_seconds)
    await redis.expire(dedup_key, incident_ttl_seconds)
    return incident


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
