from __future__ import annotations

from services.common.aiops_common.schemas import Severity, SignalSource, TelemetryEvent


def from_prometheus_alert(payload: dict) -> TelemetryEvent:
    labels = payload.get("labels", {})
    annotations = payload.get("annotations", {})
    severity = Severity(labels.get("severity", "warning"))
    return TelemetryEvent(
        source=SignalSource.prometheus,
        host=labels.get("instance", "unknown-host"),
        metric=labels.get("alertname", "unknown_metric"),
        value=float(payload.get("value", 0.0)),
        threshold=_parse_float(annotations.get("threshold")),
        tags={k: str(v) for k, v in labels.items()},
        severity=severity,
    )


def from_datadog_event(payload: dict) -> TelemetryEvent:
    tags = payload.get("tags", [])
    tag_map = _tags_to_map(tags)
    return TelemetryEvent(
        source=SignalSource.datadog,
        host=tag_map.get("host", payload.get("host", "unknown-host")),
        metric=payload.get("alert_type", payload.get("title", "unknown_metric")),
        value=float(payload.get("alert_value", payload.get("value", 0.0))),
        threshold=_parse_float(payload.get("threshold")),
        tags=tag_map,
        severity=_severity_from_text(payload.get("priority", "warning")),
    )


def from_cloudwatch_alarm(payload: dict) -> TelemetryEvent:
    trigger = payload.get("Trigger", {})
    dimensions = trigger.get("Dimensions", [])
    host = next((d.get("value") for d in dimensions if d.get("name") == "InstanceId"), "unknown-host")
    return TelemetryEvent(
        source=SignalSource.cloudwatch,
        host=host,
        metric=payload.get("AlarmName", "unknown_metric"),
        value=_parse_float(payload.get("NewStateValue"), default=1.0),
        threshold=_parse_float(trigger.get("Threshold")),
        tags={"state": payload.get("NewStateValue", "UNKNOWN")},
        severity=Severity.critical if payload.get("NewStateValue") == "ALARM" else Severity.warning,
    )


def _parse_float(value: object, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tags_to_map(tags: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in tags:
        if ":" in item:
            key, value = item.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def _severity_from_text(value: str) -> Severity:
    lowered = value.lower()
    if lowered in {"critical", "p1", "high"}:
        return Severity.critical
    if lowered in {"info", "low"}:
        return Severity.info
    return Severity.warning
