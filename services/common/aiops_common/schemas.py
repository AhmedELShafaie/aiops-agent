from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SignalSource(str, Enum):
    prometheus = "prometheus"
    datadog = "datadog"
    cloudwatch = "cloudwatch"
    custom = "custom"


class Severity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class ActionType(str, Enum):
    restart_service = "restart_service"
    clear_tmp = "clear_tmp"
    restart_agent = "restart_agent"
    investigate = "investigate"


class TelemetryEvent(BaseModel):
    source: SignalSource
    host: str
    metric: str
    value: float
    threshold: float | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=utc_now)
    severity: Severity = Severity.warning
    idempotency_key: str | None = None


class NormalizedSignal(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    fingerprint: str
    source: SignalSource
    host: str
    metric: str
    value: float
    threshold: float | None = None
    anomaly_score: float = 0.0
    tags: dict[str, str] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=utc_now)
    severity: Severity = Severity.warning


class Incident(BaseModel):
    incident_id: str = Field(default_factory=lambda: str(uuid4()))
    fingerprint: str
    host: str
    metric: str
    severity: Severity
    event_count: int = 1
    first_seen: datetime = Field(default_factory=utc_now)
    last_seen: datetime = Field(default_factory=utc_now)
    suppression_score: float = 0.0
    suppression_reasons: list[str] = Field(default_factory=list)
    correlation_key: str | None = None
    correlated_signals: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class Recommendation(BaseModel):
    recommendation_id: str = Field(default_factory=lambda: str(uuid4()))
    incident_id: str
    title: str
    rationale: str
    confidence: float
    impact: str
    proposed_actions: list[ActionType]
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    recommendation_id: str
    approver: str
    approved: bool
    reason: str | None = None
    decided_at: datetime = Field(default_factory=utc_now)


class RunbookRequest(BaseModel):
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    recommendation_id: str
    action: ActionType
    host: str
    requested_by: str
    requested_at: datetime = Field(default_factory=utc_now)
    parameters: dict[str, Any] = Field(default_factory=dict)


class RunbookResult(BaseModel):
    execution_id: str
    success: bool
    output: str
    finished_at: datetime = Field(default_factory=utc_now)


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    actor: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)
