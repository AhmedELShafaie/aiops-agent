from services.common.aiops_common.detection import (
    build_fingerprint,
    normalize_event,
    signal_quality_score,
    suppression_score,
)
from services.common.aiops_common.schemas import Incident, Severity, SignalSource, TelemetryEvent


def test_normalize_event_computes_anomaly_score() -> None:
    event = TelemetryEvent(
        source=SignalSource.prometheus,
        host="srv-1",
        metric="cpu_usage",
        value=91,
        threshold=80,
    )
    normalized = normalize_event(event)
    assert normalized.anomaly_score > 0
    assert normalized.fingerprint == build_fingerprint(event)


def test_suppression_score_increases_for_repeated_incident() -> None:
    incident = Incident(
        fingerprint="abc",
        host="srv-1",
        metric="disk_usage",
        severity=Severity.warning,
        event_count=12,
    )
    assert suppression_score(incident) >= 0.6


def test_signal_quality_score_rewards_critical_breach() -> None:
    event = TelemetryEvent(
        source=SignalSource.prometheus,
        host="srv-1",
        metric="cpu_usage",
        value=98,
        threshold=80,
        severity=Severity.critical,
        tags={"team": "platform", "service": "collector"},
    )
    normalized = normalize_event(event)
    assert signal_quality_score(normalized) >= 0.6


def test_suppression_score_penalizes_low_quality_bursts() -> None:
    incident = Incident(
        fingerprint="abc-low-quality",
        host="srv-1",
        metric="network_errors",
        severity=Severity.info,
        event_count=7,
        context={
            "signal_quality": 0.2,
            "related_incident_count": 3,
        },
    )
    assert suppression_score(incident) >= 0.7
