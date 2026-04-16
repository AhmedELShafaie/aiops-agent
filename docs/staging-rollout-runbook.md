# Staging Rollout Runbook

This runbook brings up the AIOps control plane in staging, validates end-to-end flow, and defines promotion criteria.

## 1) Prerequisites

- Kubernetes cluster access to a staging namespace.
- `kubectl` configured for target cluster.
- `python3` and `curl` available from operator workstation.
- Image available in registry:
  - `ghcr.io/example/aiops-agent:latest` (replace with your pinned tag for staging).

## 2) Configure staging secrets

1. Copy secret template and set real values:
   - `cp infra/k8s/secret-template.yaml /tmp/aiops-secrets-staging.yaml`
2. Edit `/tmp/aiops-secrets-staging.yaml` and replace:
   - `SLACK_SIGNING_SECRET`
   - `SLACK_BOT_TOKEN`
   - `REDIS_URL` (staging redis endpoint)
   - `AUDIT_DB_URL` (staging DB path/URL)

## 3) Deploy platform services

Run from repo root (`aiops-agent`):

```bash
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/configmap.yaml
kubectl apply -f /tmp/aiops-secrets-staging.yaml
kubectl apply -f infra/k8s/deployments.yaml
kubectl apply -f infra/k8s/services.yaml
kubectl apply -f infra/k8s/network-policy.yaml
```

Wait for rollouts:

```bash
kubectl -n aiops rollout status deploy/ingest-gateway
kubectl -n aiops rollout status deploy/approval-orchestrator
kubectl -n aiops rollout status deploy/correlation-engine
kubectl -n aiops rollout status deploy/recommendation-engine
kubectl -n aiops rollout status deploy/runbook-executor
```

## 4) Basic health checks

Port-forward APIs:

```bash
kubectl -n aiops port-forward svc/ingest-gateway 8001:80
kubectl -n aiops port-forward svc/approval-orchestrator 8004:80
```

In a second terminal:

```bash
curl -sS http://localhost:8001/health
curl -sS http://localhost:8004/health
```

Expected: both return `{"status":"ok"}`.

## 5) Send synthetic telemetry

Run:

```bash
python3 scripts/send_synthetic_alerts.py --url http://localhost:8001 --client-id staging-e2e --count 20
```

Expected: all requests return `queued` responses with `signal_id`.

## 6) Validate pipeline behavior

1. Confirm recommendations are generated:

```bash
curl -sS http://localhost:8004/api/recommendations | python3 -m json.tool
```

2. Pick one `recommendation_id` and submit approval:

```bash
curl -sS -X POST "http://localhost:8004/api/recommendations/<recommendation_id>/decision" \
  -H "content-type: application/json" \
  -d '{
    "recommendation_id":"<recommendation_id>",
    "approver":"staging-oncall",
    "approved":true,
    "reason":"staging validation"
  }'
```

Expected:
- Decision response: `{"status":"recorded"}`
- Runbook request emitted and processed by `runbook-executor`
- Audit events written for decision and execution

3. Verify workers are live:

```bash
kubectl -n aiops get pods -o wide
kubectl -n aiops describe pod -l app=correlation-engine
kubectl -n aiops describe pod -l app=recommendation-engine
kubectl -n aiops describe pod -l app=runbook-executor
```

Expected: liveness probes healthy and no crash loops.

## 7) Observability checks

Inspect logs:

```bash
kubectl -n aiops logs deploy/ingest-gateway --tail=200
kubectl -n aiops logs deploy/correlation-engine --tail=200
kubectl -n aiops logs deploy/recommendation-engine --tail=200
kubectl -n aiops logs deploy/approval-orchestrator --tail=200
kubectl -n aiops logs deploy/runbook-executor --tail=200
```

Check for:
- No unhandled exceptions.
- Events flowing in expected order.
- No prolonged processing gaps.

## 8) Acceptance criteria (staging exit gates)

Promote only if all criteria pass:

- Availability
  - All deployments healthy for 24h continuously.
  - No `CrashLoopBackOff` or liveness probe flapping.
- Functional E2E
  - At least 50 synthetic + 50 real telemetry events ingested.
  - At least 10 recommendations generated.
  - At least 5 approved remediations executed successfully.
- Security and controls
  - Slack signature validation enabled and tested with malformed timestamp.
  - Secrets sourced from non-template values.
  - Approval gate enforced for all runbook executions.
- Quality
  - Duplicate alert reduction visible in correlation outputs.
  - Recommendation precision (manual spot-check) >= 70% helpful.
- Auditability
  - Every ingestion/decision/execution has a corresponding audit event.

## 9) Rollback plan

If severe errors are detected:

```bash
kubectl -n aiops rollout undo deploy/ingest-gateway
kubectl -n aiops rollout undo deploy/correlation-engine
kubectl -n aiops rollout undo deploy/recommendation-engine
kubectl -n aiops rollout undo deploy/approval-orchestrator
kubectl -n aiops rollout undo deploy/runbook-executor
```

If issue persists, scale worker components to zero to stop actions:

```bash
kubectl -n aiops scale deploy/correlation-engine --replicas=0
kubectl -n aiops scale deploy/recommendation-engine --replicas=0
kubectl -n aiops scale deploy/runbook-executor --replicas=0
```

## 10) Post-rollout tuning checklist

- Tune `SUPPRESSION_SCORE_THRESHOLD` if too many noisy incidents pass through.
- Tune `RECOMMENDATION_MIN_CONFIDENCE` if recommendation quality is low.
- Review weekly:
  - false positives,
  - false negatives,
  - mean time from alert to approved action.
