from __future__ import annotations

import hashlib
from math import exp
from typing import Any

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


def signal_quality_score(signal: NormalizedSignal) -> float:
    threshold_defined = signal.threshold is not None and signal.threshold > 0
    threshold_component = 0.0
    if threshold_defined:
        threshold_component = min(1.0, max(signal.value / signal.threshold, 0.0) / 2.0)

    severity_component = {
        Severity.info: 0.2,
        Severity.warning: 0.6,
        Severity.critical: 1.0,
    }[signal.severity]
    tags_component = min(1.0, len(signal.tags) / 4)

    score = (
        signal.anomaly_score * 0.50
        + threshold_component * 0.20
        + severity_component * 0.20
        + tags_component * 0.10
    )
    return round(min(1.0, score), 4)


def _context_number(context: dict[str, Any], key: str, default: float) -> float:
    value = context.get(key, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, (float, int)):
        return float(value)
    return default


def suppression_score(incident: Incident) -> float:
    recent_volume_factor = min(1.0, incident.event_count / 8)
    signal_quality = _context_number(incident.context, "signal_quality", 0.8)
    related_incidents = _context_number(incident.context, "related_incident_count", 0.0)

    repeat_component = recent_volume_factor * 0.45
    low_quality_component = max(0.0, 1.0 - signal_quality) * 0.35
    severity_component = {
        Severity.info: 0.20,
        Severity.warning: 0.08,
        Severity.critical: 0.0,
    }[incident.severity]
    correlation_component = min(0.15, (related_incidents / 4.0) * 0.15)

    return round(
        min(1.0, repeat_component + low_quality_component + severity_component + correlation_component),
        4,
    )
