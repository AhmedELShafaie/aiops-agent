# Chaos Test Starters

Use these scenarios to validate resilience and SLO compliance before production rollout:

1. Kill one `correlation-engine` pod during peak ingest and verify no data loss in Redis stream replay.
2. Block Redis egress from `recommendation-engine` for 60 seconds and verify retries/backoff behavior.
3. Introduce 500ms network latency between `approval-orchestrator` and Redis and check p95 decision latency.
4. Restart `audit-log` and confirm append operations recover without dropped events.

Recommended tooling:

- Kubernetes: `litmus`, `chaos-mesh`, or `powerfulseal`.
- Containerized local: `toxiproxy` + scripted fault injection.
