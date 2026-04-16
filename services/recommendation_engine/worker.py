from __future__ import annotations

import asyncio

from services.common.aiops_common.audit import append_audit_event, get_engine, init_audit_db
from services.common.aiops_common.config import get_settings
from services.common.aiops_common.queue import consume_stream, get_redis_client, publish_stream
from services.common.aiops_common.schemas import ActionType, AuditEvent, Incident, Recommendation


def generate_recommendation(incident: Incident) -> Recommendation:
    actions = [ActionType.investigate]
    title = f"Investigate {incident.metric} on {incident.host}"
    rationale = "Correlation engine detected repeated signals for the same fingerprint."
    confidence = 0.65
    impact = "medium"

    metric_lower = incident.metric.lower()
    latest_value = incident.context.get("latest_value", 0)
    threshold = incident.context.get("threshold", 0)

    if "cpu" in metric_lower:
        actions = [ActionType.restart_agent, ActionType.investigate]
        rationale = "CPU saturation pattern detected; restarting agent can recover stuck collectors."
        confidence = 0.78
        impact = "high"
    elif "memory" in metric_lower:
        actions = [ActionType.clear_tmp, ActionType.investigate]
        rationale = "Memory pressure trend likely related to cache/tmp growth."
        confidence = 0.74
        impact = "high"
    elif latest_value and threshold and latest_value > threshold * 1.3:
        actions = [ActionType.restart_service, ActionType.investigate]
        rationale = "Metric significantly exceeds threshold. Service restart may reduce active incident time."
        confidence = 0.72
        impact = "high"

    return Recommendation(
        incident_id=incident.incident_id,
        title=title,
        rationale=rationale,
        confidence=confidence,
        impact=impact,
        proposed_actions=actions,
        metadata={"host": incident.host, "metric": incident.metric},
    )


async def main() -> None:
    settings = get_settings()
    redis = get_redis_client()
    audit_engine = get_engine()
    await init_audit_db(audit_engine)
    last_id = "0-0"

    try:
        while True:
            last_id, events = await consume_stream(redis, "incidents.created", last_id=last_id)
            for event in events:
                if event.get("suppressed"):
                    continue
                incident = Incident.model_validate(event)
                recommendation = generate_recommendation(incident)
                if recommendation.confidence < settings.recommendation_min_confidence:
                    continue

                payload = recommendation.model_dump(mode="json")
                await redis.set(
                    f"recommendation:{recommendation.recommendation_id}",
                    recommendation.model_dump_json(),
                    ex=86400,
                )
                await publish_stream(redis, "recommendations.created", payload)
                await append_audit_event(
                    audit_engine,
                    AuditEvent(
                        event_type="recommendation_created",
                        actor="recommendation-engine",
                        payload=payload,
                    ),
                )
            await asyncio.sleep(0.1)
    finally:
        await redis.close()
        await audit_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
