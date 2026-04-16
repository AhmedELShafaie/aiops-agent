from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from services.common.aiops_common.audit import append_audit_event, get_engine, init_audit_db
from services.common.aiops_common.config import get_settings
from services.common.aiops_common.detection import signal_quality_score, suppression_score
from services.common.aiops_common.queue import consume_stream, get_redis_client, publish_stream
from services.common.aiops_common.schemas import AuditEvent, Incident, NormalizedSignal


def _to_text(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def build_correlation_key(signal: NormalizedSignal, dedup_window_seconds: int, epoch_second: int) -> str:
    bucket_size = max(60, dedup_window_seconds // 2)
    time_bucket = epoch_second // bucket_size
    metric_group = signal.metric.split("_")[0].lower()
    return f"{signal.host}:{signal.severity.value}:{metric_group}:{time_bucket}"


def _build_context(signal: NormalizedSignal) -> dict[str, object]:
    quality = signal_quality_score(signal)
    return {
        "latest_value": signal.value,
        "threshold": signal.threshold,
        "source": signal.source.value,
        "signal_quality": quality,
        "quality_samples": 1,
        "sources": [signal.source.value],
        "metrics": [signal.metric],
        "related_incident_ids": [],
        "related_incident_count": 0,
    }


def _refresh_context(incident: Incident, signal: NormalizedSignal) -> None:
    context = incident.context
    context["latest_value"] = signal.value
    context["threshold"] = signal.threshold
    context["source"] = signal.source.value

    samples = int(context.get("quality_samples", 1))
    current_quality = float(context.get("signal_quality", signal_quality_score(signal)))
    new_quality = signal_quality_score(signal)
    context["signal_quality"] = round(((current_quality * samples) + new_quality) / (samples + 1), 4)
    context["quality_samples"] = samples + 1

    sources = set(context.get("sources", []))
    sources.add(signal.source.value)
    context["sources"] = sorted(sources)

    metrics = set(context.get("metrics", []))
    metrics.add(signal.metric)
    context["metrics"] = sorted(metrics)


def _suppression_reasons(incident: Incident) -> list[str]:
    reasons: list[str] = []
    quality = float(incident.context.get("signal_quality", 1.0))
    related_count = int(incident.context.get("related_incident_count", 0))

    if incident.event_count >= 5:
        reasons.append("high_repeat_volume")
    if quality <= 0.35:
        reasons.append("low_signal_quality")
    if related_count >= 2:
        reasons.append("high_host_correlation_density")
    if incident.severity.value == "info":
        reasons.append("low_severity_signal")
    return reasons


async def _refresh_correlated_peers(redis, incident: Incident, incident_ttl_seconds: int) -> None:
    if not incident.correlation_key:
        return
    correlation_set_key = f"correlation:{incident.correlation_key}"
    await redis.sadd(correlation_set_key, incident.incident_id)
    await redis.expire(correlation_set_key, incident_ttl_seconds)
    peer_ids_raw = await redis.smembers(correlation_set_key)
    peer_ids = sorted(
        {
            _to_text(item)
            for item in peer_ids_raw
            if _to_text(item) and _to_text(item) != incident.incident_id
        }
    )
    incident.context["related_incident_ids"] = peer_ids[:10]
    incident.context["related_incident_count"] = len(peer_ids)


async def process_signal(redis, signal: NormalizedSignal, dedup_window_seconds: int) -> Incident | None:
    now = int(datetime.now(timezone.utc).timestamp())
    dedup_key = f"dedup:{signal.fingerprint}"
    incident_ttl_seconds = dedup_window_seconds * 4
    created = await redis.setnx(dedup_key, str(now))
    if created:
        correlation_key = build_correlation_key(signal, dedup_window_seconds, now)
        incident = Incident(
            fingerprint=signal.fingerprint,
            host=signal.host,
            metric=signal.metric,
            severity=signal.severity,
            correlation_key=correlation_key,
            correlated_signals=[signal.signal_id],
            context=_build_context(signal),
        )
        await _refresh_correlated_peers(redis, incident, incident_ttl_seconds)
        incident.suppression_score = suppression_score(incident)
        incident.suppression_reasons = _suppression_reasons(incident)
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
        correlation_key = build_correlation_key(signal, dedup_window_seconds, now)
        incident = Incident(
            fingerprint=signal.fingerprint,
            host=signal.host,
            metric=signal.metric,
            severity=signal.severity,
            correlation_key=correlation_key,
            correlated_signals=[signal.signal_id],
            context=_build_context(signal),
        )
        await _refresh_correlated_peers(redis, incident, incident_ttl_seconds)
        incident.suppression_score = suppression_score(incident)
        incident.suppression_reasons = _suppression_reasons(incident)
        incident_key = f"incident:{incident.incident_id}"
        await redis.set(incident_key, incident.model_dump_json(), ex=incident_ttl_seconds)
        await redis.set(dedup_key, incident.incident_id, ex=incident_ttl_seconds)
        return incident

    incident_id_text = _to_text(incident_id)
    if not incident_id_text:
        return None

    incident_key = f"incident:{incident_id_text}"
    raw = await redis.get(incident_key)
    if not raw:
        return None

    incident = Incident.model_validate_json(raw)
    incident.event_count += 1
    incident.last_seen = datetime.now(timezone.utc)
    incident.correlated_signals.append(signal.signal_id)
    _refresh_context(incident, signal)
    if not incident.correlation_key:
        incident.correlation_key = build_correlation_key(signal, dedup_window_seconds, now)
    await _refresh_correlated_peers(redis, incident, incident_ttl_seconds)
    incident.suppression_score = suppression_score(incident)
    incident.suppression_reasons = _suppression_reasons(incident)
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
                            "suppression_reasons": incident.suppression_reasons,
                            "event_count": incident.event_count,
                            "signal_quality": incident.context.get("signal_quality"),
                            "related_incident_count": incident.context.get("related_incident_count"),
                        },
                    ),
                )
            await asyncio.sleep(0.1)
    finally:
        await redis.close()
        await audit_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
