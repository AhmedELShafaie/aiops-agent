from __future__ import annotations

import hashlib
from math import exp

from services.common.aiops_common.schemas import Incident, NormalizedSignal, Severity, TelemetryEvent


def build_fingerprint(event: TelemetryEvent) -> str:
    raw = f"{event.source}:{event.host}:{event.metric}:{event.severity}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def compute_anomaly_score(value: float, threshold: float | None) -> float:
    if threshold is None or threshold <= 0:
        return 0.25
    ratio = max(value / threshold, 0.0)
    return min(1.0, 1 - exp(-max(0.0, ratio - 1.0) * 2.0))


def normalize_event(event: TelemetryEvent) -> NormalizedSignal:
    return NormalizedSignal(
        fingerprint=build_fingerprint(event),
        source=event.source,
        host=event.host,
        metric=event.metric,
        value=event.value,
        threshold=event.threshold,
        anomaly_score=compute_anomaly_score(event.value, event.threshold),
        tags=event.tags,
        observed_at=event.observed_at,
        severity=event.severity,
    )


def suppression_score(incident: Incident) -> float:
    recent_volume_factor = min(1.0, incident.event_count / 10)
    repeat_penalty = 0.2 if incident.event_count > 1 else 0.0
    low_severity_bonus = 0.25 if incident.severity == Severity.info else 0.0
    return min(1.0, recent_volume_factor * 0.6 + repeat_penalty + low_severity_bonus)
