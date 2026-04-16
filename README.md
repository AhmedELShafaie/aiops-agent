# AIOps Agent

Self-hosted, human-approved AIOps control plane for monitoring 100-1,000 servers with Slack-first operations.

## Services

- `services/ingest_gateway`: ingest and normalize telemetry from mixed sources.
- `services/correlation_engine`: deduplicate, correlate, and suppress noisy alerts.
- `services/recommendation_engine`: generate ranked recommendations with confidence.
- `services/approval_orchestrator`: Slack approval workflow and policy enforcement.
- `services/runbook_executor`: controlled remediation execution (allowlisted runbooks only).
- `services/audit_log`: immutable decision and action journal.
- `apps/ops_dashboard`: basic operational visibility and KPI summaries.
- `services/common/aiops_common`: shared schemas, queueing, audit utilities, and config.

## Quick start

1. Install dependencies:
   - `python -m venv .venv && source .venv/bin/activate`
   - `pip install -e ".[dev]"`
2. Copy env file:
   - `cp .env.example .env`
3. Start infrastructure:
   - `docker compose up -d redis`
4. Run services (example):
   - `uvicorn services.ingest_gateway.main:app --port 8001 --reload`
   - `python -m services.correlation_engine.worker`
   - `python -m services.recommendation_engine.worker`
   - `uvicorn services.approval_orchestrator.main:app --port 8004 --reload`
   - `python -m services.runbook_executor.worker`
   - `uvicorn services.audit_log.main:app --port 8006 --reload`
   - `uvicorn apps.ops_dashboard.main:app --port 8080 --reload`

## Pipeline

1. Mixed-source telemetry enters `ingest_gateway`.
2. Signals are normalized and queued to `signals.raw`.
3. `correlation_engine` performs dedup/correlation and emits `incidents.created`.
4. `recommendation_engine` emits `recommendations.created`.
5. `approval_orchestrator` sends Slack approval and gates actions.
6. Approved actions are queued to `runbooks.requested`.
7. `runbook_executor` performs guarded execution and records outcomes.
8. All decisions/actions are appended to the audit database and queryable via `audit_log`.

## Production hardening included

- Rate limiting and idempotency keys on ingestion.
- Policy-driven approval gates.
- Immutable audit records with append-only API.
- Kubernetes manifests and Helm values stubs under `infra/`.
- Load and chaos test starters under `tests/load` and `tests/chaos`.
