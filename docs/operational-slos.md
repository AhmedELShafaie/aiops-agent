# Operational SLOs

## Phase 1 targets

- Ingestion-to-insight latency: p95 < 60 seconds for critical telemetry.
- Noise reduction: 30-50% drop in duplicate alerts in 60 days.
- Recommendation precision: 70%+ operator helpful votes.
- Remediation approval coverage: 100% explicit approval before execution.
- Audit completeness: 100% decision and execution events persisted.

## Error budget guidance

- Monthly availability target for control plane APIs: 99.9%.
- If error budget burn rate > 2x for 1 hour:
  - Freeze feature rollout.
  - Prioritize stabilization and replay verification.
  - Require incident retrospective before re-enable.
