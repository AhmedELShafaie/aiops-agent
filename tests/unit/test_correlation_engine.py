from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.common.aiops_common.schemas import NormalizedSignal, Severity, SignalSource
from services.correlation_engine.worker import build_correlation_key, process_signal


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}

    async def setnx(self, key: str, value: str) -> bool:
        if key in self._store:
            return False
        self._store[key] = value
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def expire(self, key: str, seconds: int) -> bool:
        _ = (key, seconds)
        return True

    async def sadd(self, key: str, value: str) -> int:
        self._sets.setdefault(key, set()).add(value)
        return len(self._sets[key])

    async def smembers(self, key: str) -> set[str]:
        return self._sets.get(key, set())


def _signal(
    signal_id: str,
    fingerprint: str,
    metric: str,
    value: float = 95,
    threshold: float = 80,
    anomaly_score: float = 0.8,
) -> NormalizedSignal:
    return NormalizedSignal(
        signal_id=signal_id,
        fingerprint=fingerprint,
        source=SignalSource.prometheus,
        host="srv-1",
        metric=metric,
        value=value,
        threshold=threshold,
        anomaly_score=anomaly_score,
        tags={"team": "ops"},
        observed_at=datetime.now(timezone.utc),
        severity=Severity.warning,
    )


def test_build_correlation_key_buckets_by_host_severity_and_metric_group() -> None:
    signal = _signal("s1", "f1", "cpu_usage")
    key = build_correlation_key(signal, dedup_window_seconds=300, epoch_second=1_700_000_000)
    assert key.startswith("srv-1:warning:cpu:")


@pytest.mark.asyncio
async def test_process_signal_deduplicates_and_updates_context() -> None:
    redis = FakeRedis()
    signal = _signal("s1", "fp-1", "memory_usage")
    first = await process_signal(redis, signal, dedup_window_seconds=300)
    assert first is not None
    assert first.event_count == 1

    second_signal = signal.model_copy(update={"signal_id": "s2", "value": 97})
    second = await process_signal(redis, second_signal, dedup_window_seconds=300)
    assert second is not None
    assert second.event_count == 2
    assert second.context["latest_value"] == 97
    assert len(second.correlated_signals) == 2


@pytest.mark.asyncio
async def test_process_signal_correlates_related_incidents_on_same_host() -> None:
    redis = FakeRedis()
    first = await process_signal(redis, _signal("s1", "fp-cpu-a", "cpu_usage"), dedup_window_seconds=300)
    second = await process_signal(redis, _signal("s2", "fp-cpu-b", "cpu_temp"), dedup_window_seconds=300)
    assert first is not None
    assert second is not None
    assert second.context["related_incident_count"] >= 1
    assert isinstance(second.context["related_incident_ids"], list)


@pytest.mark.asyncio
async def test_process_signal_sets_repeat_volume_suppression_reason() -> None:
    redis = FakeRedis()
    for idx in range(6):
        incident = await process_signal(
            redis,
            _signal(f"s{idx}", "fp-repeat", "disk_usage"),
            dedup_window_seconds=300,
        )
    assert incident is not None
    assert incident.event_count == 6
    assert "high_repeat_volume" in incident.suppression_reasons
