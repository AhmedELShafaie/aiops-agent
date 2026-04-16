# Central Nginx Secure Ingress Setup

This guide deploys a hardened Nginx front-end for central AIOps ingestion with:

- TLS termination
- source IP allowlist
- API key enforcement
- optional HMAC payload integrity checks

It is designed for `ingest-gateway` (`:8001`) and Slack callback proxying to `approval-orchestrator` (`:8004`).

## 1) Install Nginx/OpenResty

Use OpenResty if you want HMAC checks at edge.

```bash
sudo dnf install -y nginx
```

If using OpenResty (recommended for HMAC):

```bash
sudo dnf install -y openresty
```

## 2) Copy configuration files

From repo root (`/root/aiops-agent`):

```bash
sudo mkdir -p /etc/nginx/conf.d /etc/nginx/lua /etc/nginx/secrets
sudo cp infra/nginx/aiops-central.conf /etc/nginx/conf.d/aiops-central.conf
sudo cp infra/nginx/hmac_access.lua /etc/nginx/lua/hmac_access.lua
```

## 3) Set secrets and keys

### API key

Edit:

```bash
sudo vi /etc/nginx/conf.d/aiops-central.conf
```

Replace:

- `REPLACE_WITH_STRONG_API_KEY` with a generated key (32+ chars).
- `aiops.example.com` with your domain.
- TLS cert/key paths if different.
- allowlisted CIDRs with your real monitoring egress ranges.

### HMAC secret

```bash
openssl rand -hex 32 | sudo tee /etc/nginx/secrets/aiops_hmac_secret >/dev/null
sudo chmod 600 /etc/nginx/secrets/aiops_hmac_secret
sudo chown root:root /etc/nginx/secrets/aiops_hmac_secret
```

If you are not using OpenResty/lua:

- Remove/comment `lua_access_by_lua_file` line from config.
- Keep API key + IP allowlist controls active.

## 4) TLS certificate provisioning

Use your existing PKI or certbot.

Example (public DNS):

```bash
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d aiops.example.com
```

## 5) Validate and reload

```bash
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

## 6) Test ingestion security controls

### 6.1 Source allowlist/API key checks

No key should fail:

```bash
curl -i -X POST "https://aiops.example.com/ingest" \
  -H "content-type: application/json" \
  -d '{"source":"prometheus","host":"test","metric":"cpu_usage","value":90}'
```

Expected: `401` (or `403` if source not allowlisted).

With API key:

```bash
curl -i -X POST "https://aiops.example.com/ingest" \
  -H "content-type: application/json" \
  -H "x-api-key: <YOUR_API_KEY>" \
  -d '{"source":"prometheus","host":"test","metric":"cpu_usage","value":90}'
```

Expected: passes key check (HMAC still required if enabled).

### 6.2 HMAC check (if enabled)

Use helper script to produce headers:

```bash
python3 scripts/sign_ingest_request.py \
  --url "https://aiops.example.com/ingest/source/prometheus" \
  --secret-file "/etc/nginx/secrets/aiops_hmac_secret" \
  --api-key "<YOUR_API_KEY>"
```

Expected: `200` with queued signal.

## 7) Monitoring and maintenance

- Rotate API key and HMAC secret regularly.
- Keep strict source CIDR allowlist.
- Monitor Nginx `401/403/429` rates for abuse patterns.
- Keep `/slack/actions` publicly reachable; rely on app-level Slack signature checks.

## 8) Operational cautions

- Do not expose internal recommendation/approval API endpoints publicly.
- Keep worker services private to cluster/VPC.
- Apply host firewall policy to only allow 80/443 from expected networks.
