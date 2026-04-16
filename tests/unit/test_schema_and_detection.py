from services.common.aiops_common.detection import build_fingerprint, normalize_event, suppression_score
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
