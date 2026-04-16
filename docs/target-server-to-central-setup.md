# Targeted Server to Central AIOps Setup

This guide gives full, executable steps to connect one or many target servers to your central AIOps control plane.

## Architecture you will build

1. Each target server exports telemetry (`node_exporter`, optional `otelcol`).
2. Central monitoring stack (Prometheus/Alertmanager, Datadog, or CloudWatch) evaluates alerts.
3. Monitoring system sends alert events to central `ingest-gateway`.
4. AIOps processes incidents and sends approvals to Slack.

## A) Configure central AIOps server

Use this on your central host (or bastion) first.

### 1) Prepare central host

```bash
sudo dnf install -y git curl jq python3
mkdir -p /opt/aiops && cd /opt/aiops
git clone /root/aiops-agent .
cp .env.example .env
```

Edit `.env`:

- Set `REDIS_URL` to your central Redis.
- Set `SLACK_SIGNING_SECRET` and `SLACK_BOT_TOKEN`.
- Keep `ALLOWED_RUNBOOKS` limited to safe actions.

### 2) Start central services

```bash
docker compose up -d redis ingest-gateway approval-orchestrator audit-log
```

Start workers:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
nohup python3 -m services.correlation_engine.worker >/var/log/aiops-correlation.log 2>&1 &
nohup python3 -m services.recommendation_engine.worker >/var/log/aiops-recommendation.log 2>&1 &
nohup python3 -m services.runbook_executor.worker >/var/log/aiops-runbook.log 2>&1 &
```

### 3) Validate central APIs

```bash
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8004/health
```

Expected: `{"status":"ok"}` for both.

### 4) Expose central ingest endpoint

Expose only `/ingest` and `/ingest/source/*` behind TLS reverse proxy (nginx/ingress).

Production requirements:

- TLS enabled.
- Source IP allowlist for monitoring systems.
- Request auth (HMAC header/API key at proxy).
- Rate limiting at edge + app level.

## B) Configure target servers (resources collection)

Use this on every target server you want monitored.

### 1) Install node_exporter

```bash
sudo useradd --no-create-home --shell /sbin/nologin node_exporter || true
cd /tmp
curl -LO https://github.com/prometheus/node_exporter/releases/download/v1.9.1/node_exporter-1.9.1.linux-amd64.tar.gz
tar -xzf node_exporter-1.9.1.linux-amd64.tar.gz
sudo cp node_exporter-1.9.1.linux-amd64/node_exporter /usr/local/bin/
```

Create systemd service:

```bash
sudo tee /etc/systemd/system/node_exporter.service >/dev/null <<'EOF'
[Unit]
Description=Node Exporter
After=network-online.target
Wants=network-online.target

[Service]
User=node_exporter
Group=node_exporter
ExecStart=/usr/local/bin/node_exporter --web.listen-address=:9100
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
```

Validate:

```bash
curl -sS http://127.0.0.1:9100/metrics | head
```

### 2) (Optional) install OpenTelemetry Collector

If you also want logs/traces:

```bash
sudo dnf install -y otel-collector || true
```

Use your collector config to send to centralized telemetry backend (not directly to AIOps API).

## C) Connect central monitoring to central AIOps ingest

You can use one or more of these integrations.

### Option 1: Alertmanager -> AIOps ingest

1. Use config example from `examples/alertmanager/alertmanager.yml`.
2. Set webhook URL to your central endpoint:
   - `https://<central-domain>/ingest/source/prometheus`
3. Reload Alertmanager:

```bash
curl -X POST http://<alertmanager-host>:9093/-/reload
```

### Option 2: Datadog -> AIOps ingest

1. Create Datadog webhook integration targeting:
   - `https://<central-domain>/ingest/source/datadog`
2. Send alert JSON body compatible with adapter (see `examples/datadog/webhook_payload_example.json`).

### Option 3: CloudWatch -> AIOps ingest

Use API Gateway or Lambda forwarder to POST:

- `https://<central-domain>/ingest/source/cloudwatch`

## D) End-to-end validation with one target server

### 1) Verify target is scraped in Prometheus

In Prometheus UI, confirm `up{job="node"}` for target host is `1`.

### 2) Trigger a controlled alert on target

Generate CPU pressure briefly:

```bash
yes >/dev/null &
yes >/dev/null &
sleep 30
pkill yes
```

### 3) Check central AIOps receives and processes event

```bash
curl -sS http://127.0.0.1:8004/api/recommendations | jq .
```

You should see recommendation objects with incident context.

### 4) Approve one recommendation

```bash
curl -sS -X POST "http://127.0.0.1:8004/api/recommendations/<recommendation_id>/decision" \
  -H "content-type: application/json" \
  -d '{
    "recommendation_id":"<recommendation_id>",
    "approver":"oncall-user",
    "approved":true,
    "reason":"validation run"
  }'
```

## E) Scale to many target servers

1. Use Ansible playbook in `automation/ansible/install-node-exporter.yml`.
2. Add servers in `automation/ansible/inventory.ini`.
3. Run:

```bash
cd automation/ansible
ansible-playbook -i inventory.ini install-node-exporter.yml
```

4. Add all new targets to Prometheus scrape config.
5. Confirm alert volume and tune:
   - `SUPPRESSION_SCORE_THRESHOLD`
   - `RECOMMENDATION_MIN_CONFIDENCE`

## F) Production checklist before onboarding 100+ servers

- Enable TLS + auth for ingestion endpoint.
- Restrict source networks and enforce firewall policy.
- Add persistence and backups for audit DB.
- Add process supervision (systemd/Kubernetes) for workers.
- Run load test from `tests/load/locustfile.py`.
- Execute staging checklist from `docs/staging-rollout-runbook.md`.
